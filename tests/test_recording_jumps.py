"""
Tests for finding a recording pause, cut or zoom inside a shot,
and for marking such a shot's form as not measurable.
"""

import json

import cv2
import numpy as np

from backend.app.measurements.shot_features import mark_not_measurable
from backend.app.shot_detection.recording_jumps import (
    jump_during_shot,
    picture_jumps,
)


def make_video(path, jump_at=None, frames=90):
    """
    A slowly moving bright square on a grey background. At
    jump_at the scene changes suddenly (as after a pause).
    """
    writer = cv2.VideoWriter(
        str(path), cv2.VideoWriter_fourcc(*"mp4v"), 30, (320, 180)
    )

    for frame in range(frames):
        image = np.full((180, 320, 3), 90, np.uint8)
        x = 20 + frame

        if jump_at is not None and frame >= jump_at:
            image[:] = 30           # different scene
            x = 250 - frame

        cv2.rectangle(image, (x, 60), (x + 40, 100), (255, 255, 255), -1)
        writer.write(image)

    writer.release()


def test_sudden_change_is_found(tmp_path):
    make_video(tmp_path / "v.mp4", jump_at=50)

    _, jumps = picture_jumps(tmp_path / "v.mp4")

    assert jumps == [50]


def test_smooth_video_has_no_jump(tmp_path):
    make_video(tmp_path / "v.mp4")

    assert picture_jumps(tmp_path / "v.mp4")[1] == []


def test_jump_inside_the_shot_is_reported(tmp_path):
    make_video(tmp_path / "v.mp4", jump_at=50)

    # Ball reaches the hoop at 70: the shot is 37..70.
    assert jump_during_shot(tmp_path / "v.mp4", {}, ball_arrival_frame=70) == 50
    # Without the arrival: from the dip to release + 6.
    events = {"knee_min_frame": 44, "release_frame": 48}
    assert jump_during_shot(tmp_path / "v.mp4", events) == 50


def test_jump_just_before_the_dip_is_ignored(tmp_path):
    # Recording resumed just before the knee dip: the dip and
    # release are both in the video.
    make_video(tmp_path / "v.mp4", jump_at=50)

    events = {"knee_min_frame": 53, "release_frame": 60}
    assert jump_during_shot(tmp_path / "v.mp4", events) is None


def test_release_seen_after_jump_is_measured(tmp_path):
    # Camera jump at 50, then the dip (53) and a release that the
    # ball confirms (60): the shot is fully filmed after the jump.
    make_video(tmp_path / "v.mp4", jump_at=50)

    events = {
        "knee_min_frame": 53, "release_frame": 60,
        "release_window": [59, 61],
    }
    assert jump_during_shot(
        tmp_path / "v.mp4", events, ball_arrival_frame=80
    ) is None

    # Same jump, but the release was not seen: it may be hidden
    # by the jump, so the shot is reported.
    events.pop("release_window")
    assert jump_during_shot(
        tmp_path / "v.mp4", events, ball_arrival_frame=80
    ) == 50


def test_jump_before_the_shot_is_ignored(tmp_path):
    # The recording resumed before the shot started.
    make_video(tmp_path / "v.mp4", jump_at=10)

    assert jump_during_shot(tmp_path / "v.mp4", {}, ball_arrival_frame=70) is None


def test_not_measurable_empties_the_form_values(tmp_path):
    features = {
        "video": "v", "min_knee_angle": 120.5,
        "release_elbow_angle": 130.0, "max_elbow_angle": 170.0,
        "knee_angle_range": 40.0, "elbow_angle_range": 90.0,
        "elbow_extension_after_release": 30.0,
        "shooting_motion_ms": 800, "release_angle_valid": True,
        "measurement_quality": "pass", "outcome": "unknown",
    }
    (tmp_path / "shot_features.json").write_text(json.dumps(features))

    mark_not_measurable(tmp_path / "shot_features.csv", "paused")

    saved = json.loads((tmp_path / "shot_features.json").read_text())

    assert saved["min_knee_angle"] is None
    assert saved["release_elbow_angle"] is None
    assert saved["measurement_quality"] == "not_measurable"
    assert saved["measurement_note"] == "paused"
    assert (tmp_path / "shot_features.csv").is_file()
