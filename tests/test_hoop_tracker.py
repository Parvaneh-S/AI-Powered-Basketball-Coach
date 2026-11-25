"""
Tests for following the hoop when the camera moves.
A synthetic video is made by shifting a textured picture by
known amounts, like a camera panning.
"""

import json

import cv2
import numpy as np
import pandas as pd

from backend.app.ball_detection.hoop_tracker import track_hoop
from backend.app.ball_detection.shot_outcome import analyze_outcome


WIDTH, HEIGHT, FRAMES = 640, 360, 40
RIM = [300.0, 150.0, 360.0, 180.0]


def camera_shift(frame):
    # Smooth pan: up to 60 px right and 25 px down.
    t = frame / (FRAMES - 1)
    return 60 * t, 25 * t


def make_panning_video(path):
    rng = np.random.default_rng(0)
    scene = rng.integers(0, 255, (HEIGHT + 100, WIDTH + 150), np.uint8)
    scene = cv2.GaussianBlur(scene, (5, 5), 0)
    scene = cv2.cvtColor(scene, cv2.COLOR_GRAY2BGR)

    writer = cv2.VideoWriter(
        str(path), cv2.VideoWriter_fourcc(*"mp4v"), 30, (WIDTH, HEIGHT)
    )

    for frame in range(FRAMES):
        dx, dy = camera_shift(frame)
        # The scene content moves by (+dx, +dy) in the picture.
        matrix = np.float32([[1, 0, dx], [0, 1, dy]])
        moved = cv2.warpAffine(scene, matrix, (WIDTH + 150, HEIGHT + 100))
        writer.write(moved[:HEIGHT, :WIDTH])

    writer.release()


def write_hoop(path, reference_frame):
    dx, dy = camera_shift(reference_frame)
    x1, y1, x2, y2 = RIM
    path.write_text(json.dumps({
        "reference_frame": reference_frame,
        "rim_bbox": [x1 + dx, y1 + dy, x2 + dx, y2 + dy],
    }))


def test_rim_box_follows_camera_pan(tmp_path):
    video = tmp_path / "pan.mp4"
    make_panning_video(video)
    write_hoop(tmp_path / "hoop_detection.json", reference_frame=20)

    track_hoop(video, tmp_path / "hoop_detection.json",
               tmp_path / "hoop_track.csv")

    track = pd.read_csv(tmp_path / "hoop_track.csv")
    assert len(track) == FRAMES

    for row in track.itertuples():
        dx, dy = camera_shift(row.frame)
        assert abs(row.x1 - (RIM[0] + dx)) < 3
        assert abs(row.y1 - (RIM[1] + dy)) < 3


def test_steady_camera_gives_same_outcome_as_fixed_rim(tmp_path):
    # A ball dropping through the rim centre, hidden by the
    # net for 4 frames (12-15).
    hoop = {"reference_frame": 0, "rim_bbox": RIM}
    (tmp_path / "hoop_detection.json").write_text(json.dumps(hoop))

    pd.DataFrame({
        "frame": [10, 11, 16, 17],
        "center_x": [330.0, 330.0, 331.0, 331.0],
        "center_y": [120.0, 150.0, 170.0, 200.0],
    }).to_csv(tmp_path / "ball_trajectory.csv", index=False)

    analyze_outcome("fixed", tmp_path)
    fixed = json.loads((tmp_path / "shot_outcome.json").read_text())

    pd.DataFrame({
        "frame": range(20),
        "x1": RIM[0], "y1": RIM[1], "x2": RIM[2], "y2": RIM[3],
    }).to_csv(tmp_path / "hoop_track.csv", index=False)

    analyze_outcome("tracked", tmp_path)
    tracked = json.loads((tmp_path / "shot_outcome.json").read_text())

    assert fixed["outcome"] == tracked["outcome"] == "made"
    assert tracked["hoop_tracked"] is True
    assert (
        fixed["selected_crossing"]["distance_from_rim_center_px"]
        == tracked["selected_crossing"]["distance_from_rim_center_px"]
    )
