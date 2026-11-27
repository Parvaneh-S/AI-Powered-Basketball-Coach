"""Synthetic 20-attempt integration fixture and session coaching regressions."""

import json
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import cv2
import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from backend.app.agent.coaching_agent import coach
from backend.app.agent.evidence import load_shots
from backend.app.agent.memory import empty_memory
from backend.app.agent.profile import personal_profile
from backend.app.agent.progress import assess_progress
from backend.app.agent.retrieval import CoachingTools
from backend.app.agent.session_analysis import representative_pair, summarize_session
from backend.app.agent.video import FrameReference, shot_frames
from backend.app.api.main import app
from backend.app.database.duplicates import DuplicateVideoError
from backend.app.database.recordings import save_recording
from backend.app.pipeline.analyze_recording import analyze_attempts
from backend.app.shot_detection.session_segment import segment_attempts
from evaluation.fixtures import synthetic_shot


def recording_tables(outcomes=("made",)):
    angles, detections = [], []
    for i, outcome in enumerate(outcomes):
        base = i * 110
        for j in range(110):
            frame = base + j
            elbow = 80 + min(80, max(0, (j - 18) * 8))
            if j in (31, 32, 33):
                elbow -= 25  # A second local motion cue near the same release.
            angles.append({"frame": frame, "timestamp_ms": frame * 33,
                           "right_elbow_angle": elbow, "right_knee_angle": 145 - max(0, 16 - abs(j - 17) * 2) - i,
                           "right_wrist_x": 50, "right_wrist_y": 112})
        if outcome == "motion_only":
            continue
        x_rim = 140 if outcome == "missed" else 110
        positions = [(j, 50, 112 - (j - 18) * 2) for j in range(18, 24)]
        positions += [(j, 55 + (x_rim - 55) * (j - 24) / 19, 96 - (j - 24) * 2.5)
                      for j in range(24, 44)]
        if outcome != "unknown":
            positions.extend([(44, x_rim, 52), (45, x_rim, 57), (51, x_rim, 74), (52, x_rim, 80)])
        for j, x, y in positions:
            frame = base + j
            detections.append({"frame": frame, "timestamp_ms": frame * 33, "center_x": x, "center_y": y,
                               "x1": x - 5, "x2": x + 5, "y1": y - 5, "y2": y + 5, "confidence": .9})
    return pd.DataFrame(angles), pd.DataFrame(detections, columns=[
        "frame", "timestamp_ms", "center_x", "center_y", "x1", "x2", "y1", "y2", "confidence",
    ])


def write_tables(root, outcomes, with_hoop=True):
    angles, balls = recording_tables(outcomes)
    angles.to_csv(root / "joint_angles.csv", index=False)
    balls.to_csv(root / "ball_detections.csv", index=False)
    if with_hoop:
        (root / "hoop_detection.json").write_text(json.dumps({
            "rim_bbox": [100, 60, 120, 70], "rim_center": [110, 65],
        }), encoding="utf-8")
    return angles, balls


def test_segment_one_shot_and_leave_unconfirmed_motion_for_review():
    angles, balls = recording_tables(("made", "motion_only", "missed"))
    attempts, reviews = segment_attempts(angles, balls, "right")
    assert len(attempts) == 2
    assert all(start <= attempt.events["release_frame"] <= start + 27
               for start, attempt in zip((22, 242), attempts))
    assert any(review["reason"] == "release_not_corroborated" for review in reviews)
    cut = angles[angles.frame < 26]
    attempts, reviews = segment_attempts(cut, balls, "right")
    assert attempts == []
    one, _ = segment_attempts(*recording_tables(), "right")
    assert len(one) == 1


def test_twenty_attempts_keep_absolute_timestamps_form_and_outcomes_separate(tmp_path):
    outcomes = ("made", "missed", "unknown", "made") * 5
    write_tables(tmp_path, outcomes)
    shots, processing, trajectory = analyze_attempts("synthetic_recording", tmp_path, "right")
    assert processing["attempt_count"] == 20
    assert [shot["shot_outcome"]["prediction"] for shot in shots] == list(outcomes)
    assert [shot["shot_number"] for shot in shots] == list(range(1, 21))
    assert len({shot["shot_id"] for shot in shots}) == 20
    previous_end, previous_flight_end = -1, -1
    for shot in shots:
        events = shot["shot_events"]
        # Measurement windows never overlap; a ball may still be in
        # flight while the next preparation starts, but not past
        # the next release.
        assert previous_end < events["start_frame"] < events["release_frame"] < events["end_frame"]
        assert previous_flight_end < events["release_frame"]
        assert events["release_time_ms"] == events["release_frame"] * 33
        assert shot["biomechanics"]["min_knee_angle"] == 129 - (shot["shot_number"] - 1)
        previous_end, previous_flight_end = events["end_frame"], events["flight_end_frame"]
    assert trajectory.frame.is_unique


def test_missing_hoop_keeps_attempt_and_outcome_unknown(tmp_path):
    write_tables(tmp_path, ("made",), with_hoop=False)
    shots, processing, _ = analyze_attempts("no_rim", tmp_path, "right")
    assert processing["attempt_count"] == 1 and processing["hoop_available"] is False
    assert shots[0]["shot_outcome"]["prediction"] == "unknown"


def evidence_set(player="Fixture", session_id=1, mixed=True):
    shots = []
    for i in range(1, 21):
        outcome = ("made" if i <= 10 else "missed" if i <= 18 else "unknown") if mixed else "made"
        knee = 92 + i if outcome == "made" else 136 + i
        shot = synthetic_shot(i, player=player, outcome=outcome, knee=knee, session_id=session_id)
        shot.analysis["shot_number"] = i
        shots.append(replace(shot, video_id="session_recording"))
    return shots


def decoded_frames(shot, phases):
    return [(FrameReference(f"frame:{shot.shot_id}:{phase}:20",
                            shot.video_id, shot.shot_id, 20, 0.66, phase, "estimated", "synthetic",
                            shot.shot_number, shot.session_id), b"fixture")
            for phase in phases or ("preparation", "release")]


def test_session_summary_and_representative_median_pair(monkeypatch):
    shots = evidence_set()
    summary = summarize_session(shots)
    assert (summary["made"], summary["missed"], summary["unknown"]) == (10, 8, 2)
    assert summary["accuracy_pct"] == 55.6 and summary["outcome_coverage_pct"] == 90
    assert summary["reliable_form_attempts"] == 20
    profile = personal_profile(shots)
    assert "min_knee_angle" in profile["likely_patterns"]
    tools = CoachingTools("Fixture", session_id=1, shots=shots)
    monkeypatch.setattr("backend.app.agent.retrieval.shot_frames", decoded_frames)
    pair, images = representative_pair(tools, profile, "min_knee_angle")
    assert pair["first"]["shot_number"] in (5, 6)
    assert pair["second"]["shot_number"] in (14, 15)
    assert {item.phase for item, _ in images} == {"knee_dip"}
    assert {item.video_id for item, _ in images} == {"session_recording"}
    assert tools.session_attempts("missed")["total"] == 8
    assert tools.session_attempts(offset=19)["attempts"][0]["shot_number"] == 20


@pytest.mark.parametrize("outcome", ["made", "missed", "unknown"])
def test_single_outcome_sessions_do_not_force_a_comparison(monkeypatch, outcome):
    shots = [replace(shot, outcome=outcome) for shot in evidence_set()]
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("backend.app.agent.retrieval.load_shots", lambda _: shots)
    result = coach("Fixture", "Compare makes and misses", selected="session_recording",
                   persist=False, memory_state=("", empty_memory()))
    assert not result.video_references
    assert result.session_summary["attempts"] == 20
    assert result.session_summary["accuracy_pct"] == {"made": 100, "missed": 0, "unknown": None}[outcome]


def test_session_coaching_uses_owned_representative_visuals(monkeypatch):
    player = "Fixture"
    shots = evidence_set()
    foreign = replace(shots[0], player="Other", session_id=999)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("backend.app.agent.retrieval.load_shots", lambda _: shots + [foreign])
    monkeypatch.setattr("backend.app.agent.retrieval.shot_frames", decoded_frames)
    result = coach(player, "What should I practice for knee bend?", selected="session_recording",
                   persist=False, memory_state=("", empty_memory()))
    assert result.session_summary["attempts"] == 20
    assert result.focus == "Knee bend"
    assert result.observations[0].video_reference_ids
    assert {ref["session_id"] for ref in result.video_references} == {1}
    assert {ref["outcome"] for ref in result.video_references} == {"made", "missed"}


def test_recording_api_isolates_sessions_and_preserves_attempts(tmp_path, monkeypatch):
    player = uuid4().hex
    write_tables(tmp_path, ("made", "missed", "unknown"))
    analyses, processing, _ = analyze_attempts(player, tmp_path, "right")
    session = save_recording(player, player, None, player, "fixture.mp4", analyses, processing)
    with pytest.raises(DuplicateVideoError):
        save_recording("duplicated", player, session, player, "same.mp4", [], processing)
    assert len(load_shots(player)) == 3
    client = TestClient(app)
    assert client.get(f"/api/players/{player}/recordings").json()[0]["shot_count"] == 3
    data = client.get(f"/api/players/{player}/recordings/{player}").json()
    assert data["summary"]["accuracy_pct"] == 50
    assert data["summary"]["outcome_coverage_pct"] == 66.7
    assert client.get(f"/api/players/Other/recordings/{player}").status_code == 404
    assert client.get(f"/api/players/Other/sessions/{session}/summary").status_code == 404
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    for owner in (player, "Other"):
        response = client.post("/api/coach/ask", json={"player_name": owner,
                              "question": "How did I do?", "session_id": session, "selected_shot_id": player})
        assert response.status_code == 200
        assert bool(response.json()["coaching"]["session_summary"]) == (owner == player)


def test_poor_form_keeps_outcomes_and_representative_requires_decodable_frames(monkeypatch):
    shots = evidence_set()
    for shot in shots:
        shot.analysis["biomechanics"] = {}
    summary = summarize_session(shots)
    assert summary["reliable_form_attempts"] == 0
    assert summary["accuracy_pct"] == 55.6
    shots = evidence_set()
    monkeypatch.setattr("backend.app.agent.retrieval.shot_frames", lambda *_: [])
    assert representative_pair(CoachingTools("Fixture", session_id=1, shots=shots),
                               personal_profile(shots), "min_knee_angle") is None


def test_frame_reference_uses_attempt_timestamps_and_rejects_wrong_window(tmp_path):
    recording = "video"
    folder = tmp_path / "outputs" / recording
    folder.mkdir(parents=True)
    video_dir = tmp_path / "sample_videos"
    video_dir.mkdir()
    writer = cv2.VideoWriter(str(video_dir / "video.mp4"), cv2.VideoWriter_fourcc(*"mp4v"), 10, (32, 32))
    assert writer.isOpened()
    for i in range(12):
        writer.write(np.full((32, 32, 3), i * 16, dtype=np.uint8))
    writer.release()
    for index, start in ((1, 1), (2, 7)):
        shot = replace(synthetic_shot(index), video_id=recording)
        shot.analysis["shot_number"] = index
        shot.analysis["shot_events"].update(start_frame=start, release_frame=start + 1, end_frame=start + 2,
                                            measurement_frames={"knee_dip": 1})
        per_attempt = folder / "attempts" / shot.shot_id
        per_attempt.mkdir(parents=True)
        (per_attempt / "joint_angles.csv").write_text("frame,timestamp_ms\n" + "".join(
            f"{i},{i * 100}\n" for i in range(start, start + 3)
        ), encoding="utf-8")
        [(reference, jpg)] = shot_frames(shot, ("release",), root=tmp_path)
        assert reference.timestamp_s == (start + 1) / 10
        assert reference.shot_number == index
        assert jpg[:2] == b"\xff\xd8"
        if index == 2:
            assert shot_frames(shot, ("knee_dip",), root=tmp_path) == []


def test_session_progress_compares_one_compatible_later_session():
    baseline = evidence_set()
    later = [replace(shot, row_id=shot.row_id + 20, shot_id=f"later_{shot.shot_id}")
             for shot in evidence_set(session_id=2)]
    different = synthetic_shot(90, session_id=3, arm="left")
    same_session = replace(baseline[0], row_id=60, shot_id="late_baseline")
    focus = {"session_id": 1, "conditions": baseline[0].conditions, "last_row_id": 20,
             "baseline_shot_ids": [shot.shot_id for shot in baseline], "field": "min_knee_angle", "id": "focus"}
    progress = assess_progress(baseline + later + [different, same_session], focus, [], 2)
    assert progress["status"] == "available"
    assert progress["before_session_id"] == 1 and progress["after_session_id"] == 2
    assert progress["after"]["shot_count"] == 20
    assert progress["pattern_comparison"][0]["field"] == "min_knee_angle"
    assert assess_progress(baseline + later + [different], focus, [], 3)["status"] == "no_comparable_new_shots"
