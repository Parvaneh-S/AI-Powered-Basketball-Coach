"""Investigative miss coaching on the saved free_throw_02 analysis, with no provider requests."""

import json
from pathlib import Path

import pytest

from backend.app.agent.coaching_agent import coach, response_text
from backend.app.agent.evidence import RecordedShot, shot_evidence
from backend.app.agent.gemini_provider import GeminiProvider
from backend.app.agent.memory import empty_memory
from evaluation.fixtures import MockOpenAI

ROOT = Path(__file__).resolve().parents[1]
SHOT_ID = "free_throw_02_shot_1"


@pytest.fixture
def side_on_miss():
    analysis = json.loads((ROOT / "outputs/free_throw_02/shot_analysis.json").read_text(encoding="utf-8"))
    return RecordedShot("Investigator", 1, SHOT_ID, "free_throw_02", "missed", "auto", analysis)


def routine_memory():
    """An evidence-free routine suggestion saved earlier, as found in the demo player's memory."""
    memory = empty_memory()
    memory["recommendations"] = [{
        "id": "old", "title": "Shooting consistency", "cue": "Use the same comfortable rhythm each time.",
        "exercise": "One-focus shooting experiment", "knowledge_id": "routine", "field": "shooting_motion_ms",
        "decision": "start", "drill_id": "focused_shooting", "guidance_basis": "general", "evidence_ids": [],
        "conditions": {"shot_type": "free_throw", "shooting_arm": "right"},
    }]
    return memory


def ask(shot, client, question="Why did I miss this shot?", memory=None):
    return coach(shot.player, question, selected=shot.shot_id, shots=[shot], client=client, persist=False,
                 memory_state=("", memory or empty_memory()))


def first_packet(client):
    return json.loads(client.calls[0]["inputs"][0]["content"][0]["text"])


def calls(*items):
    return [{"type": "function_call", "call_id": f"call_{index}", "name": name, "arguments": json.dumps(arguments)}
            for index, (name, arguments) in enumerate(items)]


INVESTIGATION = {
    "message": (
        "Measured: the tracked ball came down through rim height about {{fact:0}} rim widths before the rim "
        "centre, which from this side-on view looks like a short arrival rather than a left or right miss. "
        "Your smallest knee angle was 67.99 degrees, so you loaded deeply; the elbow readings are not reliable here.\n\n"
        "Hypothesis: your release may come before your legs finish extending. One miss cannot confirm that.\n\n"
        "Experiment: take 2 sets of 5 free throws releasing as your legs finish straightening, and note whether "
        "the misses still land short."
    ),
    "evidence_ids": [f"shot:{SHOT_ID}", f"shot:{SHOT_ID}:min_knee_angle"],
    "facts": [{"evidence_id": f"shot:{SHOT_ID}", "field": "ball_flight.path_relative_to_rim.crossing_offset_rim_widths"}],
    "knowledge_ids": ["short_miss"],
}


def test_saved_ball_path_explains_side_on_lateral_label(side_on_miss):
    flight = shot_evidence(side_on_miss)["ball_flight"]
    path = flight["path_relative_to_rim"]
    assert flight["observation"] == "clear_lateral_miss_candidate"
    assert path["camera_view_estimate"] == "side_on_likely"
    assert path["crossing_side_along_travel"] == "before_rim_centre"
    assert path["crossing_offset_rim_widths"] == pytest.approx(1.63, abs=0.01)
    assert "short arrival" in path["interpretation"]
    assert "short or long in a side-on view" in flight["limitations"]


def test_mismatched_artifacts_are_not_attached(side_on_miss):
    analysis = {**side_on_miss.analysis, "shot_outcome": {"prediction": "missed", "observation": "other_run"}}
    shot = RecordedShot("Investigator", 1, SHOT_ID, "free_throw_02", "missed", "auto", analysis)
    assert "path_relative_to_rim" not in shot_evidence(shot)["ball_flight"]


def test_miss_question_leads_with_ball_path_knowledge_not_saved_routine(side_on_miss):
    client = MockOpenAI([{"message": "placeholder"}])
    ask(side_on_miss, client, memory=routine_memory())
    knowledge = list(first_packet(client)["knowledge"])
    assert knowledge[0] == "short_miss"
    assert "distance" in knowledge
    assert knowledge.index("routine") > knowledge.index("short_miss")
    assert "Investigate before advising" in client.calls[0]["instructions"]


def test_parallel_lookups_then_investigative_answer_is_kept(side_on_miss):
    client = MockOpenAI([
        calls(("retrieve_frames", {"shot_id": SHOT_ID, "phases": "knee_dip,release", "focus": "knee"}),
              ("retrieve_make_miss", {"shot_id": SHOT_ID}),
              ("retrieve_knowledge", {"topic": "short_miss"})),
        INVESTIGATION,
    ])
    result = ask(side_on_miss, client)
    assert result.provenance["source"] == "openai_authored"
    assert result.provenance["validation_failures"] == []
    assert len(client.calls) == 2
    outputs = [item for item in client.calls[1]["inputs"] if item.get("type") == "function_call_output"]
    assert [item["call_id"] for item in outputs] == ["call_0", "call_1", "call_2"]
    assert "1.63 rim widths before the rim centre" in result.message
    assert "2 sets of 5 free throws" in result.message


def test_fabricated_number_still_fails_and_fallback_uses_ball_path(side_on_miss):
    invented = {**INVESTIGATION, "message": INVESTIGATION["message"].replace("{{fact:0}}", "3"), "facts": []}
    client = MockOpenAI([invented, invented])
    result = ask(side_on_miss, client, memory=routine_memory())
    assert result.provenance["source"] == "fallback"
    text = response_text(result)
    assert "short arrival" in text
    assert "occlusion" not in text.casefold()


def test_repair_keeps_reasoning_and_fixes_only_listed_problem(side_on_miss):
    unsupported = {**INVESTIGATION, "message": "You missed because your elbow flared.\n\n" + INVESTIGATION["message"]}
    client = MockOpenAI([unsupported, INVESTIGATION])
    result = ask(side_on_miss, client)
    assert result.provenance["source"] == "openai_repaired"
    repair = json.loads(client.calls[1]["inputs"][-1]["content"][0]["text"])
    assert repair["instruction"].startswith("Fix only the listed problems")


def test_gemini_groups_responses_to_one_turn_of_calls():
    contents = GeminiProvider.contents([
        {"role": "user", "content": [{"type": "input_text", "text": "question"}]},
        {"type": "gemini_content", "content": {"role": "model", "parts": [
            {"functionCall": {"name": "retrieve_shot", "args": {}}},
            {"functionCall": {"name": "retrieve_frames", "args": {}}}]}},
        {"type": "function_call_output", "call_id": "a", "name": "retrieve_shot", "output": "{}"},
        {"type": "function_call_output", "call_id": "b", "name": "retrieve_frames", "output": "{}"},
    ])
    assert len(contents) == 3
    assert [part["functionResponse"]["name"] for part in contents[2]["parts"]] == ["retrieve_shot", "retrieve_frames"]


def angled_shot(start_x):
    analysis = {"shot_events": {"release_frame": 0}, "shot_outcome": {"observation": "clear_lateral_miss_candidate"}}
    shot = RecordedShot("Investigator", 1, "angled_shot_1", "angled", "missed", "auto", analysis)
    outcome = {"observation": "clear_lateral_miss_candidate", "rim_center": [200.0, 100.0], "rim_width_px": 50.0,
               "selected_crossing": {"crossing_x": 270.0}}
    points = [(0, start_x, 300.0), (10, 230.0, 60.0), (20, 270.0, 110.0)]
    return shot, outcome, points


@pytest.mark.parametrize("start_x", [325.0, 350.0])  # 2.5 and 3 rim widths: an angled view
def test_ambiguous_camera_angle_gives_no_direction(start_x):
    from backend.app.agent.evidence import flight_geometry
    geometry = flight_geometry(*angled_shot(start_x))
    assert geometry["camera_view_estimate"] == "unclear"
    assert "direction unclear" in geometry["interpretation"]
    assert not any(word in geometry["interpretation"] for word in ("short arrival", "long arrival", "left or right"))


def test_moving_camera_gives_no_direction_or_apex(tmp_path, monkeypatch):
    from backend.app.agent import evidence
    (tmp_path / "outputs" / "angled").mkdir(parents=True)
    (tmp_path / "outputs" / "angled" / "hoop_track.csv").write_text("frame,x1,y1,x2,y2\n", encoding="utf-8")
    monkeypatch.setattr(evidence, "ROOT", tmp_path)
    geometry = evidence.flight_geometry(*angled_shot(700.0))
    assert geometry["camera_view_estimate"] == "unclear" and "apex_above_rim_rim_widths" not in geometry


def test_unclear_view_selects_no_miss_direction_topic(side_on_miss, monkeypatch):
    from backend.app.agent import evidence
    monkeypatch.setattr(evidence, "SIDE_ON_MIN_RIM_WIDTHS", 50)
    client = MockOpenAI([{"message": "placeholder"}])
    ask(side_on_miss, client)
    knowledge = first_packet(client)["knowledge"]
    assert not {"short_miss", "long_miss", "lateral_miss"} & set(knowledge)


def test_unsupported_saved_suggestion_leaves_investigation_but_memory_stays(side_on_miss):
    memory = routine_memory() | {"goal": "Make 7 of 10 free throws", "experience": "intermediate"}
    client = MockOpenAI([{"message": "placeholder"}])
    ask(side_on_miss, client, memory=memory)
    context = first_packet(client)["player_context"]
    assert context["focus"] is None
    assert context["goal"] == "Make 7 of 10 free throws" and context["experience"] == "intermediate"


def test_supported_or_reported_suggestion_is_still_used(side_on_miss):
    supported = routine_memory()
    supported["recommendations"][0]["evidence_ids"] = [f"shot:{SHOT_ID}:min_knee_angle"]
    reported = routine_memory()
    reported["reports"] = [{"focus_id": "old", "kind": "did_not_help", "text": "It did not help.",
                            "recorded_at": "2026-11-20T00:00:00+00:00"}]
    for memory in (supported, reported):
        client = MockOpenAI([{"message": "placeholder"}])
        ask(side_on_miss, client, memory=memory)
        assert first_packet(client)["player_context"]["focus"]["id"] == "old"


def test_practice_question_follows_the_miss_not_an_unsupported_plan(side_on_miss):
    client = MockOpenAI([{"message": "placeholder"}])
    ask(side_on_miss, client, question="What should I practice, and can you recommend an instructional video?",
        memory=routine_memory())
    packet = first_packet(client)
    assert packet["player_context"]["focus"] is None
    assert list(packet["knowledge"])[0] == "short_miss"


def test_asking_about_the_saved_plan_still_sees_it(side_on_miss):
    client = MockOpenAI([{"message": "placeholder"}])
    ask(side_on_miss, client, question="Can you make my current drill harder?", memory=routine_memory())
    assert first_packet(client)["player_context"]["focus"]["id"] == "old"


def live_outputs(turn):
    """Model outputs captured in the live gpt-6.1-terra conversation, in request order."""
    outputs = []
    for request in turn["requests"]:
        outputs.append([
            {"type": "function_call", "call_id": f"c{index}", "name": item["name"], "arguments": item["arguments"]}
            if item["type"] == "function_call" else
            {"type": "message", "content": [{"type": "output_text", "text": item["text"]}]}
            for index, item in enumerate(request["output"])
        ])
    return outputs


def test_live_terra_drafts_are_kept_without_repair_or_discards(side_on_miss):
    trace = json.loads((ROOT / "evaluation/live-terra-investigative.json").read_text(encoding="utf-8"))
    history = []
    for number, turn in enumerate(trace["turns"], 1):
        # Only the first draft of each turn is replayed: it must now pass on its own.
        outputs = live_outputs(turn)
        first_answer = next(index for index, output in enumerate(outputs) if output[-1]["type"] == "message")
        client = MockOpenAI(outputs[:first_answer + 1])
        result = coach(side_on_miss.player, turn["question"], selected=SHOT_ID, shots=[side_on_miss],
                       history=history, client=client, persist=False, memory_state=("", empty_memory()))
        assert result.provenance["source"] == "openai_authored", number
        assert result.provenance["discarded_components"] == [], number
        if number in (1, 2):
            assert len(result.video_references) == 4  # knee and elbow overlays of frame 25 are both kept
        if number == 3:
            assert result.practice and result.practice.dose.sets == 2
            assert result.instructional_resource.id == "jrnba_two_hand_form"
        history += [{"role": "user", "content": turn["question"]},
                    {"role": "assistant", "content": response_text(result)}]


@pytest.mark.parametrize("sentence", [
    "Your elbow caused the miss.",
    "This drill will fix your shot.",
    "You missed because your legs were weak.",
])
def test_unhedged_causal_claims_are_still_rejected(sentence):
    from backend.app.agent.coaching_narrative import validate_text
    ctx = type("Ctx", (), {"feedback": None, "review_requested": False, "progress_records": {},
                           "practice_context": {}, "question": "Why did I miss?"})()
    issues, _ = validate_text(sentence, "message", ctx)
    assert issues


def test_counted_claims_are_still_verified(side_on_miss):
    bad = {"message": "You made one shot in your last session and your knee angle was 40 degrees."}
    client = MockOpenAI([bad, bad])
    assert ask(side_on_miss, client).provenance["source"] == "fallback"


def test_spaced_catalog_id_resolves_to_entry():
    from backend.app.agent.knowledge import search_knowledge
    assert search_knowledge("short miss", limit=2, default_to_routine=False) == ["short_miss"]


def test_final_live_drafts_need_no_repair(side_on_miss):
    """The two first drafts repaired in the final live run were scoped or negated, not unsupported."""
    trace = json.loads((ROOT / "evaluation/live-terra-final.json").read_text(encoding="utf-8"))
    history = []
    for number, turn in enumerate(trace["turns"], 1):
        outputs = live_outputs(turn)
        first_answer = next(index for index, output in enumerate(outputs) if output[-1]["type"] == "message")
        client = MockOpenAI(outputs[:first_answer + 1])
        result = coach(side_on_miss.player, turn["question"], selected=SHOT_ID, shots=[side_on_miss],
                       history=history, client=client, persist=False, memory_state=("", empty_memory()))
        assert result.provenance["source"] == "openai_authored", number
        history += [{"role": "user", "content": turn["question"]},
                    {"role": "assistant", "content": response_text(result)}]


def test_scope_and_negation_exemptions_stay_narrow():
    from backend.app.agent.coaching_narrative import validate_text
    ctx = type("Ctx", (), {"feedback": None, "review_requested": False, "progress_records": {},
                           "practice_context": {}, "question": "Why did I miss?"})()
    assert not validate_text("That compares the two without assuming either is the cause.", "message", ctx)[0]
    assert validate_text("Rushing the lift caused the miss, without question.", "message", ctx)[0]
    assert "1" not in validate_text("This is not proof of a habit from one attempt.", "message", ctx)[1]
    assert "1" in validate_text("You made one shot from the line.", "message", ctx)[1]


def resource_answer(note):
    return {"message": "Your shot looks a little short. Watch how the legs and arm finish together.",
            "instructional_resource_id": "jrnba_two_hand_form", "resource_note": note}


def ask_for_video(shot, answer):
    client = MockOpenAI([calls(("retrieve_knowledge", {"topic": "knees", "resource_kind": "video"})), answer])
    return ask(shot, client, question="Can you recommend an instructional video for my shot?")


def test_resource_note_replaces_generic_card_text(side_on_miss):
    note = "Your short miss came with a good knee bend, so watch how the legs and arm finish together."
    result = ask_for_video(side_on_miss, resource_answer(note))
    assert result.provenance["source"] == "openai_authored"
    assert result.instructional_resource.relevance == note


@pytest.mark.parametrize("note", ["Your knee bent 12 degrees too little.", "See https://example.com for more."])
def test_unsupported_resource_note_is_dropped_not_the_answer(side_on_miss, note):
    result = ask_for_video(side_on_miss, resource_answer(note))
    assert result.provenance["source"] == "openai_authored"
    assert result.instructional_resource.relevance != note
    assert any(item["field"] == "resource_note" for item in result.provenance["discarded_components"])


def test_live_practice_rerun_draft_keeps_its_practice_card(side_on_miss):
    """The rerun draft said '2 sets of 10' and sent duration_seconds 0; both are now accepted."""
    saved = json.loads((ROOT / "evaluation/live-terra-communication.json").read_text(encoding="utf-8"))
    rerun = json.loads((ROOT / "evaluation/live-terra-practice-rerun.json").read_text(encoding="utf-8"))
    history = []
    for turn in saved["turns"][:2]:
        history += [{"role": "user", "content": turn["question"]},
                    {"role": "assistant", "content": turn["player_text"]}]
    outputs = live_outputs(rerun)[:2]  # lookups, then the first draft only
    client = MockOpenAI(outputs)
    result = coach(side_on_miss.player, rerun["question"], selected=SHOT_ID, shots=[side_on_miss], history=history,
                   client=client, persist=False, memory_state=("", empty_memory()))
    assert result.provenance["source"] == "openai_authored"
    assert result.practice and result.practice.dose.model_dump() == {"sets": 2, "repetitions": 10,
                                                                      "duration_seconds": 300}
    assert result.instructional_resource.relevance.startswith("Watch how the shooting arm extends")


def test_sets_of_without_unit_still_respects_dose_limits():
    from backend.app.agent.coaching_narrative import validate_text
    ctx = type("Ctx", (), {"feedback": None, "review_requested": False, "progress_records": {},
                           "practice_context": {}, "question": "What should I practice?"})()
    assert validate_text("Shoot 2 sets of 10.", "message", ctx)[0] == []
    assert validate_text("Shoot 3 sets of 20.", "message", ctx)[0]  # 60 shots exceeds the small-dose limit


def test_explicit_question_about_saved_plan_sees_it(side_on_miss):
    client = MockOpenAI([{"message": "placeholder"}])
    ask(side_on_miss, client, question="Did my last practice plan help?", memory=routine_memory())
    assert first_packet(client)["player_context"]["focus"]["id"] == "old"


def test_live_interactive_practice_draft_keeps_numbers_and_card(side_on_miss):
    """'Then shoot 5 from the free-throw line' is a dose, so the first draft and its practice card survive."""
    trace = json.loads((ROOT / "evaluation/live-terra-interactive.json").read_text(encoding="utf-8"))
    history = []
    for turn in trace["turns"][:3]:
        history += [{"role": "user", "content": turn["question"]},
                    {"role": "assistant", "content": turn["player_text"]}]
    turn = trace["turns"][3]
    client = MockOpenAI(live_outputs(turn)[:2])
    result = coach(side_on_miss.player, turn["question"], selected=SHOT_ID, shots=[side_on_miss], history=history,
                   client=client, persist=False, memory_state=("", empty_memory()))
    assert result.provenance["source"] == "openai_authored", result.provenance
    assert "shoot 5 from the free-throw line" in result.message
    assert result.practice is not None, result.provenance["discarded_components"]


def two_video_answer(extra):
    return {"message": "Your shot felt rushed, so connect your rise with your release. Two useful videos are below.",
            "instructional_resource_id": "jrnba_two_hand_form",
            "resource_note": "Watch how the knees and shooting arm extend together.",
            "more_resources": extra}


def video_offers(shot, answer):
    client = MockOpenAI([calls(("retrieve_knowledge", {"topic": "free throw routine", "resource_kind": "video"}),
                               ("retrieve_knowledge", {"topic": "knees", "resource_kind": "video"})), answer])
    return ask(shot, client, question="How can I improve my shooting rhythm? Any videos?")


def test_video_card_is_a_learning_resource_without_catalog_exercise(side_on_miss):
    result = video_offers(side_on_miss, two_video_answer([]))
    card = result.instructional_resource
    assert card.id == "jrnba_two_hand_form" and card.creator == "Dale Ellis"
    assert card.relevance == "Watch how the knees and shooting arm extend together."
    assert card.exercise is None
    assert card.thumbnail_url is None and card.embed_url is None  # nothing unverified is invented


def test_more_than_one_offered_video_with_its_own_note(side_on_miss):
    extra = [{"id": "jrnba_free_throw", "note": "See how a steady pre-shot rhythm keeps the release unhurried."}]
    result = video_offers(side_on_miss, two_video_answer(extra))
    assert result.provenance["source"] == "openai_authored"
    assert [card.id for card in result.additional_resources] == ["jrnba_free_throw"]
    assert result.additional_resources[0].relevance.startswith("See how a steady")
    assert "jr.nba.com/video/fundamentals-of-the-free-throw/" in response_text(result)


def test_unoffered_or_repeated_extra_video_is_dropped(side_on_miss):
    extra = [{"id": "made_up_video", "note": "Invented."}, {"id": "jrnba_two_hand_form", "note": "Repeat."}]
    result = video_offers(side_on_miss, two_video_answer(extra))
    assert result.additional_resources == []
    assert any(item["field"] == "more_resources" for item in result.provenance["discarded_components"])
