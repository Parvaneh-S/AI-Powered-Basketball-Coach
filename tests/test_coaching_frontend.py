from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import requests
import pytest
from fastapi.testclient import TestClient
from streamlit.testing.v1 import AppTest

from backend.app.api.main import app


@pytest.fixture
def streamlit_app(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    client = TestClient(app)

    def send(method, url, **kwargs):
        kwargs.pop("timeout", None)
        api_response = client.request(method, urlsplit(url).path, **kwargs)
        response = requests.Response()
        response.status_code = api_response.status_code
        response.headers.update(api_response.headers)
        response._content = api_response.content
        response.url = url
        return response

    monkeypatch.setattr(requests, "request", send)
    monkeypatch.setattr(requests, "get", lambda url, **kwargs: send("GET", url, **kwargs))
    monkeypatch.setattr(requests, "post", lambda url, **kwargs: send("POST", url, **kwargs))
    monkeypatch.setattr(requests, "patch", lambda url, **kwargs: send("PATCH", url, **kwargs))

    frontend = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "frontend" / "app.py"))
    return frontend, client


def test_session_pages_accept_legacy_session_payload(streamlit_app, monkeypatch):
    from backend.app.api import main

    list_player_sessions = main.list_player_sessions

    def legacy_sessions(player):
        fields = ("session_id", "date", "is_today", "shot_count")
        return [{field: item[field] for field in fields} for item in list_player_sessions(player)]

    monkeypatch.setattr(main, "list_player_sessions", legacy_sessions)
    frontend, _ = streamlit_app
    frontend.run(timeout=20)
    assert not frontend.exception
    assert any("attempt" in caption.value and "Outcome counts unavailable" in caption.value
               for caption in frontend.caption)

    frontend.button(key="nav_sessions").click().run(timeout=20)
    assert not frontend.exception
    assert any(button.label.startswith("Open Practice session") for button in frontend.button)

    frontend.button(key="nav_progress").click().run(timeout=20)
    assert not frontend.exception
    history = frontend.dataframe[0].value
    assert history["Attempts"].sum() > 0
    assert history[["Makes", "Misses", "Unknown"]].isna().all().all()
    assert history["Accuracy"].eq("Unavailable").all()


def test_streamlit_coach_video_and_player_switch(streamlit_app):
    frontend, client = streamlit_app
    frontend.run(timeout=20)
    assert not frontend.exception
    assert not frontend.chat_input
    frontend.button(key="nav_sessions").click().run(timeout=20)
    recording = client.get("/api/players/TestPlayer/recordings/free_throw_03").json()
    frontend.button(key=f"all_{recording['session_id']}").click().run(timeout=20)
    assert not frontend.exception
    assert frontend.get("video")
    next(button for button in frontend.button if button.label == "Discuss with AI coach").click().run(timeout=20)
    assert not frontend.exception
    assert len(frontend.chat_input) == 1
    assert not any(panel.label.startswith("My Practice Plan") for panel in frontend.expander)
    assert not {"My shooting goal", "My basketball experience"} & {widget.label for widget in frontend.text_input}
    assert "Save goal and experience" not in {button.label for button in frontend.button}
    frontend.chat_input[0].set_value("Show me my follow through.").run(timeout=20)
    assert not frontend.exception
    assert len(frontend.chat_message) == 2
    captions = [element.value for element in frontend.caption]
    assert any("Estimated release" in caption and "2.533 s" in caption for caption in captions)
    assert any("Early follow-through" in caption and "2.733 s" in caption for caption in captions)
    assert len(frontend.image) >= 2
    play = next(toggle for toggle in frontend.toggle if toggle.label == "Play from this moment")
    play.set_value(True).run(timeout=20)
    assert not frontend.exception
    assert any("#t=2.533" in element.proto.body for element in frontend.get("html"))

    frontend.chat_input[0].set_value("Show me my follow-through and recommend a video for the finish.").run(timeout=20)
    assert not frontend.exception
    assert len(frontend.image) >= 4
    assert any("Form Shooting-2 Hands" in element.value and "jr.nba.com/video/form-shooting-2-hands/" in element.value
               for element in frontend.markdown)
    assert any("Instructional video · Jr. NBA · Dale Ellis" in element.value for element in frontend.caption)

    frontend.chat_input[0].set_value("What should I practice today?").run(timeout=20)
    assert not frontend.exception
    assert any(element.value == ":material/assignment: Recommended practice" for element in frontend.caption)
    assert "Mark practice complete" not in {button.label for button in frontend.button}
    next(button for button in frontend.button if button.label == "Open My Practice Plan").click().run(timeout=20)
    assert not frontend.exception
    assert frontend.chat_input and frontend.chat_message
    assert "Mark practice complete" in {button.label for button in frontend.button}
    saved_focus = client.get("/api/coach/memory", params={"player_name": "TestPlayer"}).json()["focus"]
    assert any(element.value == f"**{saved_focus['exercise']}**" for element in frontend.markdown)

    # Practice feedback goes through the existing coaching-memory endpoint.
    frontend.text_area[0].set_value("Hard to keep my elbow in.")
    frontend.button(key=f"practice_save_{saved_focus['id']}").click().run(timeout=20)
    assert any("Choose how the practice went" in element.value for element in frontend.error)
    frontend.button(key=f"practice_complete_{saved_focus['id']}").click().run(timeout=20)
    assert not frontend.exception
    reports = client.get("/api/coach/memory", params={"player_name": "TestPlayer"}).json()["reports"]
    assert {"focus_id": saved_focus["id"], "kind": "completed"}.items() <= reports[-1].items()
    assert "Mark practice complete" not in {button.label for button in frontend.button}

    player_widget = next(widget for widget in frontend.text_input if widget.label == "Player name")
    player_widget.set_value("Another player").run(timeout=20)
    assert not frontend.exception
    assert frontend.session_state["messages"] == []
    assert frontend.session_state["coach_session"] is None
    assert "recording" not in frontend.query_params
    assert not any(panel.label.startswith("My Practice Plan") for panel in frontend.expander)
    assert client.get("/api/coach/memory", params={"player_name": "Another player"}).json()["focus"] is None
    assert len(frontend.chat_input) == 1
    assert not frontend.chat_message
    player_widget = next(widget for widget in frontend.text_input if widget.label == "Player name")
    player_widget.set_value("TestPlayer").run(timeout=20)
    assert not frontend.exception
    assert client.get("/api/coach/memory", params={"player_name": "TestPlayer"}).json()["focus"] == saved_focus


def test_load_multi_attempt_recording_and_coach_without_manual_comparison(streamlit_app, monkeypatch):
    import cv2
    import numpy as np

    from backend.app.agent.video import FrameReference
    from backend.app.database.recordings import save_recording

    success, image = cv2.imencode(".jpg", np.zeros((32, 32, 3), dtype=np.uint8))
    assert success

    def fixture_frames(shot, phases):
        phase = "knee_dip"
        if phase not in (phases or ()):
            return []
        frame = shot.analysis["shot_events"]["start_frame"] + 1
        return [(FrameReference(f"frame:{shot.shot_id}:{phase}:{frame}", shot.video_id,
                                shot.shot_id, frame, frame / 10, phase, "estimated", "synthetic",
                                shot.shot_number, shot.session_id), image.tobytes())]

    monkeypatch.setattr("backend.app.agent.retrieval.shot_frames", fixture_frames)
    frontend, client = streamlit_app
    player = "session_ui_" + uuid4().hex
    video = "ui_video_" + uuid4().hex
    analyses = []
    for index, outcome in enumerate(["made"] * 10 + ["missed"] * 8 + ["unknown"] * 2, 1):
        start = index * 30
        analyses.append({
            "video_id": video, "shot_id": f"{video}_shot_{index}", "shot_number": index,
            "shot_type": "free_throw", "shot_outcome": {"prediction": outcome},
            "shot_events": {"start_frame": start, "release_frame": start + 5, "end_frame": start + 7,
                            "start_time_ms": start * 100, "release_time_ms": (start + 5) * 100,
                            "end_time_ms": (start + 7) * 100},
            "biomechanics": {"shooting_arm": "right", "knee_coverage_pct": 100,
                             "min_knee_angle": (90 if outcome == "made" else 130) + index},
        })
    session_id = save_recording(video, player, None, uuid4().hex, "session.mp4", analyses, {})
    frontend.run(timeout=20)
    next(widget for widget in frontend.text_input if widget.label == "Player name").set_value(player).run(timeout=20)
    frontend.button(key="nav_sessions").click().run(timeout=20)
    frontend.button(key=f"all_{session_id}").click().run(timeout=20)
    assert not frontend.exception
    assert any(metric.label == "Detected attempts" and metric.value == "20" for metric in frontend.metric)
    assert "Attempt details" in {panel.label for panel in frontend.expander}
    next(button for button in frontend.button if button.label == "Discuss with AI coach").click().run(timeout=20)
    frontend.chat_input[0].set_value("How did I do this session?").run(timeout=20)
    assert not frontend.exception
    assert len(frontend.chat_message) == 2
    assistant = frontend.session_state["messages"][-1]["coaching"]
    assert assistant["session_summary"]["session_id"] == session_id
    assert assistant["session_summary"]["accuracy_pct"] == 55.6
    assert assistant["session_summary"]["unknown"] == 2
    assert len(frontend.image) == 2
    assert {ref["outcome"] for ref in assistant["video_references"]} == {"made", "missed"}
    assert any("appears more bent" in element.value for element in frontend.markdown)
    assert "Supporting coaching sources" in {panel.label for panel in frontend.expander}
    assert {ref["video_id"] for ref in assistant["video_references"]} == {video}
    assert client.get(f"/api/players/{player}/recordings/{video}").json()["summary"]["attempts"] == 20

    frontend.button(key="nav_progress").click().run(timeout=20)
    assert not frontend.chat_input
    assert frontend.dataframe[0].value.iloc[0].to_dict() == {
        "Session": f"Practice session {session_id}",
        "Date": client.get(f"/api/players/{player}/sessions").json()[0]["date"],
        "Attempts": 20, "Makes": 10, "Misses": 8, "Unknown": 2, "Accuracy": "55.6%",
    }
    frontend.button(key="nav_coach").click().run(timeout=20)
    assert len(frontend.chat_message) == 2
    assert frontend.query_params["session"] == str(session_id)
    attempt = next(widget for widget in frontend.selectbox if widget.label == "Attempt")
    attempt.select(f"{video}_shot_2").run(timeout=20)
    assert frontend.query_params["attempt"] == f"{video}_shot_2"
    assert len(frontend.chat_message) == 2
    context = next(widget for widget in frontend.selectbox if widget.label == "Recording")
    context.select("").run(timeout=20)
    assert frontend.query_params["session"] == str(session_id)
    assert "recording" not in frontend.query_params
    assert "attempt" not in frontend.query_params
    next(widget for widget in frontend.selectbox if widget.label == "Session").select(0).run(timeout=20)
    assert "session" not in frontend.query_params
    assert len(frontend.chat_message) == 2


def test_upload_preview_and_named_session_redirect(streamlit_app, monkeypatch):
    from backend.app.database.recordings import save_recording
    from backend.app.pipeline import video_pipeline

    def analyze(path, player, arm, filename, session_id, session_name, *, progress):
        assert Path(path).read_bytes() == b"test upload"
        assert arm == "left"
        assert session_name == "Wednesday practice"
        assert session_id is None
        progress("Detecting the basketball", 10, 20)
        video_id = "upload_ui_" + uuid4().hex
        saved_id = save_recording(video_id, player, session_id, uuid4().hex, filename,
                                  [], {}, session_name=session_name)
        return {"session_id": saved_id, "video_id": video_id}

    monkeypatch.setattr(video_pipeline, "process_uploaded_video", analyze)
    frontend, client = streamlit_app
    frontend.run(timeout=20)
    player = "Upload " + uuid4().hex
    frontend.text_input(key="player_selector").set_value(player).run(timeout=20)
    next(button for button in frontend.button if button.label == "Upload video").click().run(timeout=20)
    assert frontend.title[0].value == "New practice recording"
    next(button for button in frontend.button if button.label == "Analyze recording").click().run(timeout=20)
    assert frontend.warning[0].value == "Select a video to analyze."

    frontend.file_uploader[0].set_value(("practice.mp4", b"test upload", "video/mp4")).run(timeout=20)
    assert frontend.get("video")
    next(widget for widget in frontend.text_input if widget.label.startswith("Session name")).set_value(
        " Wednesday practice "
    )
    next(widget for widget in frontend.selectbox if widget.label == "Shooting arm").select("left")
    next(button for button in frontend.button if button.label == "Analyze recording").click().run(timeout=20)
    assert not frontend.exception
    assert frontend.title[0].value == "Wednesday practice"
    assert frontend.query_params["page"] == "session"
    assert any(message.value == "Recording analyzed and saved." for message in frontend.success)
    assert any("No shooting attempts" in item.value for item in frontend.info)
    sessions = client.get(f"/api/players/{player}/sessions").json()
    assert len(sessions) == 1 and sessions[0]["name"] == "Wednesday practice"
    assert sessions[0]["accuracy_pct"] is None


def test_recording_video_supports_ranges_and_player_scoping(streamlit_app):
    _, client = streamlit_app
    url = "/api/players/TestPlayer/recordings/free_throw_03/video"
    response = client.get(url, headers={"Range": "bytes=0-31"})
    assert response.status_code == 206
    assert response.headers["content-type"] == "video/mp4"
    assert len(response.content) == 32
    assert client.get(url.replace("TestPlayer", "Other")).status_code == 404


def test_separate_clip_upload_opens_session_in_coaching_ui(streamlit_app, monkeypatch):
    from backend.app.api import main
    from backend.app.database.recordings import save_recording

    def analyze(path, player, arm, filename, session_id, progress, *, session_name):
        assert Path(path).read_bytes() == b"practice video"
        assert session_name == "Clip practice"
        video_id = "clip_" + uuid4().hex
        progress("Analyzing the practice video", 1, 2)
        session_id = save_recording(video_id, player, session_id, uuid4().hex, filename,
                                    [], {}, session_name=session_name)
        return {"session_id": session_id, "shots_analysed": 1, "shots_found": 2, "shots": [
            {"video_id": video_id, "status": "success"},
            {"status": "failed", "error": "Ball not found"},
        ]}

    monkeypatch.setattr(main, "process_multi_shot_video", analyze)
    monkeypatch.setattr(main, "start_job_thread", main.run_multi_shot_job)
    frontend, _ = streamlit_app
    frontend.run(timeout=20)
    frontend.text_input(key="player_selector").set_value("Clip " + uuid4().hex).run(timeout=20)
    next(button for button in frontend.button if button.label == "Upload video").click().run(timeout=20)
    frontend.file_uploader[0].set_value(("practice.mp4", b"practice video", "video/mp4"))
    frontend.radio[0].set_value("multi")
    next(widget for widget in frontend.text_input if widget.label.startswith("Session name")).set_value("Clip practice")
    next(button for button in frontend.button if button.label == "Analyze recording").click().run(timeout=20)
    assert not frontend.exception
    assert frontend.title[0].value == "Clip practice"
    assert "job" not in frontend.query_params
    assert any("1 of 2 shot clips analyzed" in caption.value for caption in frontend.caption)
    next(button for button in frontend.button if button.label == "Discuss with AI coach").click().run(timeout=20)
    assert not frontend.exception
    assert frontend.chat_input


def test_resource_cards_show_title_creator_note_and_direct_link():
    from streamlit.testing.v1 import AppTest

    def page():
        from frontend.coaching import render_response
        base = {"kind": "video", "organization": "Jr. NBA", "verified_on": "2026-11-26", "exercise": None,
                "section": None, "thumbnail_url": None, "embed_url": None}
        first = {**base, "id": "a", "title": "Form Shooting-2 Hands", "creator": "Dale Ellis",
                 "url": "https://jr.nba.com/video/form-shooting-2-hands/",
                 "watch_for": "Legs and arm extend through the finish.",
                 "relevance": "Watch how the knees and shooting arm extend together."}
        second = {**base, "id": "b", "title": "Fundamentals of the Free Throw", "creator": "Megan Griffith",
                  "url": "https://jr.nba.com/video/fundamentals-of-the-free-throw/",
                  "watch_for": "A repeatable pre-shot sequence.", "relevance": ""}
        before = {"made": 5, "missed": 5, "manual_made": 5, "manual_labels": 10, "unknown": 0,
                  "mean": 124.5, "spread": 5, "measurement_count": 10, "session_name": "First practice"}
        after = {**before, "made": 7, "missed": 3, "manual_made": 7, "spread": 2, "session_name": "Latest practice"}
        render_response({"message": "Compare the saved sets.", "instructional_resource": first,
                         "additional_resources": [second, first], "progress": {
                             "status": "available", "kind": "sessions", "before": before, "after": after,
                             "field": "release_elbow_angle", "completed": True, "player_reported_effect": "helped",
                             "assessment": {"accuracy": "higher", "consistency": "higher"},
                         }}, "Tester", "", "fixture")

    app = AppTest.from_function(page).run(timeout=20)
    assert not app.exception
    markdown = [element.value for element in app.markdown]
    assert "[**Form Shooting-2 Hands**](https://jr.nba.com/video/form-shooting-2-hands/)" in markdown
    assert any(value.startswith("**What to watch for:** Watch how the knees") for value in markdown)
    assert sum(value.startswith("**What to watch for:**") for value in markdown) == 1  # empty note shows nothing
    assert "Instructional video · Jr. NBA · Dale Ellis" in [element.value for element in app.caption]
    buttons = app.get("link_button")
    assert [button.proto.url for button in buttons] == [
        "https://jr.nba.com/video/form-shooting-2-hands/", "https://jr.nba.com/video/fundamentals-of-the-free-throw/"]
    assert all(button.proto.label == "Watch video" for button in buttons)
    assert {"**First practice**", "**Latest practice**", "**Measured progress**", "**Player-reported**"} <= set(markdown)
    captions = {element.value for element in app.caption}
    assert {"Movement repeatability · Higher", "Player said the practice helped."} <= captions


def test_coach_tools_empty_states_and_ask_error(streamlit_app, monkeypatch):
    from frontend import service

    frontend, _ = streamlit_app
    frontend.query_params["page"] = "coach"
    frontend.run(timeout=20)
    player = "tabs_ui_" + uuid4().hex
    next(widget for widget in frontend.text_input if widget.label == "Player name").set_value(player).run(timeout=20)
    assert not frontend.exception
    assert any(element.value == "### Let’s work on your shot." for element in frontend.markdown)
    assert {"Analyze my shooting form", "Why am I missing shots?", "How am I improving?",
            "What should I practice?"} <= {button.label for button in frontend.button}

    def unavailable(*args, **kwargs):
        raise requests.ConnectionError("offline")

    monkeypatch.setattr(service.requests, "post", unavailable)
    frontend.button(key="suggest_How am I improving?").click().run(timeout=20)
    assert not frontend.exception
    assert any("couldn’t answer" in element.value for element in frontend.error)
    assert "Try again" in {button.label for button in frontend.button}
    assert frontend.session_state["messages"] == []

    assert not any(panel.label.startswith("My Practice Plan") for panel in frontend.expander)
    frontend.button(key="open_progress").click().run(timeout=20)
    assert any(element.value == "### No progress to show yet" for element in frontend.markdown)
    assert frontend.chat_input
    frontend.button(key="open_practice").click().run(timeout=20)
    assert any(element.value == "No practice plan yet." for element in frontend.caption)
    assert "Ask what to practise" in {button.label for button in frontend.button}
    assert frontend.chat_input
