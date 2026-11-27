"""OpenAI-first authored responses, evidence, safety and conservative fallback."""

import json
import re
from contextlib import nullcontext
from dataclasses import replace
from uuid import uuid4

import pytest

from backend.app.agent.coaching_agent import coach, response_text
from backend.app.agent.context import EvidenceContext
from backend.app.agent.memory import active_focus, empty_memory, read_memory
from evaluation.coaching_generic import QUESTION, draft_for, patterns
from evaluation.fixtures import MockOpenAI, fixture_focus, playground_scenario, synthetic_shot

@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "")


def ask(question, replies=(), *, shots=None, case=None, history=(), memory=None, persist=False, multimodal=False):
    player = case["player"] if case else "Fixture"
    shots = case["shots"] if case else patterns(True) if shots is None else shots
    memory = memory if memory is not None else case["memory"] if case else empty_memory()
    client = MockOpenAI(replies) if replies else None
    result = coach(player, question, shots=shots, selected=shots[0].shot_id if shots else None,
                   session_id=shots[0].session_id if case else None, history=history, client=client,
                   memory_state=("", memory), persist=persist, multimodal=multimodal)
    return result, client


@pytest.fixture
def fallback_run():
    return lambda shots: ask(QUESTION, shots=shots)[0]


def input_packet(client):
    return json.loads(client.calls[0]["inputs"][0]["content"][0]["text"])


def repair_details(client, call=-1):
    return json.loads(client.calls[call]["inputs"][-1]["content"][0]["text"])["validation_details"]


def proposal(drill="focused_shooting", topic="arm", **overrides):
    return {"drill_id": drill, "topic": topic, "instructions": "Rehearse one comfortable movement and reset.",
            **overrides}


def test_same_fixture_labels_general_practice_and_coach_owns_evaluation(fallback_run):
    outcome = fallback_run([synthetic_shot()])
    assert outcome.guidance_basis == "general"
    assert "General practice option" in outcome.guidance_note
    assert outcome.practice and re.search(r"\bI(?:['’]ll| will) review\b", outcome.practice.evaluation)
    assert not outcome.observations


def test_fallback_adapts_to_different_personal_patterns(fallback_run):
    higher, lower = (fallback_run(patterns(direction)) for direction in (True, False))
    assert higher.guidance_basis == lower.guidance_basis == "personal_pattern"
    assert "straighter" in higher.cue and "softer bend" in lower.cue
    assert "recorded makes" in higher.observations[0].text
    assert "makes and misses separately" in higher.practice.evaluation



@pytest.mark.parametrize(("question", "message"), [
    ("How did I shoot overall?", "The outcomes and form samples answer different questions."),
    ("What should I keep doing?", "Keep the comfortable parts of your routine that you can repeat."),
    ("Why did I miss?", "The recorded patterns give us a place to investigate. They cannot establish a cause."),
    ("Should I change anything?", "I'd leave your comfortable setup alone for now."),
    ("What does this mean?", "There is one thing I'd keep.\n\nUse the same comfortable setup."),
    ("Can you compare the sets?", "We'll need comparable records before drawing a conclusion."),
    ("What should I practice?", "Let's first check what space and equipment you have."),
])
def test_natural_answers_can_omit_sections_and_exercises(question, message):
    result, client = ask(question, [{"message": message}])
    assert result.message == message
    assert result.provenance["source"] == "openai_authored"
    assert result.practice is None and not result.strengths and not result.observations
    assert len(client.calls) == 1


def test_choose_a_different_qualified_priority_and_drill():
    case = playground_scenario("multiple_priorities")
    question = "What is one change worth trying in this session?"
    ctx = EvidenceContext(case["player"], question, case["shots"][0].shot_id, (), [], case["memory"],
                          shots=case["shots"], session_id=1)
    ctx.collect(False)
    server_topic = ctx.priority()[0]
    key = next(key for key, topic in ctx.observation_topics.items()
               if key.startswith("pattern:") and topic != server_topic and topic in ("arm", "knees", "timing", "finish"))
    topic = ctx.observation_topics[key]
    answer = {"message": "I would test one comfortable change. The pattern is an association.",
              "evidence_ids": [key], "knowledge_ids": [topic], "practice": proposal("shadow_rehearsal", topic)}
    result, client = ask(question, [answer], case=case)
    assert result.provenance["selected_topic"] == topic != server_topic
    assert result.practice.drill_id == "shadow_rehearsal"
    packet = input_packet(client)
    assert key in packet["evidence"]
    assert "selected_drill" not in packet and "coaching_priority" not in packet
    assert "focused_shooting" in packet["eligible_practice"]


@pytest.mark.parametrize(("tool", "arguments", "field"), [
    ("retrieve_attempts", {"outcome": "missed", "offset": 1}, "attempts"),
    ("retrieve_historical_profile", {}, "status"),
    ("retrieve_history", {"outcome": "made"}, "recent"),
    ("retrieve_progress", {}, "status"),
    ("retrieve_memory", {}, "reports"),
    ("retrieve_session", {}, "accuracy_pct"),
])
def test_tool_output_reaches_author(tool, arguments, field):
    case = playground_scenario("multiple_priorities")
    key = f"tool:1:{tool}"
    call = [{"type": "function_call", "name": tool, "call_id": "lookup", "arguments": json.dumps(arguments)}]
    answer = {"message": "Here is what the available record supports.", "evidence_ids": [key]}
    result, client = ask("What can you tell me?", [call, answer], case=case)
    tool_output = next(item for item in client.calls[1]["inputs"] if item.get("type") == "function_call_output")
    payload = json.loads(tool_output["output"])
    assert tool_output["call_id"] == "lookup"
    assert payload["id"] == key and field in payload["result"]
    assert result.authored_evidence["citations"] == [key]
    assert result.provenance["source"] == "openai_authored"


def test_tool_numbers_are_locally_resolved():
    case = playground_scenario("consistent_high")
    key = "tool:1:retrieve_session"
    call = [{"type": "function_call", "name": "retrieve_session", "call_id": "stats", "arguments": "{}"}]
    answer = {"message": "You recorded {{fact:0}} makes this session.", "evidence_ids": [key],
              "facts": [{"evidence_id": key, "field": "made"}]}
    result, _ = ask("How many shots did I make?", [call, answer], case=case)
    assert result.message == "You recorded 16 makes this session."
    assert result.authored_evidence["numeric_facts"][0]["value"] == 16


def test_repair_still_sees_the_tool_result():
    case = playground_scenario("consistent_high")
    key = "tool:1:retrieve_session"
    call = [{"type": "function_call", "name": "retrieve_session", "call_id": "stats", "arguments": "{}"}]
    bad = {"message": "You recorded 99 makes this session.", "evidence_ids": [key]}
    corrected = {"message": "You recorded {{fact:0}} makes this session.", "evidence_ids": [key],
                 "facts": [{"evidence_id": key, "field": "made"}]}
    result, client = ask("How many shots did I make?", [call, bad, corrected], case=case)
    assert result.message == "You recorded 16 makes this session."
    assert client.calls[2]["tools"] == []
    assert any(item.get("call_id") == "stats" and item.get("type") == "function_call_output"
               for item in client.calls[2]["inputs"])


@pytest.mark.parametrize(("experience", "drill", "workload"), [
    ("beginner", "close_delivery", (1, 5)), ("advanced", "focused_shooting", (2, 8)),
])
def test_fallback_dose_still_respects_experience(experience, drill, workload):
    result, _ = ask(QUESTION, memory={**empty_memory(), "experience": experience})
    assert result.practice.drill_id == drill
    assert (result.practice.dose.sets, result.practice.dose.repetitions) == workload


@pytest.mark.parametrize("question", [
    "What am I doing well?", "Why should I change my elbow delivery?",
    "How many degrees was my release elbow angle?", "My shoulder hurts.",
])
def test_fallback_avoids_unsolicited_or_unsafe_drills(question):
    result, _ = ask(question)
    assert result.practice is None


def test_saved_style_is_delivered_with_the_player_goal():
    memory = {**empty_memory(), "goal": "Make free throws more consistently.",
              "experience": "beginner", "preferences": {"explanation_style": "simple"}}
    _, client = ask("What should I work on?", [{"message": "Start with a comfortable setup."}], memory=memory)
    profile = input_packet(client)["player_context"]
    assert profile["goal"] == memory["goal"] and profile["experience"] == "beginner"
    assert profile["preferences"]["explanation_style"] == "simple"


def test_shot_packet_distinguishes_reliability_events_and_flight():
    shot = synthetic_shot(quality="review")
    shot = replace(shot, analysis={**shot.analysis,
        "ball_tracking": {"tracked_frames": 8, "first_tracked_frame": 5, "last_tracked_frame": 12,
                          "tracking_coverage_pct": 100},
        "shot_outcome": {"observation": "clear_lateral_miss_candidate", "method": "2d_detector",
                         "selected_crossing": {"x": 12.5}}})
    answer = {"message": "Pose is limited, so I would avoid diagnosing your mechanics from this clip."}
    result, client = ask("Can you assess my form?", [answer], shots=[shot])
    packet = input_packet(client)
    evidence = packet["evidence"][f"shot:{shot.shot_id}"]
    assert evidence["measurements"]["shooting_motion_ms"]["value"] is None
    assert evidence["ball_flight"]["status"] == "available_2d"
    assert evidence["ball_flight"]["rim_crossing_estimate"]["x"] == 12.5
    assert evidence["outcome_source"] in ("experimental detector", "player label")
    assert "release_frame" in evidence["events"]
    assert result.provenance["source"] == "openai_authored"


def test_follow_up_retains_recommendation_history_and_feedback():
    case = playground_scenario("unsuccessful")
    history = [{"role": "assistant", "content": "Try a comfortable knee bend before lifting the ball."},
               {"role": "user", "content": "I tried it at practice."}]
    answer = {"message": "Set that knee cue aside. What changed when you tried it?", "adaptation": "discontinue"}
    result, client = ask("Your earlier exercise did not help.", [answer], case=case, history=history)
    packet = input_packet(client)
    assert packet["conversation"] == history
    assert packet["player_context"]["focus"]["id"] == case["memory"]["recommendations"][-1]["id"]
    assert any(report["kind"] == "did_not_help" for report in packet["player_context"]["reports"])
    assert result.previous_focus["id"] == packet["player_context"]["focus"]["id"]
    assert result.practice is None


@pytest.mark.parametrize(("bad", "field"), [
    ({"message": "You made 19 of 20 shots."}, "message"),
    ({"message": "Your elbow was 173 degrees."}, "message"),
    ({"message": "The result was {{fact:8}}."}, "message"),
    ({"message": "Your elbow caused your misses."}, "message"),
    ({"message": "You missed likely because of your knee bend."}, "message"),
    ({"message": "Push through the pain."}, "message"),
    ({"message": "Watch this frame.", "frame_ids": ["frame:other:release:8"]}, "frame_ids"),
    ({"message": "The value is {{fact:0}}.", "evidence_ids": ["shot:fixture_shot_1:release_elbow_angle"],
      "facts": [{"evidence_id": "shot:fixture_shot_1:release_elbow_angle", "field": "power"}]}, "message"),
])
def test_local_failures_get_targeted_repair(bad, field):
    corrected = {"message": "The evidence does not establish a specific personal cause."}
    result, client = ask("Why did I miss?", [bad, corrected])
    assert result.message == corrected["message"] and result.provenance["source"] == "openai_repaired"
    assert any(item["field"] == field and item["reason"] for item in repair_details(client))
    assert client.calls[1]["tools"] == []
    assert json.loads(client.calls[1]["inputs"][-2]["content"][0]["text"]) == bad


@pytest.mark.parametrize(("field", "value"), [
    ("evidence_ids", ["pattern:made_up:aaaaaaaa"]),
    ("evidence_ids", ["shot:fixture_shot_1:release_elbow_angl"]),
    ("knowledge_ids", ["external_unverified"]),
    ("frame_ids", ["frame:other:release:8"]),
    ("adaptation", "continue"),
    ("practice", {"drill_id": "malformed"}),
    ("facts", [{"evidence_id": "shot:fixture_shot_1:release_elbow_angle", "field": "value"}]),
])
def test_optional_mistakes_do_not_discard_safe_prose(field, value):
    message = "The evidence does not establish a specific personal cause."
    result, client = ask("Why did I miss?", [{"message": message, field: value}])
    assert result.provenance["source"] == "openai_authored"
    assert result.provenance["validation_failures"] == []
    assert [item["field"] for item in result.provenance["discarded_components"]] == [field]
    assert result.message == message and result.practice is None and not result.video_references
    assert result.memory_update is None
    assert len(client.calls) == 1


def test_repairs_report_multiple_independent_errors():
    bad = {"message": "Push through the pain. Your release elbow angle was 173 degrees. You missed because your arm was bent.",
           "adaptation": "continue"}
    good = {"message": "Stop if the movement causes pain. These measurements cannot explain the misses."}
    result, client = ask("Why did I miss?", [bad, good])
    details = repair_details(client)
    assert len(details) == 3 and all(item["kind"] == "substantive" for item in details)
    assert any("173" in issue["reason"] and issue["allowed_values"] for issue in details)
    assert result.provenance["source"] == "openai_repaired"


@pytest.mark.parametrize("message", [
    "In this session you took 20 shots and made 4 of them, for 20% shooting accuracy.",
    "You made 4 of 20.",
    "You made 4/20.",
    "Your accuracy was 20% in this session.",
    "Your recorded shots show 20% made and 80% missed.",
])
def test_verified_session_numbers_are_preserved_as_written(message):
    result, client = ask("How accurate was I this session?", [{"message": message}],
                         case=playground_scenario("consistent_low"))
    assert result.message == message and result.provenance["source"] == "openai_authored"
    assert input_packet(client)["evidence"]["session:1"]["made"] == 4
    assert result.authored_evidence["numeric_facts"] == []


@pytest.mark.parametrize("message", [
    "You made 16 of 20 attempts in this session.",
    "You made 4 of 19 attempts in this session.",
    "Your accuracy was 20% in the last session.",
    "You made 4 of 20 from the corner.",
    "You improved your accuracy by 20%.",
    "Your teammate made 4 of 20.",
])
def test_incorrect_or_unscoped_session_numbers_need_repair(message):
    good = {"message": "You made 4 of 20 in this session."}
    result, client = ask("How accurate was I this session?", [{"message": message}, good],
                         case=playground_scenario("consistent_low"))
    assert result.provenance["source"] == "openai_repaired"
    assert any("cannot be verified" in issue["reason"] for issue in repair_details(client))
    assert result.message == good["message"]


def test_unknown_outcomes_require_an_explicit_numeric_denominator():
    case = playground_scenario("consistent_low")
    case["shots"][-1] = replace(case["shots"][-1], outcome="unknown")
    bad = {"message": "Your accuracy was 21.1%."}
    good = {"message": "You made 4 out of 19 known outcomes. Your accuracy among known outcomes was 21.1%."}
    result, client = ask("How accurate was I this session?", [bad, good], case=case)
    assert result.provenance["source"] == "openai_repaired"
    assert result.message == good["message"] and repair_details(client)


@pytest.mark.parametrize("bad", ["Your release elbow angle was 120 ms.",
                                "Your release elbow angle was 120 degrees on your misses."])
def test_direct_measurements_require_known_field_unit_and_scope(bad):
    good = {"message": "Your estimated-release elbow angle was 120 degrees."}
    result, client = ask("What was my release elbow angle?", [{"message": bad}, good],
                         shots=[synthetic_shot()])
    assert result.provenance["source"] == "openai_repaired" and result.message == good["message"]
    assert result.authored_evidence["observations"]["shot:fixture_shot_1:release_elbow_angle"]["technical"]["value"] == 120


def test_inline_pattern_average_verifies_which_outcome_group_it_describes():
    case = playground_scenario("multiple_priorities")
    bad = {"message": "Your time from detected start to estimated release averaged 920 ms on makes."}
    good = {"message": "Your time from detected start to estimated release averaged 800 ms on makes."}
    result, client = ask("How did my timing vary?", [bad, good], case=case)
    assert result.provenance["source"] == "openai_repaired" and result.message == good["message"]
    failure, = repair_details(client)
    assert list(failure["allowed_values"].values()) == [800.0]
    assert failure["evidence_ids"][0].startswith("pattern:shooting_motion_ms:")


@pytest.mark.parametrize("text", [
    "For the next set, try 5 easy shots from a comfortable distance.",
    "Try two sets of five repetitions without releasing the ball.",
])
def test_natural_practice_dose_needs_no_practice_card(text):
    result, client = ask(QUESTION, [{"message": text}])
    assert result.message == text and result.practice is None
    assert len(client.calls) == 1 and result.provenance["source"] == "openai_authored"


def test_discarded_objective_action_cannot_be_saved_as_an_implicit_plan():
    player = uuid4().hex
    shots = [replace(shot, player=player) for shot in patterns(True)]
    answer = {"message": "Here is one exercise you could try if useful.",
              "practice": proposal(), "adaptation": "continue"}
    result = coach(player, QUESTION, shots=shots, selected=shots[0].shot_id, multimodal=False,
                   client=MockOpenAI([answer]))
    assert result.message == answer["message"] and result.practice
    assert result.memory_update is None and active_focus(read_memory(player)[1]) is None


def test_captured_phase_three_drafts_pass_revised_local_checks():
    from evaluation.run import ROOT, replay_phase_three_drafts

    results = replay_phase_three_drafts(ROOT / "evaluation/live-openai-coaching-baseline.json")
    assert len(results) == 10
    assert all(item["message_preserved"] for item in results)
    assert all(not item["local_errors"] for item in results)
    assert all(item["message_preserved"] for item in results)


@pytest.mark.parametrize("claim", [
    "You made nineteen out of twenty.",
    "Your wrist collapsed on every miss.",
    "Practice this to rehabilitate your shoulder.",
    "Take 100 shots without stopping.",
])
def test_local_safeguards_repair_unsupported_claims_without_a_reviewer(claim):
    good = {"message": "Keep the movement comfortable and use the evidence available."}
    result, client = ask("How can I improve my shot?", [{"message": claim}, good])
    assert result.message == good["message"]
    assert result.provenance["validation_failures"] == ["narrative_validation_failed"]
    assert len(client.calls) == 2 and repair_details(client)


@pytest.mark.parametrize(("constraint", "plan"), [
    ("I have no hoop.", proposal()),
    ("I don't have a ball.", proposal()),
    ("I only have a ball.", proposal()),
    ("I have no equipment.", proposal()),
    ("I cannot jump.", proposal()),
    ("I only have 30 seconds.", proposal(dose={"sets": 1, "repetitions": 3, "duration_seconds": 45})),
    ("Make it easier.", proposal(dose={"sets": 2, "repetitions": 8, "duration_seconds": 240})),
    ("No drills.", proposal()),
    ("", proposal("landing_balance", "arm")),
    ("", proposal("shadow_rehearsal", instructions="Shoot from one spot.")),
    ("", proposal(instructions="Take 2 sets of 5 shots.", dose={"sets": 1, "repetitions": 5, "duration_seconds": 75})),
    ("", proposal(instructions="Your elbow was 173 degrees, so take 5 shots.")),
    ("", proposal(instructions="You made 5 shots from one spot.")),
    ("", proposal(instructions="Do 100 repetitions before progressing.")),
])
def test_discard_infeasible_practice_and_keep_valid_coaching(constraint, plan):
    body = "We can wait to choose an exercise until the constraints are clear."
    result, client = ask(f"{QUESTION} {constraint}", [{"message": body, "practice": plan}])
    assert result.provenance["source"] == "openai_authored"
    assert result.message == body and result.practice is None and result.memory_update is None
    assert result.provenance["discarded_components"][0]["field"] == "practice"
    assert len(client.calls) == 1


def test_valid_dose_and_openai_practice_render_in_existing_frontend(monkeypatch):
    from frontend import coaching as frontend_coaching

    answer = draft_for(patterns(True))
    answer["practice"].update(instructions="Take 2 sets of 5 shots.",
                              dose={"sets": 2, "repetitions": 5, "duration_seconds": 150})
    result, _ = ask(QUESTION, [answer])
    rendered = []
    class UI:
        write = staticmethod(rendered.append)
        caption = staticmethod(rendered.append)
        markdown = staticmethod(rendered.append)
        container = expander = staticmethod(lambda *args, **kwargs: nullcontext())
    monkeypatch.setattr(frontend_coaching, "st", UI())
    frontend_coaching.render_response(result.model_dump(mode="json"), "Fixture", "unused", "test")
    assert rendered.count(answer["message"]) == 1
    assert rendered.count("Take 2 sets of 5 shots.") == 1
    assert any("Prescribed practice target:" in text for text in rendered)
    assert result.practice.source_info["professionally_validated"] is False


def test_authored_practice_persists_with_evidence():
    player = uuid4().hex
    shots = [replace(shot, player=player) for shot in patterns(True)]
    ctx = EvidenceContext(player, QUESTION, shots[0].shot_id, (), [], empty_memory(), shots=shots)
    ctx.collect(False)
    key = next(key for key in ctx.observations if key.startswith("pattern:release_elbow_angle:"))
    supporting_context = [item for item in ctx.observations if item.startswith("shot:")][:3]
    citations = supporting_context + [key]
    answer = {"message": "Test this comfortably. The association is not a cause.",
              "evidence_ids": citations, "practice": proposal("shadow_rehearsal")}
    result = coach(player, QUESTION, shots=shots, selected=shots[0].shot_id, multimodal=False,
                   client=MockOpenAI([answer]))
    saved = active_focus(read_memory(player)[1])
    assert saved["id"] == result.memory_update["id"]
    assert saved["evidence_ids"] == citations and saved["drill_id"] == "shadow_rehearsal"
    assert saved["verified_personal_correction"] is False
    assert saved["guidance_basis"] == "personal_pattern"


def test_failed_drill_is_not_offered_again():
    shots = patterns(True)
    focus = {**fixture_focus(shots), "id": "prior_arm", "knowledge_id": "arm", "drill_id": "focused_shooting"}
    memory = {**empty_memory(), "recommendations": [focus], "reports": [
        {"focus_id": "prior_arm", "kind": "did_not_help", "text": "It did not help."}]}
    bad = {"message": "Let's continue that drill.", "adaptation": "continue"}
    good = {"message": "Let's put that approach aside.", "adaptation": "discontinue"}
    result, client = ask("The earlier drill did not help.", [bad, good], shots=shots, memory=memory)
    assert "focused_shooting" not in input_packet(client)["eligible_practice"]
    assert result.provenance["source"] == "openai_repaired"


@pytest.mark.parametrize("bad", ["bad JSON", {"message": "A fabricated result of 90 percent."}])
def test_unrepairable_output_falls_back_without_leaking_or_saving_rejected_text(bad):
    result, client = ask(QUESTION + " I have no hoop. I only have 1 minute.", [bad, bad])
    assert result.provenance["source"] == "fallback" and len(client.calls) == 2
    assert result.practice.drill_id == "shadow_rehearsal"
    assert result.practice.dose.duration_seconds <= 60
    assert "90 percent" not in response_text(result)


def test_provider_errors_remain_private(monkeypatch):
    from backend.app.agent import coaching_agent
    def unavailable(*args, **kwargs):
        raise ImportError("private host proxy configuration detail")
    monkeypatch.setenv("OPENAI_API_KEY", "test-placeholder-not-a-real-key")
    monkeypatch.setattr("backend.app.agent.provider.ProviderSettings.connect", unavailable)
    result, _ = ask(QUESTION)
    assert result.provenance["source"] == "fallback"
    assert result.provenance["reason"] == "model_transport_unavailable"
    assert "private host" not in result.model_dump_json()


def test_saved_live_drafts_replay_locally(monkeypatch):
    from evaluation.run import ROOT, replay_live_drafts

    def no_provider(*args, **kwargs):
        pytest.fail("Saved drafts must never use a provider")

    monkeypatch.setattr("backend.app.agent.provider.ProviderSettings.connect", no_provider)
    monkeypatch.setattr("backend.app.agent.provider.HttpProvider.request", no_provider)
    results = replay_live_drafts(ROOT / "evaluation/live-openai-coaching-baseline.json")
    assert len(results) == 15
    assert [(r["scenario"], r["attempt"]) for r in results if r["previous_rejection"] is None] == [(2, 1)]
    assert "cannot establish why shots missed" in next(r["local_rejection"] for r in results
                                                       if (r["scenario"], r["attempt"]) == (3, 1))
    assert "cannot establish why shots missed" in next(r["local_rejection"] for r in results if (r["scenario"], r["attempt"]) == (3, 2))


@pytest.mark.parametrize(("scenario", "question", "interpretation", "accuracy", "variable"), [
    ("consistent_high", "My form looks unconventional. Should I change it?",
     "Keep the motion that feels comfortable. Appearance alone gives me no reason to change it.", 80, False),
    ("consistent_low", "My mechanics look good and repeatable. Why am I still missing?",
     "Your repeatable setup is worth keeping. The outcomes and measured angles do not tell us why you missed.", 20, False),
    ("inconsistent_high", "My motion varies, but I'm making most shots. Should I fix it?",
     "The variation is real, but these results give me no reason to overhaul your shot. Keep what feels repeatable and comfortable.",
     80, True),
])
def test_session_outcomes_and_movement_variation_are_independent(scenario, question, interpretation, accuracy, variable):
    case = playground_scenario(scenario)
    message = "Your accuracy among known outcomes was {{fact:0}} percent. " + interpretation
    answer = {"message": message, "evidence_ids": ["session:1", "profile:current"],
              "facts": [{"evidence_id": "session:1", "field": "accuracy_pct"}]}
    result, client = ask(question, [answer], case=case)
    packet = input_packet(client)
    summary = packet["evidence"]["session:1"]
    group_stats = summary["measurements"]["min_knee_angle"]["by_outcome"]
    assert summary["accuracy_pct"] == accuracy
    assert group_stats["made"]["sample"] == summary["made"]
    assert group_stats["missed"]["sample"] == summary["missed"]
    assert (group_stats["made"]["spread"] > 1) == variable
    assert group_stats["made"]["median"] == group_stats["missed"]["median"]
    assert packet["evidence"]["profile:current"]["likely_patterns"] == []
    assert result.message == message.replace("{{fact:0}}", str(accuracy))
    assert result.practice is None and result.provenance["source"] == "openai_authored"
    assert len(client.calls) == 1


@pytest.mark.parametrize("tool", ["retrieve_comparison", "retrieve_make_miss"])
def test_author_can_check_contrasting_session_examples_without_a_pattern(tool):
    case = playground_scenario("consistent_low")
    made, missed = case["shots"][0], case["shots"][4]
    args = ({"first_id": made.shot_id, "second_id": missed.shot_id}
            if tool == "retrieve_comparison" else {"shot_id": made.shot_id})
    call = [{"type": "function_call", "name": tool, "call_id": "comparison", "arguments": json.dumps(args)}]
    key = f"tool:1:{tool}"
    answer = {"message": "This make and miss are useful examples to compare. A pair cannot explain the misses across the session.",
              "evidence_ids": ["profile:current", key]}
    result, client = ask("What can I learn from a made attempt and a missed attempt?", [call, answer], case=case)
    payload = next(item for item in client.calls[1]["inputs"] if item.get("type") == "function_call_output")
    comparison = json.loads(payload["output"])["result"]
    assert comparison["status"] == "available"
    assert comparison["first"]["outcome"] == "made" and comparison["second"]["outcome"] == "missed"
    assert comparison["matched_recorded_conditions"] is True
    assert comparison["differences"]["min_knee_angle"]["unit"] == "degrees"
    assert any("does not establish a pattern" in item for item in comparison["limitations"])
    assert input_packet(client)["evidence"]["profile:current"]["likely_patterns"] == []
    assert result.message == answer["message"] and result.practice is None


def test_exploratory_pairs_respect_the_current_session_and_player():
    case = playground_scenario("consistent_low")
    first = case["shots"][0]
    past = replace(first, shot_id="other_session", session_id=2, outcome="missed")
    foreign = replace(first, shot_id="another_player", player="SomeoneElse", outcome="missed")
    ctx = EvidenceContext(case["player"], "Why do I miss?", first.shot_id, (), [], case["memory"],
                          shots=[*case["shots"], past, foreign], session_id=1)
    ctx.collect(False)
    assert ctx.retrieve_comparison(first.shot_id, past.shot_id) == {"status": "unavailable"}
    assert ctx.retrieve_comparison(first.shot_id, foreign.shot_id) == {"status": "unavailable"}
    assert ctx.retrieve_make_miss(past.shot_id) == {"status": "unavailable"}
    pair = ctx.retrieve_make_miss(first.shot_id)
    assert pair["second"]["session_id"] == 1 and pair["second"]["player"] == case["player"]
    assert ctx.pair is None  # An exploratory pair does not replace the display selection.


def test_small_sample_shows_coverage_without_inventing_group_spread():
    case = playground_scenario("insufficient")
    answer = {"message": "This is too small a sample to explain the misses. I'd keep your comfortable form for now.",
              "evidence_ids": ["session:1", "profile:current"]}
    result, client = ask("What change will make me more accurate?", [answer], case=case)
    data = input_packet(client)["evidence"]
    stats = data["session:1"]["measurements"]["min_knee_angle"]["by_outcome"]
    assert all(group["sample"] == 1 and group["spread"] is None for group in stats.values())
    assert data["profile:current"]["status"] == "insufficient_data"
    assert result.message == answer["message"] and result.practice is None


def test_missing_release_and_flight_can_lead_to_targeted_catalog_lookup():
    case = playground_scenario("insufficient")
    first = case["shots"][0]
    biomech = {**first.analysis["biomechanics"], "release_elbow_angle": None}
    case["shots"][0] = replace(first, analysis={**first.analysis, "ball_tracking": {}, "biomechanics": biomech})
    call = [{"type": "function_call", "name": "retrieve_knowledge", "call_id": "catalog",
             "arguments": '{"topic":"recording"}'}]
    shot_id = f"shot:{first.shot_id}"
    answer = {"message": "I can't judge power or the release from this clip. As general recording guidance, use a steady side view that keeps the ball and shooting hand visible.",
              "evidence_ids": [shot_id], "knowledge_ids": ["recording"]}
    result, client = ask("Am I using too much power or releasing badly?", [call, answer], case=case)
    packet = input_packet(client)
    assert "recording" not in packet["knowledge"]
    shot = packet["evidence"][shot_id]
    assert shot["measurements"]["release_elbow_angle"]["status"] == "missing"
    assert shot["ball_flight"]["status"] == "unavailable"
    payload = next(item for item in client.calls[1]["inputs"] if item.get("type") == "function_call_output")
    lookup = json.loads(payload["output"])["result"]
    assert lookup["status"] == "available" and list(lookup["principles"]) == ["recording"]
    assert lookup["principles"]["recording"]["avoid_when"]
    assert result.knowledge_references[0]["id"] == "recording"
    assert result.message == answer["message"] and result.practice is None


def test_catalog_lookup_can_explicitly_report_no_relevant_entry():
    ctx = EvidenceContext("Fixture", "How should I shoot?", None, (), [], empty_memory(), shots=[])
    before = list(ctx.knowledge_ids)
    assert ctx.retrieve_knowledge("xyzzy unrelated topic") == {"status": "no_match", "principles": {}}
    assert ctx.knowledge_ids == before


def test_failed_advice_can_prompt_investigation_without_a_replacement_drill():
    case = playground_scenario("unsuccessful")
    tool = [{"type": "function_call", "name": "retrieve_progress", "call_id": "progress", "arguments": "{}"}]
    answer = {"message": "Set the knee cue aside. Did it feel uncomfortable or was it hard to repeat? That would affect what we check next.",
              "evidence_ids": ["tool:1:retrieve_progress"], "adaptation": "discontinue"}
    result, client = ask("The knee cue you suggested did not help.", [tool, answer], case=case)
    assert any(report["kind"] == "did_not_help" for report in input_packet(client)["player_context"]["reports"])
    assert "focused_shooting" not in input_packet(client)["eligible_practice"]
    assert result.previous_focus["id"] == case["memory"]["recommendations"][0]["id"]
    assert result.message == answer["message"] and result.practice is None
