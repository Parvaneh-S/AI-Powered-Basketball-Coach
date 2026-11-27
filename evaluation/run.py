"""Reproduce deterministic fixtures and optionally run a small live demo evaluation."""

import argparse
import json
import os
import tempfile
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from evaluation.scenarios import CASES, CRITICAL_FAILURES, RUBRIC

ROOT = Path(__file__).resolve().parents[1]


def replay_live_drafts(path):
    """Map archived prose to the current wire format and run current local checks only."""
    from pydantic import ValidationError

    from backend.app.agent.coaching_agent import bounded_history
    from backend.app.agent.coaching_narrative import AuthorEvidence, validate_answer
    from backend.app.agent.context import EvidenceContext
    from backend.app.agent.evidence import RecordedShot
    from backend.app.agent.memory import active_focus
    from backend.app.agent.provider import run_tool
    from backend.app.agent.player_input import player_update
    from backend.app.agent.response import CoachAnswer

    record = json.loads(path.read_text(encoding="utf-8"))
    results = []
    for scenario in record["scenarios"]:
        evidence = scenario["application_evidence"]
        shots = [RecordedShot(**shot) for shot in evidence["shots"]]
        question = scenario["question"]
        memory = evidence["memory_before"]
        memory = {**memory, **player_update(question, memory, active_focus(memory))}
        history = bounded_history(scenario["history_passed_to_playground"])
        ctx = EvidenceContext(scenario["player"], question, shots[0].shot_id, (), history, memory,
                              shots=shots, session_id=shots[0].session_id)
        ctx.collect(False)
        ledger = AuthorEvidence(ctx, history)
        ledger.packet()
        for index, call in enumerate(scenario["tools"], 1):
            name = call["name"]
            ledger.add({f"tool:{index}:{name}": run_tool(getattr(ctx, name), call["arguments_raw"])})
        if not ctx.frames:
            ctx.select_frames()
        ledger.packet()
        rejected = {event["attempt"]: event["reason"] for event in scenario["validation_and_reviews"]
                    if event["stage"] == "validation_failure"}
        for draft in scenario["raw_author_outputs"]:
            raw = draft["text"]
            attempt = draft["attempt"]
            result = {"scenario": scenario["number"], "title": scenario["title"], "attempt": attempt,
                      "previous_rejection": rejected.get(attempt), "local_rejection": None}
            try:
                historical = json.loads(raw)
                prose = historical["narrative"]
                fields = ("message", "explanation", "cue", "uncertainty", "next_step")
                message = [prose[field] for field in fields if prose.get(field)]
                message.extend(item["text"] for field in ("observations", "strengths") for item in prose.get(field, []))
                practice = prose.get("practice")
                # This adapter maps prose to the current wire format. The archived raw draft stays intact.
                answer = CoachAnswer(
                    message="\n\n".join(message), evidence_ids=list(dict.fromkeys(
                        prose.get("evidence_ids", []) + historical.get("observation_ids", []))),
                    facts=prose.get("facts", []), frame_ids=historical.get("frame_ids", []),
                    visual=historical.get("visual"), adaptation=historical.get("adaptation"),
                    knowledge_ids=[historical["knowledge_id"]] if historical.get("knowledge_id") else [],
                    practice={**{key: practice.get(key) for key in ("drill_id", "instructions", "evaluation", "dose")},
                              "topic": historical["knowledge_id"]} if practice else None,
                )
                validate_answer(answer, ledger)
            except (ValidationError, ValueError) as exc:
                result["local_rejection"] = str(exc)
                result["rejection_kind"] = getattr(exc, "kind", "contract")
            results.append(result)
    return results


def replay_phase_three_drafts(path):
    """Validate all captured drafts independently, with no provider or mock reviewer approval."""
    from backend.app.agent.coaching_agent import bounded_history
    from backend.app.agent.coaching_narrative import AnswerValidationError, AuthorEvidence, parse_answer, validate_answer
    from backend.app.agent.context import EvidenceContext
    from backend.app.agent.evidence import RecordedShot
    from backend.app.agent.memory import active_focus
    from backend.app.agent.player_input import player_update
    from evaluation.fixtures import phase_three_drafts

    results = []
    for row in json.loads(path.read_text(encoding="utf-8"))["scenarios"]:
        number = row["number"]
        if number not in (1, 4, 5, 6, 8):
            continue
        evidence = row["application_evidence"]
        shots = [RecordedShot(**shot) for shot in evidence["shots"]]
        memory = evidence["memory_before"]
        question = row["question"]
        history = bounded_history(row["history_passed_to_playground"])
        ctx = EvidenceContext(row["player"], question, shots[0].shot_id, (), history,
                              {**memory, **player_update(question, memory, active_focus(memory))},
                              shots=shots, session_id=shots[0].session_id)
        ctx.collect(False, prepare_examples=False)
        ctx.add_session_flight_observation()
        ledger = AuthorEvidence(ctx, history)
        ledger.packet()
        for attempt, draft in enumerate(phase_three_drafts(number, row["player"]), 1):
            discarded = []
            answer = parse_answer(json.dumps(draft), discarded)
            rejected = []
            try:
                validate_answer(answer, ledger, discarded)
            except AnswerValidationError as exc:
                rejected = exc.details
            results.append({"scenario": number, "attempt": attempt, "local_errors": rejected,
                            "discarded_components": discarded, "message_preserved": answer.message == draft["message"],
                            "independent_review": "not run"})
    return results


def run_case(case, monkeypatch=None):
    from backend.app.agent import context
    from backend.app.agent.coaching_agent import coach
    from backend.app.agent.coaching_narrative import AuthorEvidence
    from evaluation.fixtures import MockOpenAI, scenario_input

    player, shots, memory, options = scenario_input(case.fixture)
    fake = None
    if case.key == "conflicting":
        ids = ["frame:free_throw_03_shot_1:release:76", "frame:free_throw_03_shot_1:follow_through:82"]
        fake = MockOpenAI([{"message": "The arm bends between the two frames.", "frame_ids": ids, "visual": "arm_bends"},
                           {"message": "The frames do not establish that movement.", "frame_ids": ids}])
    if monkeypatch:
        class_scope = monkeypatch.context()
    else:
        from pytest import MonkeyPatch
        class_scope = MonkeyPatch.context()
    with class_scope as setting:
        setting.delenv("OPENAI_API_KEY", raising=False)
        setting.delenv("GEMINI_API_KEY", raising=False)
        if shots is not None:
            setting.setattr("backend.app.agent.retrieval.load_shots", lambda _: shots)
        if case.fixture == "unavailable_profile":
            setting.setattr("backend.app.agent.retrieval.personal_profile",
                            lambda *args: {"status": "unavailable"})
        data = context.EvidenceContext(player, case.question, options["selected"], options["comparison"],
                                       options["history"], memory)
        data.collect(multimodal=True)
        result = coach(player, case.question, **options, persist=False, client=fake, memory_state=("", memory))
    tool_results = AuthorEvidence(data).packet()
    tool_results["knowledge_ids"] = list(tool_results.pop("knowledge"))
    return {
        **asdict(case), "kind": "mocked_model" if fake else "deterministic_fallback",
        "player": player, "selected": options["selected"], "prior_turns": options["history"],
        "evidence_and_tool_results": {
            **tool_results, "comparison": data.pair, "form_profile": data.profile,
        },
        "coaching": result.model_dump(mode="json"),
    }


def assert_behaviour(key, result):
    observations = result["observations"]
    text = " ".join(item["text"] for item in observations)
    expected = {
        "too_few": lambda: bool(result["practice"]) and "pattern:" not in str(observations),
        "pattern": lambda: "pattern:min_knee_angle" in str(observations) and bool(result["uncertainty"]),
        "no_pattern": lambda: "no clear difference" in result["message"],
        "poor_tracking": lambda: "too limited" in text and not any(item.get("technical") for item in observations),
        "missing_measurements": lambda: "too limited" in text and not any(item.get("technical") for item in observations),
        "power": lambda: "release speed or how hard" in result["message"] and not observations,
        "unconventional_high": lambda: bool(result["strengths"]) and result["focus"] == "Individual technique",
        "conventional_low": lambda: "cannot tell us why" in result["message"],
        "multiple_issues": lambda: result["focus"] == "Knee bend" and bool(result["practice"]),
        "conflicting": lambda: "do not establish" in result["message"] and not observations,
        "pain": lambda: result["response_type"] == "pain" and result["practice"] is None and not observations,
        "worse": lambda: result["response_type"] == "reassess" and result["previous_focus"] and not result["cue"],
        "disagrees": lambda: result["response_type"] == "reassess" and result["clarification"] and not result["cue"],
        "beginner": lambda: result["focus"] == "Shooting consistency" and bool(result["practice"]),
        "experienced": lambda: observations[0]["technical"]["field"] == "release_elbow_angle"
        and observations[0]["technical"]["value"] == 120 and observations[0]["technical"]["unit"] == "degrees",
        "general": lambda: "one point" in result["message"] and not observations and not result["video_references"],
        "show_movement": lambda: {ref["phase"] for ref in result["video_references"]} == {"release", "follow_through"},
        "earlier_cue": lambda: result["previous_focus"]["id"] == "focus_from_prior_turn" and not result["cue"],
        "progress": lambda: result["progress"]["after"]["accuracy_pct"] == 100 and
        result["progress"]["after"]["spread"] == 0 and bool(result["uncertainty"]),
        "unavailable_profile": lambda: bool(result["practice"]) and "pattern:" not in str(observations),
        "invalid_video": lambda: result["response_type"] == "visual" and not result["video_references"],
        "other_player": lambda: result["response_type"] == "clarify" and not result["video_references"]
        and not observations and "fixture_shot_2" not in str(result),
    }
    assert expected[key](), f"{key} failed its deterministic behaviour check"


def demo_against_baseline():
    from backend.app.agent.coaching_agent import coach, response_text
    from backend.app.agent.memory import empty_memory

    baseline = json.loads((ROOT / "evaluation" / "baseline-main.json").read_text(encoding="utf-8"))
    player = baseline["player"]
    runs = []
    with patch.dict(os.environ, {"OPENAI_API_KEY": "", "GEMINI_API_KEY": ""}):
        for entry in baseline["cases"]:
            history = []
            if entry["prior_case"] is not None:
                previous = runs[entry["prior_case"]]
                history = [{"role": "user", "content": previous["question"]},
                           {"role": "assistant", "content": previous["final_text"]}]
            result = coach(player, entry["question"], selected=baseline["selected_video_id"],
                           history=history, persist=entry["prior_case"] is not None
                           or entry["question"] == "What should I practice today?",
                           memory_state=None if history or entry["question"] == "What should I practice today?"
                           else ("", empty_memory()))
            runs.append({"question": entry["question"], "prior_turns": history,
                         "original_model_output": entry["response"], "final_kind": "deterministic_fallback",
                         "final_text": response_text(result), "final_coaching": result.model_dump(mode="json")})
    return {"baseline_revision": baseline["revision"], "baseline_status": baseline["status"],
            "live_original_vs_final": "unavailable", "runs": runs}


def mocked_comparison():
    from backend.app.agent.coaching_agent import coach
    from backend.app.agent.memory import empty_memory
    from evaluation.fixtures import MockOpenAI

    frame_ids = ["frame:free_throw_03_shot_1:release:76", "frame:free_throw_03_shot_1:follow_through:82"]
    question = "Can you show me my follow through?"
    earlier = [{"role": "user", "content": "Please look at the free_throw_03 recording."},
               {"role": "assistant", "content": "We can check the estimated release and early follow-through."}]
    visual = {"message": "Watch the elbow straighten between these frames.", "frame_ids": frame_ids, "visual": "arm_straightens"}
    numeric = {"message": "Here are the saved frames near release.", "frame_ids": frame_ids}
    malformed = {"message": "Watch this frame.", "frame_ids": ["frame:unsupported:release:7"]}
    comparisons = []
    for mode, history, multimodal, choices in [
        ("numeric_only", [], False, [numeric]),
        ("multimodal", [], True, [visual]),
        ("conversation_aware", earlier, True, [visual]),
        ("rejected_citation_and_repair", earlier, True, [malformed, visual]),
    ]:
        fake = MockOpenAI(choices)
        result = coach("TestPlayer", question, selected="free_throw_03", client=fake,
                       multimodal=multimodal, history=history, persist=False, memory_state=("", empty_memory()))
        counts = [sum(part["type"] == "input_image" for item in request["inputs"]
                      if isinstance(item.get("content"), list) for part in item["content"])
                  for request in fake.calls if "inputs" in request]
        comparisons.append({"mode": mode, "prior_turns": history, "stubbed_decisions": choices,
                            "attached_image_counts_per_call": counts, "after_validation": result.model_dump(mode="json")})
    return comparisons


def live_comparison():
    from dotenv import load_dotenv
    from backend.app.agent.coaching_agent import coach
    from backend.app.agent.provider import PROVIDER_ERRORS, provider_diagnostic, provider_settings
    from backend.app.agent.memory import empty_memory

    load_dotenv(ROOT / ".env")
    settings = provider_settings()
    runs = []
    if not settings.key:
        return {"status": f"blocked: {settings.key_env} unavailable", "model": settings.model, "runs": runs,
                "top_level_requests": 0, "subjective_scores": None}

    class Capture:
        def __init__(self, client):
            self.client = client
            self.requests = []

        def respond(self, **kwargs):
            record = {"kind": "coaching_conversation"}
            self.requests.append(record)
            try:
                response = self.client.respond(**kwargs)
            except PROVIDER_ERRORS as error:
                record["error"] = provider_diagnostic(error, record["kind"])
                raise
            record["output"] = response
            return response

    history = [
        {"role": "user", "content": "I want to see what my shooting arm does right after the free_throw_03 release."},
        {"role": "assistant", "content": "Let's look at the release frame and the early follow-through."},
    ]
    with settings.connect() as client:
        for mode, multimodal, prior in [
            ("single_turn_numeric", False, []), ("single_turn_visual", True, []),
            ("conversation_aware_visual", True, history),
        ]:
            capture = Capture(client)
            result = coach("TestPlayer", "Can you show me the finish in my video?",
                           selected="free_throw_03", multimodal=multimodal, history=prior,
                           client=capture, persist=False, memory_state=("", empty_memory()))
            runs.append({"mode": mode, "prior_turns": prior, "requests": capture.requests,
                         "after_validation": result.model_dump(mode="json"), "subjective_scores": None})
            if any("error" in request for request in capture.requests):
                break
    return {"status": "API error" if any("error" in item for run in runs for item in run["requests"])
            else "captured, pending human review", "model": settings.model, "runs": runs,
            "top_level_requests": sum(len(run["requests"]) for run in runs),
            "subjective_scores": None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--live", action="store_true", help="Allow configured provider requests for the bundled demo clip.")
    mode.add_argument("--replay", type=Path, metavar="BASELINE", help="Replay saved author drafts offline and print local validation results.")
    mode.add_argument("--replay-phase-three", type=Path, metavar="BASELINE",
                      help="Replay the captured Phase 3 drafts against the original scenario evidence offline.")
    parser.add_argument("--output", type=Path, default=ROOT / "evaluation" / "results.json")
    args = parser.parse_args()
    if args.replay:
        print(json.dumps(replay_live_drafts(args.replay), indent=2, ensure_ascii=True))
        return 0
    if args.replay_phase_three:
        print(json.dumps(replay_phase_three_drafts(args.replay_phase_three), indent=2, ensure_ascii=True))
        return 0
    fixture_runs = []
    with tempfile.TemporaryDirectory(prefix="shotcoach_eval_") as directory, patch.dict(
        os.environ, {"SHOTCOACH_DB_PATH": str(Path(directory) / "demo.db")}
    ):
        for case in CASES:
            artifact = run_case(case)
            try:
                assert_behaviour(case.key, artifact["coaching"])
            except (AssertionError, AttributeError, IndexError, KeyError, TypeError) as exc:
                artifact["deterministic_check"] = f"failed: {exc}"
            else:
                artifact["deterministic_check"] = "passed"
            fixture_runs.append(artifact)
        baseline_runs = demo_against_baseline()
        with patch.dict(os.environ, {"OPENAI_API_KEY": "", "GEMINI_API_KEY": ""}):
            mocked_runs = mocked_comparison()
        live = live_comparison() if args.live else {
            "status": "not requested", "runs": [], "top_level_requests": 0, "subjective_scores": None,
        }
        from backend.app.agent.evidence import MEASUREMENTS
        from backend.app.agent.knowledge import KNOWLEDGE
        from backend.app.database.models import engine
        engine.dispose()
    record = {
        "measurement_dictionary": MEASUREMENTS, "coaching_knowledge": KNOWLEDGE,
        "generated_at": datetime.now(timezone.utc).isoformat(), "coaching_provider": "openai_responses",
        "deterministic_cases": fixture_runs, "demo_against_baseline": baseline_runs,
        "mocked_contract_comparisons": mocked_runs, "live_final_comparison": live,
        "rubric": RUBRIC, "critical_failures_rubric": CRITICAL_FAILURES,
        "subjective_evaluation": {"status": "not performed", "scores": None},
    }
    args.output.write_text(json.dumps(record, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    passed = sum(entry["deterministic_check"] == "passed" for entry in fixture_runs)
    print(f"{passed}/{len(fixture_runs)} deterministic coaching checks passed. Live evaluation: {live['status']}.")
    return int(passed != len(fixture_runs))


if __name__ == "__main__":
    raise SystemExit(main())
