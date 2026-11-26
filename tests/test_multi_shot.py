"""
Tests for videos with several shots: finding the shots
(multi_shot.py) and analysing them one by one in one session
(multi_shot_pipeline.py).
"""

from uuid import uuid4

import pandas as pd
import pytest

import backend.app.pipeline.multi_shot_pipeline as pipeline
import backend.app.pipeline.video_pipeline as video_pipeline
from backend.app.pipeline.video_input import WrongUploadModeError
from backend.app.shot_detection.multi_shot import find_shots


FPS = 30


def write_signals(path, raise_starts, dips, frames=300):
    """
    Simulated pose signals: standing (knee 170 deg, hands at
    the waist), a knee dip, then the hands above the nose for
    0.5 s at each raise start.
    """

    rows = []

    for frame in range(frames):
        knee = 170.0
        for dip in dips:
            knee = min(knee, 170.0 - max(0, 40 - 4 * abs(frame - dip)))

        raised = any(s <= frame < s + 15 for s in raise_starts)
        wrist = 150.0 if raised else 500.0

        rows.append({
            "frame": frame,
            "timestamp_ms": round(frame * 1000 / FPS),
            "left_elbow_angle": 90.0,
            "right_elbow_angle": 90.0,
            "left_knee_angle": knee,
            "right_knee_angle": knee,
            "nose_y": 200.0,
            "left_wrist_y": wrist,
            "right_wrist_y": wrist,
        })

    pd.DataFrame(rows).to_csv(path, index=False)


def test_finds_each_shot_and_its_knee_dip(tmp_path):
    csv = tmp_path / "signals.csv"
    write_signals(csv, raise_starts=[60, 200], dips=[50, 190])

    shots = find_shots(csv, FPS)

    assert [s["hands_up_frame"] for s in shots] == [60, 200]
    # Smoothing flattens the bottom of the dip slightly.
    for shot, true_dip in zip(shots, [50, 190]):
        assert abs(shot["dip_frame"] - true_dip) <= 2


def test_knee_bend_without_raised_hands_is_not_a_shot(tmp_path):
    csv = tmp_path / "signals.csv"
    # Picking up the ball at frame 120: knees bend, hands stay low.
    write_signals(csv, raise_starts=[60], dips=[50, 120])

    assert len(find_shots(csv, FPS)) == 1


@pytest.fixture
def fake_steps(monkeypatch, tmp_path):
    """
    Replace the slow steps (conversion, pose, single-shot
    analysis) so only the multi-shot logic is tested.
    """

    calls = []

    def fake_find(video, work_dir, count=3):
        return work_dir / "video.mp4", FPS, [
            {"shot": n, "dip_frame": 100 * n,
             "hands_up_frame": 100 * n + 10,
             "hands_down_frame": 100 * n + 25}
            for n in range(1, count + 1)
        ]

    monkeypatch.setattr(pipeline, "find_shots_in_video", fake_find)
    monkeypatch.setattr(pipeline, "count_frames", lambda video: 1000)
    monkeypatch.setattr(pipeline, "cut_clip",
                        lambda video, destination, first, last: None)

    def fake_analysis(video_path, player_name, shooting_arm,
                      original_filename, session_id, source_sha256):
        calls.append(session_id)

        if "shot 2," in original_filename:
            raise RuntimeError("ball not found")

        return {
            "video_id": f"shot_{len(calls)}",
            "session_id": session_id or 777,
            "shot_outcome": {"prediction": "missed"},
        }

    monkeypatch.setattr(pipeline, "process_uploaded_video", fake_analysis)

    video = tmp_path / "practice.mp4"
    video.write_bytes(uuid4().bytes)  # a new fingerprint every run

    return video, calls


def test_all_shots_join_the_first_shots_session(fake_steps):
    video, calls = fake_steps

    summary = pipeline.process_multi_shot_video(video, "MultiShotTester")

    # Shot 1 starts a new session; the others join it.
    assert calls == [None, 777, 777]
    assert summary["session_id"] == 777
    assert summary["shots_found"] == 3


def test_a_failed_shot_does_not_stop_the_others(fake_steps):
    video, _ = fake_steps

    summary = pipeline.process_multi_shot_video(video, "MultiShotTester")

    assert [s["status"] for s in summary["shots"]] == [
        "success", "failed", "success",
    ]
    assert summary["shots_analysed"] == 2
    assert "ball not found" in summary["shots"][1]["error"]


def test_no_shots_found_is_reported(fake_steps, monkeypatch):
    video, _ = fake_steps
    monkeypatch.setattr(pipeline, "find_shots_in_video",
                        lambda video, work_dir: (None, FPS, []))

    with pytest.raises(pipeline.NoShotsFoundError):
        pipeline.process_multi_shot_video(video, "MultiShotTester")


def test_single_shot_video_is_refused_as_several_shots(
    fake_steps, monkeypatch
):
    video, calls = fake_steps
    monkeypatch.setattr(
        pipeline, "find_shots_in_video",
        lambda video, work_dir: (None, FPS, [
            {"shot": 1, "dip_frame": 50, "hands_up_frame": 60,
             "hands_down_frame": 75},
        ]),
    )

    with pytest.raises(WrongUploadModeError, match="One shot"):
        pipeline.process_multi_shot_video(video, "MultiShotTester")

    assert calls == []  # nothing analysed or saved


def test_several_shot_video_is_refused_as_one_shot(
    tmp_path, monkeypatch
):
    two_shots = [{"shot": 1}, {"shot": 2}]
    monkeypatch.setattr(
        video_pipeline, "find_shots_in_video",
        lambda video, work_dir: (None, FPS, two_shots),
    )

    with pytest.raises(WrongUploadModeError, match="2 shots"):
        video_pipeline.refuse_multi_shot_video(tmp_path / "v.mp4")

    # One shot, or none found: accepted.
    for shots in ([{"shot": 1}], []):
        monkeypatch.setattr(
            video_pipeline, "find_shots_in_video",
            lambda video, work_dir, s=shots: (None, FPS, s),
        )
        video_pipeline.refuse_multi_shot_video(tmp_path / "v.mp4")


def test_only_one_analysis_at_a_time():
    from fastapi import HTTPException

    from backend.app.api import main

    main.claim_analysis_slot()

    try:
        with pytest.raises(HTTPException) as refused:
            main.claim_analysis_slot()

        assert refused.value.status_code == 409
    finally:
        main.release_analysis_slot()

    # Free again once the first analysis has finished.
    main.claim_analysis_slot()
    main.release_analysis_slot()
