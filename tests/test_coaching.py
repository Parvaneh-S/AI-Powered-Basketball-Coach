import base64
import json
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.app.agent import coaching_agent, profile
from backend.app.agent.coaching_agent import coach
from backend.app.agent.context import EvidenceContext
from backend.app.agent.evidence import MEASUREMENTS, measurement, shot_evidence
from backend.app.agent.openai_provider import OpenAIProvider
from backend.app.agent.provider import provider_settings
from backend.app.agent.memory import active_focus, empty_memory, read_memory, reset_memory, save_memory
from backend.app.agent.player_input import player_update
from backend.app.agent.profile import personal_profile
from backend.app.agent.progress import assess_progress
from backend.app.agent.retrieval import CoachingTools
from backend.app.agent.video import extract_frame, shot_frames, video_source
from backend.app.api.main import app
from evaluation.fixtures import MockOpenAI, fixture_focus, scenario_input, synthetic_shot
from evaluation.scenarios import CASES, grade

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def no_live_openai(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)


def test_measurement_definitions_and_provenance():
    shot = synthetic_shot()
    evidence = shot_evidence(shot)
    assert evidence["player"] == shot.player
    assert evidence["session_id"] == shot.session_id
    assert evidence["shot_id"] == shot.shot_id
    assert "SQLite" in evidence["provenance"]
    assert set(evidence["measurements"]) == MEASUREMENTS.keys()
    assert "ball launch angle" in MEASUREMENTS["release_elbow_angle"]["unsupported_interpretation"]
    assert "Angle accuracy" in MEASUREMENTS["knee_coverage_pct"]["unsupported_interpretation"]
    for field, definition in MEASUREMENTS.items():
        assert all(definition.values())
        assert definition["unit"] == evidence["measurements"][field]["unit"]


def test_missing_and_unreliable_values_are_withheld():
    shot = synthetic_shot(quality="review")
    shot.analysis["biomechanics"]["min_knee_angle"] = float("nan")
    assert measurement(shot, "min_knee_angle")["status"] == "missing"
    assert measurement(shot, "knee_angle_range")["status"] == "unreliable"
    assert measurement(shot, "knee_angle_range")["value"] is None
    assert measurement(shot, "release_elbow_angle")["status"] == "valid"
    assert measurement(shot, "elbow_coverage_pct")["value"] == 100


def test_explicit_comparison_and_scope():
    shots = [synthetic_shot(1), synthetic_shot(2, outcome="missed"), synthetic_shot(3),
             synthetic_shot(4, player="Other")]
    tools = CoachingTools("Fixture", "fixture_shot_2", shots=shots)
    assert tools.shot_analysis()["shot_id"] == "fixture_shot_2"
    assert tools.player_history("missed")["recent"][0]["shot_id"] == "fixture_shot_2"
    result = tools.compare_shots("fixture_shot_1", "fixture_shot_3")
    assert result["first"]["shot_id"] == "fixture_shot_1"
    assert result["second"]["shot_id"] == "fixture_shot_3"
    assert tools.compare_shots("fixture_shot_4", "fixture_shot_3") == {"status": "unavailable"}
    assert tools.shot_analysis("fixture_shot_4") == {"status": "unavailable"}
    assert tools.video_frames("fixture_shot_4") == []
    assert tools.make_miss_pair()["second"]["outcome"] == "made"


def test_named_comparison_stays_pinned_and_rejects_unrelated_tools():
    shots = [synthetic_shot(index) for index in (1, 2, 3)]
    ctx = EvidenceContext("Fixture", "Compare fixture_shot_2 with fixture_shot_1.", None, (),
                          [], empty_memory(), shots=shots)
    ctx.collect(multimodal=False)
    assert ctx.pair["first"]["shot_id"] == "fixture_shot_2"
    assert ctx.pair["second"]["shot_id"] == "fixture_shot_1"
    assert ctx.retrieve_comparison("fixture_shot_3", "fixture_shot_1") == {"status": "unavailable"}
    assert ctx.pair["first"]["shot_id"] == "fixture_shot_2"


def test_saved_goal_guides_general_practice():
    memory = {**empty_memory(), "goal": "Improve my follow through"}
    result = coach("NewPlayer", "What should I practice today?", persist=False, memory_state=("", memory))
    assert result.focus == "Follow-through"


def test_new_player_gets_a_focus_without_profile_configuration():
    player = uuid4().hex
    client = TestClient(app)
    params = {"player_name": player}
    before = client.get("/api/coach/memory", params=params).json()
    assert before["goal"] == before["experience"] == ""
    assert before["focus"] is None

    response = client.post("/api/coach/ask", json={**params, "question": "How can I improve my shot?"})
    assert response.status_code == 200
    result = response.json()["coaching"]
    assert result["response_type"] == "shot"
    assert result["practice"] and result["cue"] and not result["clarification"]
    assert result["memory_update"]["decision"] == "start"
    after = client.get("/api/coach/memory", params=params).json()
    assert after["goal"] == after["experience"] == ""
    assert after["preferences"] == {}
    assert after["focus"]["id"] == result["memory_update"]["id"]
    assert after["focus"]["guidance_basis"] == "general"
    assert after["focus"]["verified_personal_correction"] is False
    assert response.json()["coaching"]["provenance"]["source"] == "fallback"
    assert "model_not_configured" not in response.json()["answer"]


@pytest.mark.parametrize(("question", "topic"), [
    ("I keep missing free throws.", "Shooting consistency"),
    ("I struggle to shoot from further away.", "Trajectory and distance"),
    ("I want a quicker release.", "Leg and arm timing"),
])
def test_player_conversation_guides_one_practice_focus(monkeypatch, question, topic):
    player = uuid4().hex
    shot = synthetic_shot(player=player)
    monkeypatch.setattr("backend.app.agent.retrieval.load_shots", lambda name: [shot] if name == player else [])
    result = coach(player, question, selected=shot.shot_id, persist=False,
                   memory_state=("", empty_memory()))
    assert result.response_type == "shot"
    assert result.focus == topic
    assert result.practice
    assert result.clarification is None


def test_explicit_goal_replaces_existing_focus_and_persists():
    player = uuid4().hex
    first = coach(player, "What should I practice today?")
    assert first.focus == "Shooting consistency"
    faster = coach(player, "I want a quicker release.")
    assert faster.focus == "Leg and arm timing"
    assert faster.memory_update["decision"] == "modify"
    memory = read_memory(player)[1]
    assert memory["goal"] == "a quicker release"
    assert memory["experience"] == ""
    assert coach(player, "What should I practice today?").focus == "Leg and arm timing"
    feedback = coach(player, "The previous exercise didn’t help.")
    assert feedback.response_type == "reassess"
    assert feedback.previous_focus["id"] == faster.memory_update["id"]
    assert active_focus(read_memory(player)[1]) is None


def test_current_free_throw_concern_takes_priority_over_an_earlier_goal():
    player = uuid4().hex
    assert coach(player, "I want a quicker release.").focus == "Leg and arm timing"
    result = coach(player, "I keep missing free throws.")
    assert result.focus == "Shooting consistency"
    assert read_memory(player)[1]["goal"] == "a quicker release"


def test_beginner_and_feedback_preferences_apply_to_future_turns():
    player = uuid4().hex
    new_player = coach(player, "I'm new to basketball.")
    assert new_player.practice and new_player.practice.dose.repetitions == 5
    assert new_player.practice.dose.sets == 1
    assert new_player.explanation is None
    coach(player, "I prefer detailed feedback.")
    result = coach(player, "What should I practice today?")
    assert result.show_details
    assert result.explanation
    saved = read_memory(player)[1]
    assert saved["experience"] == "new to basketball"
    assert saved["preferences"] == {"explanation_style": "detailed"}
    coach(player, "I prefer simple feedback.")
    result = coach(player, "What should I practice today?")
    assert not result.show_details and result.explanation is None
    assert read_memory(player)[1]["preferences"] == {"explanation_style": "simple"}


def test_existing_context_loads_without_preferences_key():
    player = uuid4().hex
    legacy = {"goal": "Improve my follow through", "experience": "intermediate",
              "recommendations": [], "reports": []}
    assert save_memory(player, "", legacy)
    result = coach(player, "What should I practice today?")
    assert result.focus == "Follow-through"
    stored = read_memory(player)[1]
    assert stored["goal"] == legacy["goal"] and stored["experience"] == legacy["experience"]
    assert stored["preferences"] == {}


@pytest.mark.parametrize("question", [
    "I want to see my release.",
    "I want to make dinner.",
    'My teammate said, "I prefer detailed feedback."',
    "If I were new to basketball, what would I practice?",
    "Does 'I am a beginner' affect the coach?",
    "I want a quicker release?",
])
def test_context_is_not_inferred_from_questions_or_other_people(question):
    assert player_update(question, empty_memory(), None) == {}


def test_adapter_uses_existing_analysis_and_attaches_support():
    _, shots, _, _ = scenario_input("pattern")
    shots.append(synthetic_shot(13, outcome="missed", quality="review", knee=30))
    shots.append(synthetic_shot(14, outcome="made", arm="left", knee=30))
    result = personal_profile(shots, shots[0])
    assert "min_knee_angle" in result["likely_patterns"]
    feature = result["features"]["min_knee_angle"]
    assert feature["n_made"] == len(feature["made_shot_ids"]) == 6
    assert feature["n_missed"] == len(feature["missed_shot_ids"]) == 6
    assert feature["direction"] == "lower_on_makes"
    assert result["conditions"] == {"shot_type": "free_throw", "shooting_arm": "right"}
    assert result["sample_shots"] == 13


def test_free_throw_03_reference_decodes():
    tools = CoachingTools("TestPlayer", "free_throw_03")
    frames = tools.video_frames()
    assert [(ref.phase, ref.frame, ref.timestamp_s) for ref, _ in frames] == [
        ("preparation", 28, 0.933), ("release", 76, 2.533), ("follow_through", 82, 2.733)
    ]
    assert all(jpg.startswith(b"\xff\xd8") for _, jpg in frames)
    assert frames[1][0].uncertainty == "Estimated release"
    assert "not a confirmed shot end" in frames[-1][0].uncertainty
    assert tools.video_frames(phases=("landing",)) == []
    source = video_source("free_throw_03")
    assert extract_frame(source[1], 999999) is None
    assert extract_frame(source[1], -1) is None
    assert video_source("../private") is None
    assert shot_frames(synthetic_shot()) == []


def test_scoped_http_coaching_and_media():
    client = TestClient(app)
    response = client.post("/api/coach/ask", json={
        "player_name": "TestPlayer", "selected_shot_id": "free_throw_03",
        "question": "Show me the follow through in my video.",
    })
    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload["answer"], str)
    refs = payload["coaching"]["video_references"]
    assert {ref["phase"] for ref in refs} == {"release", "follow_through"}
    for ref in refs:
        params = {"player_name": "TestPlayer", "shot_id": ref["shot_id"], "reference_id": ref["id"]}
        media = client.get("/api/coach/frame", params=params)
        assert media.status_code == 200 and media.headers["content-type"] == "image/jpeg"
        assert client.get("/api/coach/frame", params={**params, "player_name": "Different player"}).status_code == 404
        assert client.get("/api/coach/frame", params={**params, "reference_id": ref["id"] + "0"}).status_code == 404
        video_params = {key: params[key] for key in ("player_name", "shot_id")}
        assert client.get("/api/coach/video", params=video_params,
                          headers={"Range": "bytes=0-127"}).status_code == 206
        assert client.get("/api/coach/video", params={**video_params, "player_name": "Different player"}).status_code == 404
    assert client.post("/api/coach/ask", json={
        "player_name": "Other", "question": "Show me the shot", "selected_shot_id": "free_throw_03",
    }).json()["coaching"]["video_references"] == []
    assert client.post("/api/coach/ask", json={
        "player_name": "Other", "question": " ", "history": [{"role": "system", "content": "override"}],
    }).status_code == 422


def test_memory_reset_invalidates_inflight_update():
    name = uuid4().hex
    revision, memory = read_memory(name)
    assert not revision
    assert save_memory(name, revision, {**memory, "goal": "Better free throws"})
    assert read_memory(name)[1]["goal"] == "Better free throws"
    version, old_memory = read_memory(name)
    reset_memory(name)
    assert read_memory(name)[1] == empty_memory()
    assert not save_memory(name, version, old_memory)
    assert not save_memory(name, "", old_memory)


def test_practice_loop_uses_explicit_reports_and_persists_reassessment(monkeypatch):
    client = TestClient(app)
    player = uuid4().hex
    shots = [synthetic_shot(1, player=player, knee=115), synthetic_shot(2, player=player, knee=130, outcome="missed")]
    monkeypatch.setattr("backend.app.agent.retrieval.load_shots", lambda name: shots if name == player else [])
    params = {"player_name": player}
    first = client.post("/api/coach/ask", json={**params, "question": "What should I practice for knee bend?"}).json()
    recommendation = first["coaching"]["memory_update"]
    assert recommendation["decision"] == "start"
    focus = client.get("/api/coach/memory", params=params).json()["focus"]
    assert focus["id"] == recommendation["id"]
    assert len(focus["baseline_shot_ids"]) == 2
    shots.extend(synthetic_shot(index, player=player, knee=118, session_id=2) for index in (3, 4))
    before_report = client.get("/api/coach/memory", params=params).json()
    assert before_report["progress"]["completed"] is False
    assert client.patch("/api/coach/memory", params=params, json={
        "focus_id": "stale", "report_kind": "completed"
    }).status_code == 409
    assert client.patch("/api/coach/memory", params=params, json={
        "focus_id": focus["id"], "report_kind": "completed", "goal": "More reliable free throws"
    }).status_code == 200
    progress = client.post("/api/coach/ask", json={**params, "question": "Am I improving?"}).json()["coaching"]
    assert progress["progress"]["completed"] is True
    assert progress["progress"]["before"]["accuracy_pct"] == 50
    assert progress["progress"]["after"]["accuracy_pct"] == 100
    assert progress["progress"]["before"]["spread"] == 7.5
    assert progress["progress"]["after"]["spread"] == 0
    assert progress["progress"]["assessment"]["overall"] == "insufficient"
    assert progress["memory_update"] is None
    worse = client.post("/api/coach/ask", json={
        **params, "question": "I tried your previous advice, but it did not help.",
    }).json()["coaching"]
    assert worse["previous_focus"]["id"] == focus["id"]
    assert worse["memory_update"]["decision"] == "discontinue"
    assert client.get("/api/coach/memory", params=params).json()["focus"] is None
    assert client.get("/api/coach/memory", params={"player_name": "Else"}).json()["reports"] == []
    assert client.delete("/api/coach/memory", params=params).status_code == 204
    assert client.get("/api/coach/memory", params=params).json()["reports"] == []


@pytest.mark.parametrize("via_chat", [True, False])
def test_difficulty_feedback_simplifies_the_active_practice_plan(via_chat):
    client = TestClient(app)
    params = {"player_name": uuid4().hex}

    def ask(question):
        response = client.post("/api/coach/ask", json={**params, "question": question})
        assert response.status_code == 200
        return response.json()["coaching"]

    ask("I am an advanced player.")
    first = ask("What should I practice for my shooting arm?")
    original = first["practice"]
    focus_id = first["memory_update"]["id"]
    assert original["drill_id"] == "focused_shooting"

    if via_chat:
        simplified = ask("I found it difficult.")
    else:
        report = client.patch("/api/coach/memory", params=params, json={
            "focus_id": focus_id, "report_kind": "difficulty", "report": "The set felt difficult."
        })
        assert report.status_code == 200
        simplified = ask("What should I practice today?")

    assert "last drill felt difficult" in simplified["message"]
    assert simplified["focus"] == first["focus"]
    practice = simplified["practice"]
    assert practice["drill_id"] == "close_delivery"
    assert practice["dose"]["duration_seconds"] < original["dose"]["duration_seconds"]
    assert simplified["memory_update"]["decision"] == "modify"
    memory = client.get("/api/coach/memory", params=params).json()
    assert memory["reports"][-1]["kind"] == "difficulty"
    assert memory["reports"][-1]["focus_id"] == focus_id
    assert memory["focus"]["id"] == simplified["memory_update"]["id"]
    repeat = ask("What should I practice for my shooting arm?")
    assert repeat["practice"]["drill_id"] == practice["drill_id"]
    assert repeat["practice"]["dose"] == practice["dose"]
    assert repeat["memory_update"] is None
    different = ask("What should I practice for knee bend?")
    assert different["practice"]["drill_id"] == "focused_shooting"


def test_difficulty_feedback_reduces_workload_if_the_drill_stays_the_same():
    player = uuid4().hex
    coach(player, "I am a beginner.")
    first = coach(player, "What should I practice for my shooting arm?")
    simpler = coach(player, "The drill felt too hard.")

    assert simpler.practice.drill_id == first.practice.drill_id == "close_delivery"
    assert simpler.practice.dose.repetitions < first.practice.dose.repetitions
    assert simpler.memory_update["decision"] == "modify"
    repeat = coach(player, "What should I practice for my shooting arm?")
    assert repeat.practice.dose == simpler.practice.dose


def test_player_statements_and_different_conditions():
    _, shots, memory, _ = scenario_input("focus")
    focus = active_focus(memory)
    assert player_update("If I completed the drill, how would you know?", memory, focus) == {}
    assert player_update("I completed the drill. Am I improving?", memory, focus)["reports"][0]["kind"] == "completed"
    assert player_update("I'm a beginner.", memory, focus)["experience"] == "beginner"
    assert player_update("My goal is to make more free throws.", memory, focus)["goal"] == "make more free throws"
    alternate = synthetic_shot(3, arm="left")
    assert assess_progress(shots + [alternate], focus, [])["status"] == "no_comparable_new_shots"


def test_openai_tool_declarations_and_ordered_conversation():
    history = [{"role": "user", "content": "Let's look at free_throw_03."},
               {"role": "assistant", "content": "This is the shot we discussed."}]
    call = [{"type": "function_call", "name": "retrieve_frames", "call_id": "frame",
             "arguments": '{"shot_id":"free_throw_03","phases":"release","focus":"elbow"}'}]
    replies = iter([call, output_message({"message": "Here is your estimated-release frame.",
                                         "frame_ids": ["frame:free_throw_03_shot_1:release:76:elbow:"]})])
    requests = []

    def respond(request):
        assert request.url.path == "/v1/responses"
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={"output": next(replies)})

    with OpenAIProvider("test-only", transport=httpx.MockTransport(respond)) as client:
        result = coach("TestPlayer", "Can you show that for me?", history=history,
                       client=client, persist=False, memory_state=("", empty_memory()))
    payload = json.loads(requests[0]["input"][0]["content"][0]["text"])
    assert payload["conversation"] == history
    assert payload["scope"]["selected_shot"] == "free_throw_03_shot_1"
    assert result.provenance["source"] == "openai_authored"
    assert "angle_arc" in result.video_references[0]["annotation"]["marks"]
    assert any(part["type"] == "input_image" for item in requests[1]["input"]
               if item.get("role") == "user" for part in item["content"])
    declaration = next(tool for tool in requests[0]["tools"] if tool["name"] == "retrieve_frames")
    assert "focus" in declaration["parameters"]["properties"]


def output_message(value):
    return [{"type": "message", "content": [{"type": "output_text",
                                           "text": json.dumps(value) if isinstance(value, dict) else value}]}]


def test_provider_configuration_is_explicit_and_keeps_credentials_separate(monkeypatch):
    monkeypatch.delenv("SHOTCOACH_PROVIDER", raising=False)
    monkeypatch.delenv("SHOTCOACH_MODEL", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "openai-test-key")
    monkeypatch.setenv("OPENAI_MODEL", "openai-test-model")
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-test-key")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-test-model")
    settings = provider_settings()
    assert (settings.name, settings.model, settings.key) == ("openai", "openai-test-model", "openai-test-key")
    monkeypatch.setenv("SHOTCOACH_PROVIDER", "gemini")
    monkeypatch.setenv("SHOTCOACH_MODEL", "gemini-override")
    settings = provider_settings()
    assert (settings.name, settings.model, settings.key) == ("gemini", "gemini-override", "gemini-test-key")
    monkeypatch.delenv("GEMINI_API_KEY")
    assert provider_settings().key == ""


def test_gemini_coaching_tool_round_keeps_native_state_and_shared_safeguards(monkeypatch):
    from backend.app.agent.gemini_provider import GeminiProvider

    monkeypatch.setenv("SHOTCOACH_PROVIDER", "gemini")
    monkeypatch.setenv("SHOTCOACH_MODEL", "gemini-test-model")
    requests = []
    call = {"functionCall": {"name": "retrieve_frames", "args": {"phases": "release", "focus": "elbow"}, "id": "frame-call"},
            "thoughtSignature": "opaque-test-signature"}
    frame_id = "frame:free_throw_03_shot_1:release:76:elbow:"
    answer = {"message": "Here is the estimated-release frame.", "frame_ids": [frame_id]}
    replies = iter([
        [call],
        [{"text": json.dumps(answer)}],
    ])

    def respond(request):
        assert request.url.host == "generativelanguage.googleapis.com"
        assert request.url.path == "/v1beta/models/gemini-test-model:generateContent"
        assert request.headers["x-goog-api-key"] == "test-only"
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={
            "modelVersion": "gemini-test-snapshot",
            "candidates": [{"content": {"role": "model", "parts": next(replies)}}],
            "usageMetadata": {"promptTokenCount": 120, "cachedContentTokenCount": 20,
                              "candidatesTokenCount": 20, "thoughtsTokenCount": 5},
        })

    with GeminiProvider("test-only", transport=httpx.MockTransport(respond)) as client:
        result = coach("TestPlayer", "Can you show that for me?", selected="free_throw_03",
                       client=client, persist=False, memory_state=("", empty_memory()))

    declarations = requests[0]["tools"][0]["functionDeclarations"]
    frame_tool = next(tool for tool in declarations if tool["name"] == "retrieve_frames")
    assert "parametersJsonSchema" in frame_tool and "parameters" not in frame_tool
    second = requests[1]["contents"]
    assert any(part == call for turn in second if turn["role"] == "model" for part in turn["parts"])
    response = next(part["functionResponse"] for turn in second for part in turn["parts"] if "functionResponse" in part)
    assert response["id"] == "frame-call" and response["response"]["result"]["frames"][0]["id"] == frame_id
    assert any(part.get("inlineData", {}).get("mimeType") == "image/jpeg" for turn in second for part in turn["parts"])
    assert result.message == answer["message"] and result.video_references[0]["id"] == frame_id
    assert "angle_arc" in result.video_references[0]["annotation"]["marks"]
    assert result.provenance["source"] == "gemini_authored"
    assert [row["output_tokens"] for row in result.provenance["request_usage"]["requests"]] == [25, 25]


def test_gemini_uses_the_same_local_repair(monkeypatch):
    from backend.app.agent.gemini_provider import GeminiProvider

    monkeypatch.setenv("SHOTCOACH_PROVIDER", "gemini")
    requests = []
    replies = iter([
        {"message": "Your release elbow angle was 200 degrees."},
        {"message": "Your release elbow angle was 120 degrees."},
    ])

    def respond(request):
        requests.append(json.loads(request.content))
        part = {"text": json.dumps(next(replies))}
        return httpx.Response(200, json={"candidates": [{"content": {"role": "model", "parts": [part]}}]})

    with GeminiProvider("test-only", transport=httpx.MockTransport(respond)) as client:
        result = coach("Fixture", "What was my release elbow angle?", shots=[synthetic_shot()],
                       selected="fixture_shot_1", client=client, persist=False, multimodal=False,
                       memory_state=("", empty_memory()))
    assert result.provenance["source"] == "gemini_repaired"
    assert result.message == "Your release elbow angle was 120 degrees."
    assert "tools" not in requests[1]
    assert requests[1]["generationConfig"]["responseMimeType"] == "application/json"
    assert requests[1]["generationConfig"]["responseJsonSchema"]["required"] == ["message"]
    assert "validation_details" in requests[1]["contents"][-1]["parts"][0]["text"]


def test_saved_follow_up_keeps_the_initial_request_compact():
    from backend.app.agent.evidence import RecordedShot

    baseline = json.loads((ROOT / "evaluation/live-openai-coaching-baseline.json").read_text(encoding="utf-8"))
    case = next(row for row in baseline["scenarios"] if row["number"] == 8)
    evidence = case["application_evidence"]
    shots = [RecordedShot(**row) for row in evidence["shots"]]
    requests = []

    def respond(request):
        requests.append(request.content)
        return httpx.Response(200, json={"output": output_message({"message": "What felt different when you tried it?"})})

    with OpenAIProvider("test-only", transport=httpx.MockTransport(respond)) as client:
        result = coach(case["player"], case["question"], shots=shots, selected=shots[0].shot_id,
                       session_id=1, history=case["history_passed_to_playground"], multimodal=False,
                       client=client, persist=False, memory_state=("", evidence["memory_before"]))
    request, = requests
    packet = json.loads(json.loads(request)["input"][0]["content"][0]["text"])
    assert packet["conversation"] == case["history_passed_to_playground"]
    assert packet["player_context"]["focus"] and packet["visual_mode"] == "references_only"
    assert len(request) < 30_000 and "numeric_facts" not in packet
    assert not any("drills" in entry for entry in packet["knowledge"].values())
    assert result.provenance["source"] == "openai_authored"


def test_structured_answer_uses_openai_json_schema_transport():
    payloads = []
    key = "shot:fixture_shot_1:release_elbow_angle"
    outputs = iter([
        {"message": "The estimated-release elbow angle was {{fact:0}} degrees.",
         "evidence_ids": [key], "facts": [{"evidence_id": key, "field": "value"}]},
    ])

    def respond(request):
        payloads.append(json.loads(request.content))
        assert request.url.path == "/v1/responses"
        return httpx.Response(200, json={"output": output_message(next(outputs))})

    with OpenAIProvider("test-only", transport=httpx.MockTransport(respond)) as client:
        result = coach("Fixture", "How many degrees was my release elbow angle?", shots=[synthetic_shot()],
                       selected="fixture_shot_1", client=client, multimodal=False,
                       persist=False, memory_state=("", empty_memory()))

    payload = payloads[0]
    response_format = payload["text"]["format"]
    assert payload["store"] is False
    assert response_format["type"] == "json_schema" and response_format["strict"] is False
    schema = response_format["schema"]
    assert schema["additionalProperties"] is False
    assert schema["required"] == ["message"]
    assert {"intent", "draft", "narrative"}.isdisjoint(schema["properties"])
    practice = schema["$defs"]["PracticeProposal"]
    assert {"drill_id", "topic", "instructions"} == set(practice["required"])
    assert "120 degrees" in result.message
    assert result.authored_evidence["observations"][key]["technical"]["value"] == 120


def test_openai_tool_loop_only_calls_allowed_functions_and_valid_arguments():
    payloads = []
    from backend.app.agent.coaching_agent import MAX_TOOL_ROUNDS
    calls = [("retrieve_shot", '{"shot_id":"another_players_shot"}'),
             ("unregistered_tool", "{}"), ("retrieve_shot", '{"shot_id":15}')]
    calls += [("unregistered_tool", "{}")] * (MAX_TOOL_ROUNDS - len(calls))

    def respond(request):
        payloads.append(json.loads(request.content))
        index = len(payloads) - 1
        if index >= len(calls):
            reply = {"message": "I can only review a shot from your own recordings."}
            return httpx.Response(200, json={"output": output_message(reply)})
        name, arguments = calls[index]
        return httpx.Response(200, json={"output": [{
            "type": "function_call", "call_id": f"call_{index}", "name": name, "arguments": arguments,
        }]})

    shots = [synthetic_shot(), synthetic_shot(2, player="SomeoneElse")]
    with OpenAIProvider("test-only", transport=httpx.MockTransport(respond)) as client:
        result = coach("Fixture", "Show my shot.", shots=shots, client=client, persist=False,
                       memory_state=("", empty_memory()), multimodal=False)

    assert result.provenance["source"] == "openai_authored"
    assert len(payloads) == MAX_TOOL_ROUNDS + 1
    assert "tools" not in payloads[-1]
    assert "fixture_shot_2" not in json.dumps(payloads)
    statuses = [json.loads(item["output"])["result"]["status"] for item in payloads[-1]["input"]
                if item.get("type") == "function_call_output"]
    assert statuses[:3] == ["unavailable", "unavailable", "invalid_arguments"]
    assert set(statuses[3:]) <= {"unavailable"}


def test_openai_request_usage_tracks_all_phases_and_cache_discount(monkeypatch, caplog):
    monkeypatch.setenv("SHOTCOACH_DEBUG", "1")
    monkeypatch.setenv("SHOTCOACH_OPENAI_PRICING", json.dumps({
        "mock-model-snapshot": {"input": 2, "cached_input": 0.5, "output": 4},
    }))
    decision = {"message": "A free throw is an uncontested shot from the foul line.",
                "knowledge_ids": ["free_throw"]}
    outputs = iter([
        [{"type": "function_call", "name": "retrieve_history", "arguments": "{}", "call_id": "call_history"}],
        output_message("bad JSON"), output_message(decision),
    ])

    def respond(request):
        return httpx.Response(200, json={
            "model": "mock-model-snapshot", "output": next(outputs),
            "usage": {"input_tokens": 100, "input_tokens_details": {"cached_tokens": 20}, "output_tokens": 25},
        })

    with OpenAIProvider("test-only", transport=httpx.MockTransport(respond)) as client:
        result = coach("Fixture", "What is a free throw?", client=client, shots=[],
                       persist=False, memory_state=("", empty_memory()))
    usage = result.provenance["request_usage"]
    assert result.provenance["source"] == "openai_repaired"
    assert result.message == decision["message"]
    assert usage["total_requests"] == 3
    assert usage["estimated_cost_usd"] == pytest.approx(0.00081)
    assert [entry["purpose"] for entry in usage["requests"]] == ["planning", "generation", "repair"]
    for entry in usage["requests"]:
        assert entry["model"] == "mock-model-snapshot"
        assert (entry["input_tokens"], entry["cached_input_tokens"], entry["output_tokens"]) == (100, 20, 25)
        assert entry["estimated_cost_usd"] == pytest.approx(0.00027)
        assert entry["latency_ms"] >= 0
    trace = json.loads(caplog.records[-1].getMessage().split("ShotCoach development trace ", 1)[1])
    assert trace["request_usage"] == usage


@pytest.mark.parametrize("failed", [False, True])
def test_openai_request_usage_leaves_unreported_values_unknown(monkeypatch, failed):
    monkeypatch.setenv("SHOTCOACH_OPENAI_PRICING", "invalid JSON")
    outputs = iter([{"message": "Let's review the release position."}])

    def respond(request):
        if failed:
            raise httpx.ReadTimeout("mock timeout")
        return httpx.Response(200, json={"output": output_message(next(outputs))})

    with OpenAIProvider("test-only", transport=httpx.MockTransport(respond)) as client:
        result = coach("Fixture", "How many degrees was my release elbow angle?",
                       selected="fixture_shot_1", shots=[synthetic_shot()], client=client,
                       persist=False, memory_state=("", empty_memory()))
    usage = result.provenance["request_usage"]
    assert usage["total_requests"] == 1
    assert usage["estimated_cost_usd"] is None
    entry = usage["requests"][0]
    assert entry["model"] == provider_settings().model
    assert entry["purpose"] == "generation"
    assert entry["input_tokens"] is entry["cached_input_tokens"] is entry["output_tokens"] is None
    assert entry["estimated_cost_usd"] is None
    assert result.provenance["reason"] == ("provider_error" if failed else None)


def test_json_repair_and_conservative_fallback():
    invalid = {"message": "Your elbow was 173 degrees and caused the miss.", "evidence_ids": ["shot:arbitrary"]}
    fake = MockOpenAI([invalid, "bad JSON"])
    result = coach("TestPlayer", "How can I improve my shot?", selected="free_throw_03",
                   client=fake, persist=False, memory_state=("", empty_memory()))
    assert len(fake.calls) == 2
    assert "validation" in fake.calls[-1]["inputs"][-1]["content"][0]["text"]
    assert "arbitrary" not in result.model_dump_json()
    assert result.practice is not None
    corrected = {"message": "Start from a comfortable, repeatable setup."}
    fake = MockOpenAI([invalid, corrected])
    repaired = coach("TestPlayer", "How can I improve my shot?", selected="free_throw_03",
                     client=fake, persist=False, memory_state=("", empty_memory()))
    assert repaired.message == corrected["message"] and repaired.practice is None


def test_multimodal_input_and_numerical_only_conflict():
    frame_ids = ["frame:free_throw_03_shot_1:release:76", "frame:free_throw_03_shot_1:follow_through:82"]
    choices = {"message": "Watch your shooting arm straighten.", "frame_ids": frame_ids,
               "visual": "arm_straightens"}
    data = {"selected": "free_throw_03", "persist": False, "memory_state": ("", empty_memory())}
    call = [{"type": "function_call", "name": "retrieve_frames", "call_id": "sequence",
             "arguments": '{"phases":"release,follow_through"}'}]
    model = MockOpenAI([call, choices])
    result = coach("TestPlayer", "Show me my follow through.", client=model, **data)
    images = [part["image_url"] for item in model.calls[1]["inputs"] if item.get("role") == "user"
              for part in item["content"] if part["type"] == "input_image"]
    assert len(images) == 2 and all(base64.b64decode(image.split(",", 1)[1]).startswith(b"\xff\xd8") for image in images)
    assert [item["id"] for item in result.video_references] == frame_ids
    corrected = {"message": "See the two saved phases.", "frame_ids": frame_ids}
    conflicting_tag = MockOpenAI([call, {**choices, "visual": "arm_bends"}])
    result = coach("TestPlayer", "Show me my follow through.", client=conflicting_tag, **data)
    assert result.provenance["source"] == "openai_authored" and result.message == choices["message"]
    assert [item["field"] for item in result.provenance["discarded_components"]] == ["visual"]
    numeric_only = MockOpenAI([call, choices, corrected])
    result = coach("TestPlayer", "Show me my follow through.", multimodal=False, client=numeric_only, **data)
    assert result.provenance["source"] == "openai_repaired" and result.message == corrected["message"]
    assert "input_image" not in json.dumps(numeric_only.calls[1]["inputs"])


def test_invalid_response_cannot_write_memory(monkeypatch):
    name = uuid4().hex
    monkeypatch.setattr(coaching_agent, "record_recommendation", lambda decision, *_: (
        pytest.fail("Rejected action survived") if decision.knowledge_id == "invented" else None
    ))
    fake = MockOpenAI([{"message": "A free throw is taken from the foul line.", "knowledge_ids": ["invented"],
                        "adaptation": "modify"}])
    coach(name, "What is a free throw?", client=fake)
    assert read_memory(name)[1] == empty_memory()


def test_profile_unavailable_fails_gracefully(monkeypatch):
    import sys

    monkeypatch.setitem(sys.modules, "backend.app.ml.form_profile", None)
    assert profile.personal_profile([synthetic_shot()])["status"] == "unavailable"


def test_rubric_reports_denominator_and_critical_failure():
    outcome = grade({"evidence_grounding": 4, "clarity": 2, "visual_relevance": None})
    assert outcome["score_pct"] == 81.25 and outcome["applicable_weight"] == 40
    assert grade({"evidence_grounding": 4}, ["Fabricated personal measurements"])["valid_for_comparison"] is False


@pytest.mark.parametrize("case", CASES, ids=[item.key for item in CASES])
def test_coaching_evaluation_fixtures(case, monkeypatch):
    from evaluation.run import assert_behaviour, run_case

    artifact = run_case(case, monkeypatch)
    assert_behaviour(case.key, artifact["coaching"])


@pytest.fixture
def phase_two(monkeypatch):
    monkeypatch.setattr("backend.app.agent.retrieval.shot_frames", lambda *_: [])

    def run(question, shots=None, memory=None, client=None, **options):
        shots = [synthetic_shot()] if shots is None else shots
        monkeypatch.setattr("backend.app.agent.retrieval.load_shots", lambda _: shots)
        return coach("Fixture", question, selected=shots[0].shot_id if shots else None,
                     memory_state=("", memory or empty_memory()), client=client,
                     persist=False, multimodal=False, **options)
    return run


def test_phase_two_broad_question_is_not_arm_request(phase_two):
    result = phase_two("How can I improve my shooting?")
    assert result.focus == "Shooting consistency"
    assert result.guidance_basis == "general"
    assert not result.provenance["supporting_evidence_ids"]
    assert result.provenance["source"] == "fallback"
    assert result.provenance["reason"] == "model_not_configured"


@pytest.mark.parametrize(("question", "topic"), [
    ("How can I improve my shooting arm?", "Shooting arm"),
    ("What should I practice for my knee bend?", "Knee bend"),
    ("I want a quicker release.", "Leg and arm timing"),
    ("How can I improve my follow-through?", "Follow-through"),
])
def test_phase_two_explicit_technique_preserved(phase_two, question, topic):
    result = phase_two(question)
    assert result.focus == topic and result.guidance_basis == "general"


def test_phase_two_personal_pattern_beats_shooting_keyword(phase_two):
    _, shots, _, _ = scenario_input("pattern")
    result = phase_two("How can I improve my shooting?", shots)
    assert result.focus == "Knee bend"
    assert result.guidance_basis == "personal_pattern"
    assert result.provenance["supporting_evidence_ids"][0].startswith("pattern:min_knee_angle:")
    explicit = phase_two("How can I improve my shooting arm?", shots)
    assert explicit.focus == "Shooting arm" and explicit.guidance_basis == "general"


def test_phase_two_pattern_ranking_ignores_retrieval_order():
    from backend.app.agent.response import Observation
    ctx = EvidenceContext("Fixture", "How can I improve my shooting?", "fixture_shot_1",
                          (), [], empty_memory(), shots=[synthetic_shot()])
    for topic, field, effect in (("arm", "release_elbow_angle", 0.6), ("knees", "min_knee_angle", 1.8)):
        key = f"pattern:{field}:fixture"
        ctx.observations[key] = Observation(text="Qualified fixture association", evidence_ids=[key],
            technical={"field": field, "effect_size": effect, "n_made": 8, "n_missed": 8})
        ctx.observation_topics[key] = topic
    assert ctx.priority()[0] == "knees"
    ctx.knowledge_ids.reverse()
    assert ctx.priority()[0] == "knees"


@pytest.mark.parametrize("question", ["What am I doing well?", "What should I keep doing?",
                                      "Is there anything good about my shooting?"])
def test_phase_two_strengths_are_supported_not_corrections(phase_two, question):
    result = phase_two(question, [synthetic_shot(1), synthetic_shot(2)], session_id=1)
    assert result.response_type == "strengths" and result.strengths
    assert result.practice is None and result.cue is None
    assert all(item.evidence_ids for item in result.strengths)
    assert not result.memory_update


def test_phase_two_strengths_without_evidence(phase_two):
    result = phase_two("What am I doing well?", [])
    assert not result.strengths and not result.practice
    assert "does not establish" in result.message


def test_phase_two_unverified_focus_does_not_drive_priority(phase_two):
    shots = [synthetic_shot()]
    focus = fixture_focus(shots)
    memory = {**empty_memory(), "recommendations": [focus]}
    assert phase_two("What should I practice?", shots, memory).focus == "Shooting consistency"
    _, current, _, _ = scenario_input("pattern")
    focus = {**focus, "knowledge_id": "arm", "title": "Shooting arm"}
    memory["recommendations"] = [focus]
    assert phase_two("What should I practice?", current, memory).focus == "Knee bend"


def test_phase_two_failed_practice_not_repeated(phase_two):
    _, shots, _, _ = scenario_input("pattern")
    focus = fixture_focus(shots)
    memory = {**empty_memory(), "recommendations": [focus], "reports": [
        {"focus_id": focus["id"], "kind": "did_not_help", "text": "It did not help."}]}
    result = phase_two("What should I practice?", shots, memory)
    assert result.focus != "Knee bend"
    assert result.guidance_basis == "general"
    reassess = phase_two("Your advice did not help.", shots, memory)
    assert reassess.response_type == "reassess" and reassess.practice is None
    memory["goal"] = "Improve knee bend"
    retry = phase_two("What should I practice?", shots, memory)
    assert retry.practice is None and retry.clarification


def test_phase_two_personal_focus_is_labelled_and_grounded(monkeypatch):
    player = uuid4().hex
    _, shots, _, _ = scenario_input("pattern")
    from dataclasses import replace
    shots = [replace(shot, player=player) for shot in shots]
    monkeypatch.setattr("backend.app.agent.retrieval.load_shots", lambda _: shots)
    monkeypatch.setattr("backend.app.agent.retrieval.shot_frames", lambda *_: [])
    result = coach(player, "How can I improve my shooting?", selected=shots[0].shot_id, multimodal=False)
    focus = active_focus(read_memory(player)[1])
    assert focus["verified_personal_correction"] is False
    assert focus["guidance_basis"] == "personal_pattern"
    assert focus["evidence_ids"] == result.provenance["supporting_evidence_ids"]


def test_openai_authorship_and_repair_provenance(phase_two):
    valid = {"message": "Your most useful next step is a comfortable routine."}
    result = phase_two("How can I improve my shooting?", client=MockOpenAI([valid]))
    assert result.provenance["source"] == "openai_authored"
    repaired = phase_two("How can I improve my shooting?", client=MockOpenAI(["bad JSON", valid]))
    assert repaired.provenance["source"] == "openai_repaired"
    assert repaired.provenance["wording"] == "model_authored"
    assert repaired.provenance["validation_failures"] == ["schema_validation_failed"]
    fallback = phase_two("How can I improve my shooting?", client=MockOpenAI(["bad JSON", "bad JSON"]))
    assert fallback.provenance["reason"] == "model_response_failed_validation"


def test_openai_can_prioritize_preserving_form_despite_a_server_pattern(phase_two):
    _, shots, _, _ = scenario_input("pattern")
    answer = {"message": "I would keep your comfortable form and collect more comparable attempts before changing it."}
    client = MockOpenAI([answer])
    result = phase_two("How can I improve my shooting?", shots, client=client)
    packet = json.loads(client.calls[0]["inputs"][0]["content"][0]["text"])
    assert any(key.startswith("pattern:min_knee_angle:") for key in packet["evidence"])
    assert "coaching_priority" not in packet and "selected_drill" not in packet
    assert result.message == answer["message"] and result.practice is None
    assert result.provenance["source"] == "openai_authored"


def test_phase_two_bypass_and_provider_error_provenance(phase_two):
    class Unavailable:
        def respond(self, **kwargs):
            raise httpx.ReadTimeout("private provider details")
    pain = phase_two("My shoulder hurts.", client=Unavailable())
    assert pain.provenance["source"] == "bypassed"
    assert pain.provenance["reason"] == "pain_safety_response"
    failed = phase_two("How can I improve my shooting?", client=Unavailable())
    assert failed.provenance["reason"] == "provider_error"
    assert "private provider details" not in failed.model_dump_json()
    assert "provenance" not in coaching_agent.response_text(failed)


def test_phase_two_endpoint_exposes_separate_provenance(monkeypatch):
    from backend.app.api.coaching import CoachingRequest, ask_coaching_agent
    player = uuid4().hex
    monkeypatch.setattr("backend.app.agent.retrieval.load_shots", lambda _: [])
    result = ask_coaching_agent(CoachingRequest(player_name=player, question="How can I improve my shooting?"))
    assert result["coaching"]["provenance"]["selected_topic"] == "routine"
    assert result["coaching"]["provenance"]["source"] == "fallback"
    assert "model_not_configured" not in result["answer"]
    focus = active_focus(read_memory(player)[1])
    assert focus["verified_personal_correction"] is False
    assert focus["guidance_basis"] == "general"


def test_phase_two_debug_provenance_not_rendered_as_coaching(phase_two, monkeypatch):
    from types import SimpleNamespace
    from frontend import coaching as frontend_coaching
    result = phase_two("What am I doing well?").model_dump(mode="json")
    rendered = []
    monkeypatch.setattr(frontend_coaching, "st", SimpleNamespace(write=rendered.append, caption=rendered.append))
    frontend_coaching.render_response(result, "Fixture", "unused", "test")
    assert any("recorded makes" in text for text in rendered)
    assert not any("fallback" in text or "model_not_configured" in text for text in rendered)


def test_phase_two_multiple_explicit_topics_use_stronger_evidence(phase_two):
    _, shots, _, _ = scenario_input("pattern")
    result = phase_two("How can I improve my follow-through and knee bend?", shots)
    assert result.focus == "Knee bend" and result.guidance_basis == "personal_pattern"


def test_phase_two_openai_cannot_invent_strength(phase_two):
    invalid = {"message": "Your wrist snapped on every shot."}
    result = phase_two("What am I doing well?", client=MockOpenAI([invalid, invalid]))
    assert result.provenance["source"] == "fallback"
    assert "narrative_validation_failed" in result.provenance["validation_failures"]
    assert not result.practice


@pytest.mark.parametrize("scenario", ["consistent_high", "consistent_low", "inconsistent_high", "inconsistent_low",
                                     "multiple_priorities", "insufficient", "unreliable", "unsuccessful"])
def test_playground_scenarios_use_production_pipeline_without_media(monkeypatch, scenario):
    from evaluation.fixtures import playground_scenario
    case = playground_scenario(scenario)
    def forbidden(*args, **kwargs):
        pytest.fail("Synthetic playground must not load real player rows or decode video")
    monkeypatch.setattr("backend.app.agent.retrieval.load_shots", forbidden)
    monkeypatch.setattr("backend.app.agent.retrieval.shot_frames", forbidden)
    result = coach(case["player"], "How can I improve my shooting?", shots=case["shots"], session_id=1,
                   selected=case["shots"][0].shot_id, persist=False, multimodal=False,
                   memory_state=("", case["memory"]))
    assert not result.video_references
    assert result.session_summary["attempts"] == (2 if scenario == "insufficient" else 20)
    assert all(shot.analysis["synthetic"] for shot in case["shots"])
    assert all("SYNTHETIC" in shot_evidence(shot)["provenance"] for shot in case["shots"])
    if scenario == "unreliable":
        assert result.session_summary["reliable_form_attempts"] == 0
        assert not any(key.startswith("pattern:") for key in result.provenance["supporting_evidence_ids"])
    if scenario == "unsuccessful":
        assert result.provenance["selected_topic"] != "knees"
        assert not result.practice or result.practice.drill_id != "focused_shooting"


def test_playground_consistency_and_accuracy_are_independent():
    from evaluation.fixtures import playground_scenario
    cases = {key: playground_scenario(key) for key in (
        "consistent_high", "consistent_low", "inconsistent_high", "inconsistent_low")}
    for prefix in ("consistent", "inconsistent"):
        high, low = (cases[prefix + suffix]["shots"] for suffix in ("_high", "_low"))
        assert [shot.analysis["biomechanics"] for shot in high] == [shot.analysis["biomechanics"] for shot in low]
        assert sum(shot.outcome == "made" for shot in high) == 16
        assert sum(shot.outcome == "made" for shot in low) == 4
        assert not personal_profile(high)["likely_patterns"]
        assert not personal_profile(low)["likely_patterns"]
    def spread(key):
        values = [shot.analysis["biomechanics"]["min_knee_angle"] for shot in cases[key]["shots"]]
        return max(values) - min(values)
    assert spread("inconsistent_high") > spread("consistent_high")
    multi = personal_profile(playground_scenario("multiple_priorities")["shots"])
    assert len(multi["likely_patterns"]) >= 2


def test_playground_connectivity_diagnostics_do_not_disclose_configuration(monkeypatch):
    from evaluation.playground import connectivity_status
    monkeypatch.setenv("OPENAI_API_KEY", "a-private-placeholder-key")
    monkeypatch.setenv("HTTPS_PROXY", "socks5h://private-user:private-password@private-host:9999")
    monkeypatch.setattr("evaluation.playground.importlib.util.find_spec", lambda _: None)
    status = connectivity_status()
    assert status["readiness"] == "missing_socks_support"
    assert status["key_configured"]
    assert "private" not in json.dumps(status)
    assert "9999" not in json.dumps(status)


def test_playground_requires_separate_process():
    from evaluation.playground import initialize_runtime
    with pytest.raises(RuntimeError, match="fresh, separate Python process"):
        initialize_runtime()


def test_playground_isolated_store_live_wiring_and_streamlit(tmp_path):
    """A fresh process verifies import-time isolation and the real UI/coach path.

    Only the SDK response is deterministic here. The actual playground has no
    mock client switch and uses the production client factory unchanged.
    """
    import os
    import subprocess
    import sys
    script = r'''
import json, os
from pathlib import Path
from unittest.mock import patch
import httpx
from streamlit.testing.v1 import AppTest
from evaluation.playground import initialize_runtime
sentinel = Path(os.environ["SHOTCOACH_DB_PATH"])
sentinel.write_bytes(b"unrelated database must not be opened")
initialize_runtime()
from backend.app.database import models
from backend.app.agent.memory import read_memory
from backend.app.agent.openai_provider import OpenAIProvider
assert models.DB_PATH.resolve() != sentinel.resolve()
assert sentinel.read_bytes() == b"unrelated database must not be opened"
with models.engine.connect() as connection:
    assert connection.exec_driver_sql("SELECT COUNT(*) FROM players").scalar() == 0
    assert connection.exec_driver_sql("SELECT COUNT(*) FROM shots").scalar() == 0
app = AppTest.from_file("evaluation/playground.py").run(timeout=25)
assert not app.exception, app.exception
assert not app.get("file_uploader")
case = app.session_state["playground_case"]
player = case["player"]
next(item for item in app.selectbox if item.label == "Experience").select("beginner")
next(item for item in app.selectbox if item.label == "Hoop").select("Unavailable")
next(item for item in app.button if item.label == "Apply synthetic player context").click().run(timeout=25)
assert read_memory(player)[1]["experience"] == "beginner"
assert read_memory(player)[1]["preferences"]["practice"]["equipment"]["hoop"] is False
message = "Your synthetic session has recorded makes, but the measured features do not identify a personal correction."
outputs = iter([{"message":message, "evidence_ids":["session:1"]}])
requests = []
def respond(request):
    requests.append(json.loads(request.content))
    item = next(outputs)
    output = [] if item is None else [{"type":"message", "content":[{"type":"output_text", "text":json.dumps(item)}]}]
    return httpx.Response(200, json={"model":"mock", "output":output,
        "usage":{"input_tokens":80, "input_tokens_details":{"cached_tokens":10}, "output_tokens":25}})
os.environ["OPENAI_API_KEY"] = "test-placeholder-not-a-real-key"
client = OpenAIProvider("test-placeholder-not-a-real-key", transport=httpx.MockTransport(respond))
with patch("backend.app.agent.provider.ProviderSettings.connect", return_value=client):
    app.chat_input[0].set_value("How can I improve my shooting?").run(timeout=30)
assert not app.exception, app.exception
result = app.session_state["playground_messages"][-1]["coaching"]
assert result["provenance"]["source"] == "openai_authored"
assert result["message"] == message
assert any(message == item.value for item in app.markdown)
assert any("Debug" in item.label for item in app.expander)
assert result["provenance"]["request_usage"]["total_requests"] == 1
assert any('"request_usage"' in str(item.value) and '"cached_input_tokens"' in str(item.value) for item in app.json)
payload = json.loads(requests[0]["input"][0]["content"][0]["text"])
assert any("SYNTHETIC" in row.get("provenance", "") for row in payload["evidence"].values())
assert payload["player_context"]["experience"] == "beginner"
app.selectbox(key="playground_scenario").select("insufficient").run(timeout=25)
assert not app.exception, app.exception
assert app.session_state["playground_case"]["player"] != player
assert app.session_state["playground_messages"] == []
with models.engine.connect() as connection:
    assert all(row[0].startswith("SYNTHETIC_") for row in connection.exec_driver_sql("SELECT player FROM coaching_memory"))
assert sentinel.read_bytes() == b"unrelated database must not be opened"
print("PLAYGROUND_INTEGRATION_OK")
'''
    environment = {**os.environ, "OPENAI_API_KEY": "", "SHOTCOACH_DEBUG": "0",
                   "SHOTCOACH_DB_PATH": str(tmp_path / "untouched.db"), "PYTHONIOENCODING": "utf-8"}
    completed = subprocess.run([sys.executable, "-B", "-c", script], cwd=ROOT, env=environment,
                               capture_output=True, text=True, encoding="utf-8", timeout=100)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "PLAYGROUND_INTEGRATION_OK" in completed.stdout
