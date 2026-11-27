"""
Tests for following the shot's ball when other balls are in
view (a previous shot still in the air, balls on the floor).
"""

import cv2
import numpy as np
import pandas as pd

from backend.app.ball_detection.ball_tracker import track_ball


FRAMES = 40
RELEASE = 10


def make_blank_video(path):
    writer = cv2.VideoWriter(
        str(path), cv2.VideoWriter_fourcc(*"mp4v"), 30, (640, 360)
    )
    for _ in range(FRAMES):
        writer.write(np.zeros((360, 640, 3), np.uint8))
    writer.release()


def test_follows_rising_ball_after_release(tmp_path):
    rows = []

    for frame in range(FRAMES):
        # Previous shot's ball, falling near the hoop,
        # with high confidence (would win the old tracker).
        if frame < 20:
            rows.append((frame, 0.95, 500.0, 60.0 + 8 * frame))

        # A ball lying still on the floor.
        rows.append((frame, 0.4, 100.0, 330.0))

        # This shot's ball: rises after release, then falls.
        if frame >= RELEASE:
            t = frame - RELEASE
            rows.append((frame, 0.7, 150.0 + 12 * t,
                         300.0 - 20 * t + 0.8 * t * t))

    detections = pd.DataFrame(
        rows, columns=["frame", "confidence", "center_x", "center_y"]
    )
    detections.to_csv(tmp_path / "ball_detections.csv", index=False)

    video = tmp_path / "clip.mp4"
    make_blank_video(video)

    track_ball(video, tmp_path / "ball_detections.csv", tmp_path,
               start_frame=RELEASE)

    path = pd.read_csv(tmp_path / "ball_trajectory.csv")

    assert path["frame"].min() >= RELEASE
    assert len(path) == FRAMES - RELEASE

    # Every point is the shot's ball, not the others.
    t = path["frame"] - RELEASE
    assert np.allclose(path["center_x"], 150.0 + 12 * t)


def test_without_release_frame_old_behaviour_is_kept(tmp_path):
    detections = pd.DataFrame({
        "frame": [0, 1, 2],
        "confidence": [0.9, 0.9, 0.9],
        "center_x": [100.0, 110.0, 120.0],
        "center_y": [100.0, 90.0, 80.0],
    })
    detections.to_csv(tmp_path / "ball_detections.csv", index=False)

    video = tmp_path / "clip.mp4"
    make_blank_video(video)

    track_ball(video, tmp_path / "ball_detections.csv", tmp_path)

    path = pd.read_csv(tmp_path / "ball_trajectory.csv")
    assert list(path["center_x"]) == [100.0, 110.0, 120.0]


def test_link_gap_is_measured_in_time_not_frames():
    from backend.app.ball_detection.ball_tracker import link_paths

    def points(fps):
        # One ball, unseen for 30 frames (hidden by the net).
        frames = [0, 1, 2, 33, 34]
        return pd.DataFrame({
            "frame": frames, "timestamp_ms": [round(f * 1000 / fps) for f in frames],
            "stable_x": [100.0, 105, 110, 120, 121], "stable_y": [100.0] * 5,
            "center_x": [100.0, 105, 110, 120, 121], "center_y": [100.0] * 5,
            "confidence": [0.9] * 5, "x1": 95.0, "x2": 105.0,
        })

    assert len(link_paths(points(60), max_distance=200)) == 1
    assert len(link_paths(points(30), max_distance=200)) == 2
