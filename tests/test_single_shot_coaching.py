import csv
import json
from pathlib import Path

import pytest

from backend.app.agent.coaching_agent import coach, response_text
from backend.app.agent.context import EvidenceContext
from backend.app.agent.evidence import RecordedShot
from backend.app.agent.memory import empty_memory
from backend.app.agent.video import shot_frames
from evaluation.fixtures import MockOpenAI


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def live_single_shot():
    trace = json.loads((ROOT / "evaluation/live-openai-single-shot.json").read_text(encoding="utf-8"))
    shot = trace["shot_evidence"]
    with (ROOT / "outputs/shot_features.csv").open(newline="", encoding="utf-8") as stream:
        row = next(row for row in csv.DictReader(stream) if row["video"] == shot["video_id"] + ".mp4")
    biomech = {key: float(row[key]) for key in shot["measurements"] if key in row}
    biomech.update(shooting_arm=row["shooting_arm"], measurement_quality=row["measurement_quality"],
                   valid_knee_frames=int(row["valid_knee_frames"]), valid_elbow_frames=int(row["valid_elbow_frames"]),
                   release_angle_valid=row["release_angle_valid"] == "True")
    return RecordedShot(shot["player"], shot["session_id"], shot["shot_id"], shot["video_id"], shot["outcome"],
                        shot["outcome_source"], {"shot_type": shot["conditions"]["shot_type"],
                                                "shot_events": shot["events"], "biomechanics": biomech}), trace["turns"]


def ask(shot, question, client, history=()):
    return coach(shot.player, question, selected=shot.shot_id, shots=[shot], history=history, client=client,
                 persist=False, memory_state=("", empty_memory()))


def request_parts(client, part):
    packets = (json.loads(item["text"]) for call in client.calls for message in call["inputs"]
               for item in message.get("content", [])
               if item.get("type") == "input_text" and item["text"].startswith("{"))
    return [packet for packet in packets if part in packet]


def test_replay_four_live_turns_without_provider(live_single_shot):
    shot, turns = live_single_shot
    replay = []
    for turn in turns:
        # Exercise the original requests, raw drafts and repairs. The tool calls run again on saved data.
        client = MockOpenAI([request["output"] for request in turn["requests"]] + [turn["requests"][-1]["output"]])
        history = turn["requests"][0]["initial_context"]["conversation"]
        replay.append((client, ask(shot, turn["question"], client, history)))

    first, analysis = replay[0]
    archived_first = next(request["tool_result"]["result"]["frames"] for request in turns[0]["requests"]
                          if "tool_result" in request)
    assert len({ref["frame"] for ref in archived_first}) < len(archived_first)
    preferred = request_parts(first, "selected_attempt_observations")[0]["selected_attempt_observations"]
    assert [record["field"] for record in preferred.values()] == ["min_knee_angle", "knee_angle_range"]
    repair = request_parts(first, "validation_details")[0]["validation_details"]
    assert any("131" in item["reason"] for item in repair)
    assert not any("88.8" in item["reason"] or item["field"] == "visual" for item in repair)
    assert len({ref["frame"] for ref in analysis.video_references}) == len(analysis.video_references)

    second, visual = replay[1]
    assert visual.video_references
    archived_second = next(request["tool_result"]["result"]["frames"] for request in turns[1]["requests"]
                           if "tool_result" in request)
    release = shot.analysis["shot_events"]["release_frame"]
    assert archived_second[-1]["frame"] == shot.analysis["shot_events"]["end_frame"] > release + 6
    assert all(ref["frame"] <= release + 6 for ref in visual.video_references)
    assert any(item["field"] == "visual" for item in request_parts(second, "validation_details")[0]["validation_details"])
    assert "extended forward" not in visual.message

    _, instructional = replay[2]
    assert turns[2]["requests"][1]["tool_result"]["result"]["resource_status"] == "no_match"
    assert instructional.instructional_resource.id == "jrnba_free_throw"
    assert "couldn’t find a verified" not in response_text(instructional)

    fourth, keep = replay[3]
    assert any("shooting habit" in item["reason"] for item in request_parts(fourth, "validation_details")[0]["validation_details"])
    assert "if that dip felt comfortable" in keep.message.lower()
    assert "a good habit to keep" not in keep.message


def test_visual_request_gets_frames_when_author_omits_ids(live_single_shot):
    shot, turns = live_single_shot
    client = MockOpenAI([turns[1]["requests"][0]["output"], {"message": "Compare the two labelled moments."}])
    result = ask(shot, turns[1]["question"], client)
    assert result.provenance["source"] == "openai_authored"
    assert [ref["phase"] for ref in result.video_references] == ["knee_dip", "release", "follow_through"]


def test_full_attempt_end_is_not_a_follow_through_frame(live_single_shot):
    shot, _ = live_single_shot
    refs = shot_frames(shot, ("release", "follow_through"), focus="elbow")
    assert [ref.frame for ref, _ in refs] == [49, 55]


def test_rounded_knee_measurement_and_stray_optional_tag_need_no_repair(live_single_shot):
    shot, _ = live_single_shot
    client = MockOpenAI([{"message": "Your knee bend at the deepest dip is about 88.8 degrees in this clip. "
                                      "Check whether the same comfortable setup appears on your next attempts.",
                          "visual": "arm_straightens"}])
    result = ask(shot, "Analyze my shooting form. What should I improve?", client)
    assert len(client.calls) == 1
    assert result.provenance["supporting_evidence_ids"] == [f"shot:{shot.shot_id}:min_knee_angle"]
    assert [item["field"] for item in result.provenance["discarded_components"]] == ["visual"]


def test_visual_question_without_tool_call_uses_reliable_saved_frames(live_single_shot):
    shot, _ = live_single_shot
    client = MockOpenAI([{"message": "Use the labelled phases to compare the setup and release."}])
    result = ask(shot, "Can you visually show me what you mean?", client)
    assert [ref["phase"] for ref in result.video_references] == ["knee_dip", "knee_extension"]
    assert all(ref["annotation"]["focus"] == "knee" for ref in result.video_references)


@pytest.mark.parametrize(("question", "topic", "expected"), [
    ("Can you recommend a specific instructional video and explain what I should focus on?", "shooting routine", "jrnba_free_throw"),
    ("Can you recommend a coaching video?", "how to shoot off a screen", "jrnba_using_a_screen_shooting_drill"),
])
def test_specific_tool_query_refreshes_explicit_request_catalog(live_single_shot, question, topic, expected):
    shot, _ = live_single_shot
    context = EvidenceContext(shot.player, question, shot.shot_id, (), [], empty_memory(), shots=[shot])
    context.collect(False)
    assert context.retrieve_knowledge(topic, "video")["resources"][0]["id"] == expected
    assert context.retrieve_knowledge(topic, "article")["resource_status"] == "no_match"


def test_unverified_title_does_not_survive_as_prose(live_single_shot):
    shot, _ = live_single_shot
    question = "Find a video about spin rpm."
    client = MockOpenAI([{"message": 'I recommend the video "Perfect Spin Workshop" by Basketball Experts. '
                                      'Compare clearly visible seams across frames.',
                         "instructional_resource_id": "invented"}])
    result = ask(shot, question, client)
    assert result.message == "Compare clearly visible seams across frames."
    assert result.instructional_resource is None and "couldn’t find a verified video" in result.guidance_note
    advice = "Watch the video for how the shooter settles into a comfortable rhythm."
    client = MockOpenAI([{"message": advice, "instructional_resource_id": "jrnba_free_throw"}])
    result = ask(shot, "Recommend a video for my shooting routine.", client)
    assert result.message == advice and result.instructional_resource.id == "jrnba_free_throw"
