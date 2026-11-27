import json
from dataclasses import replace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from streamlit.testing.v1 import AppTest

from backend.app.agent.coaching_agent import coach
from backend.app.agent.context import EvidenceContext
from backend.app.agent.memory import empty_memory, read_memory, save_memory
from backend.app.agent.player_input import player_update
from backend.app.agent.retrieval import CoachingTools
from backend.app.api.coaching import router
from evaluation.fixtures import MockOpenAI, fixture_focus, playground_scenario, scenario_input, synthetic_shot


def sessions(*plans, player="Fixture"):
    """One plan per session gives confirmed makes out of ten and angle variation."""
    return [
        synthetic_shot((session_id - 1) * 10 + index + 1, player=player, session_id=session_id,
                       outcome="made" if index < makes else "missed",
                       angle=125 + spread * (-1 if index % 2 else 1))
        for session_id, (makes, spread) in enumerate(plans, start=1)
        for index in range(10)
    ]


def offline(question, shots, *, memory=None, **options):
    return coach(shots[0].player, question, shots=shots, persist=False,
                 memory_state=("", memory or empty_memory()), **options)


@pytest.mark.parametrize(("plans", "overall", "accuracy", "consistency"), [
    ([(2, 9), (5, 5), (8, 2)], "favorable", "higher", "higher"),
    ([(5, 5), (5, 5), (5, 5)], "similar", "similar", "similar"),
    ([(2, 2), (5, 5), (8, 9)], "mixed", "higher", "lower"),
    ([(2, 5), (8, 5), (4, 5)], "mixed", "mixed", "similar"),
])
def test_session_comparison_without_objective_uses_bounded_ordered_samples(plans, overall, accuracy, consistency):
    shots = sessions((0, 20), *plans)
    result = offline("Am I improving?", shots)
    progress = result.progress
    assert progress["kind"] == "sessions"
    assert (progress["before_session_id"], progress["after_session_id"]) == (2, 4)
    assert [item["session_id"] for item in progress["intermediate"]] == [3]
    assert progress["assessment"] == {
        "overall": overall, "accuracy": accuracy, "consistency": consistency,
        "camera": "unknown", "phase": "estimated release",
    }
    assert progress["before"]["measurement_count"] == progress["after"]["measurement_count"] == 10
    assert result.practice is None and result.memory_update is None
    if overall == "mixed":
        assert "don’t establish overall improvement" in result.message
    if overall == "similar":
        assert "broadly similar" in result.message


def test_camera_change_unknown_outcomes_and_incompatible_conditions():
    shots = sessions((3, 8), (8, 3))
    shots = [replace(shot, outcome_source="auto") if shot.session_id == 2 else shot for shot in shots]
    shots[-1] = replace(shots[-1], outcome="unknown")
    answer = offline("Is my shooting form more consistent? The camera angle changed.", shots)
    assert answer.progress["assessment"]["consistency"] == "camera_changed"
    assert answer.progress["assessment"]["accuracy"] == "insufficient"
    assert answer.progress["after"]["unknown"] == 1
    assert "camera change" in answer.message and "too few confirmed outcomes" in answer.message
    answer = offline("Compare sessions 1 and 2. The sets were from different distances.", shots)
    assert answer.progress["status"] == "no_comparable_sessions" and "different distances" in answer.message
    shots = [shot for shot in shots if shot.session_id == 1] + [synthetic_shot(99, session_id=2, arm="left")]
    assert offline("Am I improving?", shots).progress["status"] == "no_comparable_sessions"


def test_model_cannot_turn_sparse_samples_into_improvement():
    shots = [synthetic_shot(1, outcome="missed"), synthetic_shot(2, session_id=2)]
    model = MockOpenAI([{"message": "Your shooting has improved."},
                       {"message": "We need more comparable attempts to judge progress."}])
    result = offline("Am I improving?", shots, client=model)
    assert result.provenance["source"] == "openai_repaired"
    assert result.progress["assessment"]["overall"] == "insufficient"
    assert len(model.calls) == 2


def test_saved_sessions_reuse_equivalent_annotated_frames():
    tools = CoachingTools("TestPlayer")
    earlier, later = tools.resolve("free_throw_03"), tools.resolve("free_throw_02")
    result = offline("Show me if my elbow is more consistent across sessions and recommend a video on elbow positioning.",
                     [earlier, later],
                     selected=later.shot_id, session_id=later.session_id)
    assert result.progress["assessment"]["overall"] == "insufficient"
    assert [(ref["session_id"], ref["phase"], ref["timestamp_s"]) for ref in result.video_references] == [
        (earlier.session_id, "release", 2.533), (later.session_id, "release", 0.833),
    ]
    assert all(ref["annotation"]["focus"] == "elbow" for ref in result.video_references)
    assert result.instructional_resource.id == "jrnba_two_hand_form"


def test_previous_unsuccessful_drill_is_available_for_review_and_excluded_from_next_focus():
    case = playground_scenario("unsuccessful")
    memory = case["memory"]
    prior = memory["recommendations"][0]
    prior["practice_instructions"] = "Rehearse the knee cue before every shot."
    result = offline("Why am I still struggling with the same problem?", case["shots"], memory=memory)
    assert result.previous_focus["practice_instructions"] == prior["practice_instructions"]
    assert "reported that the cue didn’t help" in result.message
    assert "hard to repeat" in result.clarification
    next_focus = offline("What should I focus on next?", case["shots"], memory=memory)
    assert next_focus.clarification or (next_focus.practice and next_focus.practice.drill_id != prior["drill_id"])


def test_effective_unconventional_form_keeps_the_player_technique():
    case = playground_scenario("consistent_high")
    result = offline("My form is unconventional but effective. Should I change it?", case["shots"])
    assert result.focus == "Individual technique"
    assert result.practice is None and result.memory_update is None


def test_helped_and_completed_advance_the_same_drill_by_one_rep():
    player = uuid4().hex
    shots = sessions((6, 5), (7, 3), player=player)
    focus = {**fixture_focus(shots[:10]), "session_id": 1, "drill_id": "focused_shooting",
             "prescribed_dose": {"sets": 1, "repetitions": 5, "duration_seconds": 75},
             "practice_instructions": "Use the same comfortable knee bend before each attempt."}
    memory = {**empty_memory(), "recommendations": [focus], "reports": [
        {"focus_id": focus["id"], "kind": kind, "text": kind} for kind in ("completed", "helped")
    ]}
    assert save_memory(player, "", memory)
    continued = coach(player, "Did the adjustment you recommended last time help?", shots=shots)
    assert continued.memory_update["id"] == focus["id"] and continued.memory_update["decision"] == "continue"
    revision, retained = read_memory(player)
    assert len(retained["recommendations"]) == 1
    assert coach(player, "Did the adjustment help?", shots=shots).memory_update is None
    assert read_memory(player)[0] == revision
    result = coach(player, "Can I make this drill more challenging?", shots=shots)
    assert result.memory_update["decision"] == "advance"
    assert result.practice.drill_id == focus["drill_id"] and result.cue == focus["cue"]
    assert result.practice.dose.model_dump() == {"sets": 1, "repetitions": 6, "duration_seconds": 90}
    assert "reported that this exercise helped" in result.message
    _, updated = read_memory(player)
    assert updated["recommendations"][-1]["previous_focus_id"] == focus["id"]
    assert updated["recommendations"][0] == retained["recommendations"][0]
    repeat = coach(player, "Can I make this drill more challenging?", shots=shots)
    assert repeat.memory_update is None and repeat.practice is None


def test_memory_corrections_replace_report_and_duplicate_writes_are_noops():
    player, other = uuid4().hex, uuid4().hex
    shots = sessions((5, 5), player=player)
    focus = fixture_focus(shots)
    assert save_memory(player, "", {**empty_memory(), "experience": "beginner", "goal": "Higher arc",
                                   "recommendations": [focus]})
    assert save_memory(other, "", {**empty_memory(), "goal": "Other player's goal"})
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    params = {"player_name": player}
    for kind in ("completed", "did_not_help", "helped"):
        request = {"focus_id": focus["id"], "report_kind": kind, "report": f"Player said {kind}."}
        assert client.patch("/api/coach/memory", params=params, json=request).status_code == 200
        revision = read_memory(player)[0]
        assert client.patch("/api/coach/memory", params=params, json=request).status_code == 200
        assert read_memory(player)[0] == revision
    assert [item["kind"] for item in read_memory(player)[1]["reports"]] == ["completed", "helped"]
    coach(player, "Actually, I didn't complete the drill.", shots=shots)
    result = coach(player, "Actually, I'm intermediate. My goal is more consistent free throws.", shots=shots)
    corrected = read_memory(player)[1]
    assert [item["kind"] for item in corrected["reports"]] == ["helped"]
    assert (corrected["experience"], corrected["goal"]) == ("intermediate", "more consistent free throws")
    assert result.practice is None and len(corrected["recommendations"]) == 1
    foreign = client.patch("/api/coach/memory", params={"player_name": other}, json={
        "focus_id": focus["id"], "report_kind": "did_not_help",
    })
    assert foreign.status_code == 409 and read_memory(other)[1]["reports"] == []
    assert read_memory(other)[1]["goal"] == "Other player's goal"


def test_context_only_sends_relevant_plan_and_owned_session_examples():
    shots = sessions(*[(5, 5)] * 15)
    focus = fixture_focus(shots[:10])
    old = {**focus, "id": "old_arm", "knowledge_id": "arm", "practice_instructions": "OLD-INSTRUCTION"}
    previous = {**focus, "practice_instructions": "CURRENT-INSTRUCTION"}
    memory = {**empty_memory(), "recommendations": [old, previous], "reports": [
        {"focus_id": "old_arm", "kind": "difficulty", "text": "PRIVATE-OLDER-REPORT"},
        {"focus_id": previous["id"], "kind": "helped", "text": "This cue felt comfortable."},
    ]}
    foreign = synthetic_shot(999, player="Other", session_id=999)
    model = MockOpenAI([{"message": "Use the compatible samples to check repeatability."}])
    offline("Am I improving?", shots + [foreign], memory=memory, client=model)
    packet = model.calls[0]["inputs"][0]["content"][0]["text"]
    assert len(packet) < 16_000
    assert "CURRENT-INSTRUCTION" in packet and "OLD-INSTRUCTION" not in packet and "PRIVATE-OLDER-REPORT" not in packet
    assert foreign.shot_id not in packet and shots[0].shot_id not in json.dumps(json.loads(packet)["evidence"]["history:outcome_counts"])
    context = EvidenceContext("Fixture", "Am I improving?", None, (), [], memory, shots=shots + [foreign])
    assert context.retrieve_memory(topic="arm")["focus"]["practice_instructions"] == "OLD-INSTRUCTION"
    assert context.retrieve_progress(before_session_id=1, after_session_id=999)["status"] == "no_comparable_sessions"


@pytest.mark.parametrize("reverse_second", [False, True])
def test_historical_profile_distinguishes_recurring_and_opposing_associations(reverse_second):
    _, source, _, _ = scenario_input("pattern")
    history = []
    for session_id in range(1, 4):
        for shot in source:
            biomech = shot.analysis["biomechanics"]
            if reverse_second and session_id == 2:
                biomech = {**biomech, "min_knee_angle": 142 if shot.outcome == "made" else 110}
            history.append(replace(shot, session_id=session_id, shot_id=f"s{session_id}_{shot.shot_id}",
                                   analysis={**shot.analysis, "biomechanics": biomech}))
    context = EvidenceContext("Fixture", "How did my form compare with earlier sessions?",
                              history[-1].shot_id, (), [], empty_memory(), shots=history, session_id=3)
    profile = context.retrieve_historical_profile()
    assert profile["sessions_reviewed"] == [1, 2]
    assert profile["recurrence"]["min_knee_angle"]["status"] == ("mixed" if reverse_second else "recurring")
    assert all(data["n_made"] == 6 for data in [row["min_knee_angle"] for row in profile["session_associations"].values()])


def test_temporary_practice_constraints_apply_in_the_turn_without_becoming_profile_memory():
    memory = empty_memory()
    question = "What should I practice? Today I have no hoop."
    shots = sessions((5, 5))
    result = offline(question, shots, memory=memory)
    assert result.practice and result.practice.drill_id in ("steady_setup", "shadow_rehearsal")
    assert player_update(question, memory, None) == {}


def test_progress_is_rendered_inside_the_coaching_reply():
    result = offline("Am I improving?", sessions((3, 8), (5, 5), (8, 3)))
    frontend = AppTest.from_string(
        "from frontend.coaching import render_response\n"
        f"render_response({result.model_dump()!r}, 'Fixture', 'unused', 'review')"
    ).run()
    assert not frontend.exception
    assert any("8 makes / 10 player-confirmed outcomes" == item.value for item in frontend.markdown)
    assert any("Measured phase · estimated release" == item.value for item in frontend.caption)
    assert any("Intervening session reviewed · 2" == item.value for item in frontend.caption)


def first_packet(client):
    return json.loads(client.calls[0]["inputs"][0]["content"][0]["text"])


def knee_plan_memory(shots, reports=()):
    focus = {**fixture_focus(shots[:10]), "session_id": 1, "drill_id": "focused_shooting",
             "recorded_at": "2026-11-20T00:00:00+00:00"}
    return focus, {**empty_memory(), "recommendations": [focus], "reports": list(reports)}


@pytest.mark.parametrize("question", [
    "Did the knee drill you gave me help?",
    "My shot feels smoother now. Have I actually improved?",
    "How does my latest session compare with my earlier ones?",
])
def test_progress_questions_get_the_session_comparison_up_front(question):
    shots = sessions((3, 9), (5, 5), (8, 2))
    _, memory = knee_plan_memory(shots)
    client = MockOpenAI([{"message": "placeholder"}])
    offline(question, shots, memory=memory, client=client, selected=shots[-1].shot_id)
    assert any(key.startswith("progress:") for key in first_packet(client)["evidence"])


def test_previous_advice_is_deduplicated_with_reports_and_left_out_of_miss_investigations():
    shots = sessions((3, 9), (5, 5))
    focus, memory = knee_plan_memory(shots)
    routine = {"title": "Shooting consistency", "cue": "Use the same rhythm.", "knowledge_id": "routine",
               "decision": "start", "evidence_ids": [], "recorded_at": "2026-11-18T00:00:00+00:00"}
    memory["recommendations"] = [{**routine, "id": "r1"}, {**routine, "id": "r2"}, focus]
    memory["reports"] = [{"focus_id": "r1", "kind": "did_not_help", "text": "No change."}]
    client = MockOpenAI([{"message": "placeholder"}])
    offline("What should I practice today?", shots, memory=memory, client=client)
    advice = first_packet(client)["player_context"]["previous_advice"]
    assert advice == [{"title": "Shooting consistency", "cue": "Use the same rhythm.", "given": "2026-11-18",
                       "times_given": 2, "player_report": "did_not_help", "based_on": "general guidance"}]
    client = MockOpenAI([{"message": "placeholder"}])
    offline("Why did I miss this shot?", shots, memory=memory, client=client, selected=shots[-1].shot_id)
    assert "previous_advice" not in first_packet(client)["player_context"]


def replay_live_multisession(number_of_turns):
    from evaluation.live_multisession import PLAYER, TURNS, fixture
    from pathlib import Path
    trace = json.loads((Path(__file__).resolve().parents[1] / "evaluation/live-terra-multisession.json")
                       .read_text(encoding="utf-8"))
    shots, focus, memory = fixture()
    history, results = [], []
    for (question, report), turn in list(zip(TURNS, trace["turns"]))[:number_of_turns]:
        outputs = [[{"type": "function_call", "call_id": f"c{index}", "name": item["name"], "arguments": item["arguments"]}
                    if item["type"] == "function_call" else
                    {"type": "message", "content": [{"type": "output_text", "text": item["text"]}]}
                    for index, item in enumerate(request["output"])] for request in turn["requests"]]
        first = next(index for index, output in enumerate(outputs) if output[-1]["type"] == "message")
        results.append(coach(PLAYER, question, shots=shots, selected=shots[-1].shot_id, history=history,
                             client=MockOpenAI(outputs[:first + 1]), persist=False, memory_state=("", memory)))
        history += [{"role": "user", "content": question}, {"role": "assistant", "content": turn["player_text"]}]
        if report:
            memory = {**memory, "reports": [*memory["reports"], {"focus_id": focus["id"], "kind": report, "text": question}]}
    return results


def test_live_multisession_drafts_with_session_and_goal_numbers_need_no_repair():
    results = replay_live_multisession(4)
    assert [result.provenance["source"] for result in results] == ["openai_authored"] * 4
    assert "7 of 10 free throws" in results[0].message
    assert "110°" in results[1].message
    assert "5 of 10 in the second" in results[3].message


@pytest.mark.parametrize("claim", [
    "You made 6 of 10 in your second session.",
    "You're working toward 9 of 10 free throws.",
])
def test_invented_session_or_goal_numbers_are_still_rejected(claim):
    from evaluation.live_multisession import PLAYER, fixture
    shots, _, memory = fixture()
    result = coach(PLAYER, "Have I actually improved?", shots=shots, selected=shots[-1].shot_id,
                   client=MockOpenAI([{"message": claim}, {"message": claim}]), persist=False,
                   memory_state=("", memory))
    assert result.provenance["source"] == "fallback"


def test_plan_progress_lists_intermediate_sessions_without_changing_endpoints():
    from evaluation.live_multisession import PLAYER, fixture
    shots, _, memory = fixture()
    progress = offline("Have I actually improved?", shots, memory=memory).progress
    assert (progress["before_session_id"], progress["after_session_id"]) == (1, 3)
    assert [(row["session_id"], row["made"], row["shot_count"]) for row in progress["intermediate"]] == [(2, 5, 10)]
    assert (progress["before"]["made"], progress["after"]["made"]) == (3, 8)
