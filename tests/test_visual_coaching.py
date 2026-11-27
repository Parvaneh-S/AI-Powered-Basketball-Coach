import csv
import json
from dataclasses import replace

import cv2
import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.agent.coaching_agent import coach
from backend.app.agent.context import EvidenceContext
from backend.app.agent.evidence import ROOT
from backend.app.agent.memory import empty_memory
from backend.app.agent.retrieval import CoachingTools
from backend.app.agent.video import shot_frames
from backend.app.api.coaching import router
from backend.app.measurements.joint_angles import calculate_angle


def decode(jpeg):
    return cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)


def test_release_annotation_matches_saved_landmark_angle_and_frame_endpoint():
    tools = CoachingTools("TestPlayer", "free_throw_03")
    ref, jpg = tools.video_frames(phases=("release",), focus="elbow")[0]
    assert (ref.frame, ref.timestamp_s) == (76, 2.533)
    assert ref.annotation["angle_source"] == "saved_landmarks"
    assert ref.annotation["marks"] == ["alignment_lines", "joint_markers", "angle_arc"]
    raw = decode(tools.video_frames(phases=("release",))[0][1])
    annotated = decode(jpg)
    height, width = annotated.shape[:2]
    assert raw.shape == annotated.shape and max(height, width) <= 768
    pose = json.loads((ROOT / "outputs/free_throw_03/pose_landmarks.json").read_text())
    expected_angle = calculate_angle(*[(x * width, y * height) for x, y in (pose["76"][index]
                                                                         for index in ("12", "14", "16"))])
    assert ref.annotation["angle_deg"] == round(expected_angle, 1)
    x, y = pose["76"]["14"]
    x, y = round(x * width), round(y * height)
    patch = np.s_[y-3:y+4, x-3:x+4]
    assert np.abs(annotated[patch].astype(float) - raw[patch]).max() > 40
    assert np.array_equal(annotated[:40], raw[:40])
    application = FastAPI()
    application.include_router(router)
    client = TestClient(application)
    params = {"player_name": "TestPlayer", "shot_id": ref.shot_id, "reference_id": ref.id}
    response = client.get("/api/coach/frame", params=params)
    assert response.status_code == 200 and response.content == jpg
    assert client.get("/api/coach/frame", params={**params, "player_name": "Other player"}).status_code == 404
    assert client.get("/api/coach/frame", params={**params, "reference_id": ref.id.replace(":76:", ":77:")}).status_code == 404


def test_question_focus_selects_relevant_phases_and_displacement():
    def ask(question):
        return coach("TestPlayer", question, selected="free_throw_03", persist=False,
                     memory_state=("", empty_memory())).video_references

    elbow = ask("Show me my elbow placement.")
    assert [(ref["phase"], ref["timestamp_s"]) for ref in elbow] == [("preparation", 0.933), ("release", 2.533)]
    knees = ask("Show me my knee movement.")
    assert [ref["phase"] for ref in knees] == ["knee_dip", "knee_extension"]
    assert knees[0]["timestamp_s"] < knees[1]["timestamp_s"] <= 2.533
    assert knees[0]["annotation"]["angle_deg"] < knees[1]["annotation"]["angle_deg"]
    evidence = CoachingTools("TestPlayer", "free_throw_02").video_frames(
        phases=("knee_dip", "knee_extension"), focus="knee", from_phase="knee_dip")
    assert evidence[-1][0].annotation["from_phase"] == "knee_dip"
    finish = ask("Show me my follow-through.")
    assert [(ref["phase"], ref["timestamp_s"]) for ref in finish] == [("release", 2.533), ("follow_through", 2.733)]
    assert [ref["phase"] for ref in ask("Compare my release and follow-through in this attempt.")] == [
        "release", "follow_through",
    ]
    assert ask("What is a free throw?") == []


def test_missing_landmarks_preserve_frame_and_saved_measurement(monkeypatch):
    monkeypatch.setattr("backend.app.agent.video.stored_landmarks", lambda _: {"76": {"14": [0.4, 0.5]}})
    tools = CoachingTools("TestPlayer", "free_throw_03")
    ref, _ = tools.video_frames(phases=("release",), focus="elbow")[0]
    assert ref.annotation["marks"] == ["joint_markers"]
    monkeypatch.setattr("backend.app.agent.video.stored_landmarks", lambda _: {})
    ref, jpg = tools.video_frames(phases=("release",), focus="elbow")[0]
    assert ref.annotation["angle_deg"] == 129.0 and ref.annotation["marks"] == []
    assert jpg == tools.video_frames(phases=("release",))[0][1]


def test_matching_phases_across_sessions_and_player_labels():
    original = CoachingTools("TestPlayer", "free_throw_03").selected
    other = CoachingTools("TestPlayer", "free_throw_02").selected
    first = replace(original, session_id=201, outcome="unknown")
    second = replace(other, session_id=202, outcome="unknown")
    answer = coach("TestPlayer", "Compare elbow placement across sessions.", selected=first.shot_id,
                   session_id=first.session_id, shots=[first, second], persist=False, memory_state=("", empty_memory()))
    refs = answer.video_references
    assert [(r["phase"], r["session_id"], r["timestamp_s"]) for r in refs] == [
        ("preparation", 201, 0.933), ("preparation", 202, 0.0),
        ("release", 201, 2.533), ("release", 202, 0.833),
    ]

    def outcomes(source):
        shots = [replace(first, outcome="made", outcome_source=source),
                 replace(second, outcome="missed", outcome_source=source)]
        return coach("TestPlayer", "Show and compare elbow placement on my made and missed shots across sessions.",
                     selected=first.shot_id, shots=shots, persist=False, memory_state=("", empty_memory()))

    assert not outcomes("auto").video_references
    assert {ref["outcome"] for ref in outcomes("manual").video_references} == {"made", "missed"}


def test_same_recording_comparison_uses_attempt_csv_and_absolute_timestamps(tmp_path, monkeypatch):
    shot = CoachingTools("TestPlayer", "free_throw_03").selected
    video_id = "stitched"
    video_dir = tmp_path / "sample_videos"
    video_dir.mkdir()
    capture = cv2.VideoCapture(str(ROOT / "sample_videos/free_throw_03.mp4"))
    frames = [capture.read()[1] for _ in range(90)]
    fps = capture.get(cv2.CAP_PROP_FPS)
    capture.release()
    height, width = frames[0].shape[:2]
    writer = cv2.VideoWriter(str(video_dir / "stitched.mp4"), cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height))
    assert writer.isOpened()
    try:
        for _ in range(2):
            for frame in frames:
                writer.write(frame)
    finally:
        writer.release()

    folder = tmp_path / "outputs" / video_id
    demo = ROOT / "outputs/free_throw_03"
    with (demo / "joint_angles.csv").open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    shots = []
    for number, offset in ((1, 0), (2, 90)):
        shot_id = f"{video_id}_shot_{number}"
        analysis = {**shot.analysis, "shot_number": number, "shot_events": {
            "start_frame": 28 + offset, "release_frame": 76 + offset, "end_frame": 82 + offset}}
        shots.append(replace(shot, shot_id=shot_id, video_id=video_id, analysis=analysis, outcome="unknown"))
        attempt = folder / "attempts" / shot_id
        attempt.mkdir(parents=True)
        with (attempt / "joint_angles.csv").open("w", newline="") as stream:
            csv_writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            csv_writer.writeheader()
            csv_writer.writerows(
                row | {"frame": frame + offset, "timestamp_ms": round((frame + offset) * 1000 / fps)}
                for frame, row in enumerate(rows[28:83], 28)
            )
    monkeypatch.setattr("backend.app.agent.retrieval.shot_frames",
                        lambda shot, phases, **options: shot_frames(shot, phases, root=tmp_path, **options))
    context = EvidenceContext("TestPlayer", "Compare attempt 1 and 2.", video_id, (), [], empty_memory(), shots=shots)
    context.collect(prepare_examples=False)
    response = context.retrieve_frames(shots[0].shot_id, "release,landing", second_shot_id=shots[1].shot_id)
    refs = response["frames"]
    assert [(r["shot_number"], r["phase"], r["frame"], r["timestamp_s"]) for r in refs] == [
        (1, "release", 76, pytest.approx(2.533)), (2, "release", 166, pytest.approx(5.533)),
    ]
    assert context.retrieve_frames(shots[0].shot_id, "release", second_shot_id="other_player")["frames"] == []
