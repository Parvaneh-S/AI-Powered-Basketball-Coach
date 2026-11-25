"""
Tests for finding the release frame from the ball leaving the
hands (release.py).

Simulated shot: the ball sits in the hands (close to the wrist)
until it is released, then flies away. Ball radius 10 px.
"""

import json

import pandas as pd

from backend.app.shot_detection.release import refine_release


KNEE_MIN = 10
TRUE_RELEASE = 20


def write_shot(tmp_path, pose_release):
    angles, trajectory, detections = [], [], []

    for frame in range(40):
        wrist = (300.0, 400.0 - 5 * min(frame, TRUE_RELEASE))

        if frame <= TRUE_RELEASE:
            # In the hands: 1 ball radius above the wrist.
            ball = (wrist[0], wrist[1] - 10)
        else:
            t = frame - TRUE_RELEASE
            ball = (300.0 + 15 * t, wrist[1] - 10 - 25 * t)

        angles.append({
            "frame": frame,
            "timestamp_ms": round(frame * 1000 / 30),
            "right_wrist_x": wrist[0], "right_wrist_y": wrist[1],
            "left_wrist_x": None, "left_wrist_y": None,
        })
        trajectory.append({
            "frame": frame, "center_x": ball[0], "center_y": ball[1],
        })
        detections.append({
            "frame": frame, "confidence": 0.9,
            "center_x": ball[0], "center_y": ball[1],
            "x1": ball[0] - 10, "x2": ball[0] + 10,
            "y1": ball[1] - 10, "y2": ball[1] + 10,
        })

    pd.DataFrame(angles).to_csv(tmp_path / "angles.csv", index=False)
    pd.DataFrame(trajectory).to_csv(tmp_path / "traj.csv", index=False)
    pd.DataFrame(detections).to_csv(tmp_path / "det.csv", index=False)

    (tmp_path / "events.json").write_text(json.dumps({
        "knee_min_frame": KNEE_MIN,
        "release_frame": pose_release,
        "release_time_ms": 0,
    }))


def refine(tmp_path):
    return refine_release(
        tmp_path / "events.json", tmp_path / "angles.csv",
        tmp_path / "traj.csv", tmp_path / "det.csv",
    )


def test_late_pose_release_is_corrected_by_ball(tmp_path):
    # Pose-only estimate 12 frames late (the hop problem).
    write_shot(tmp_path, pose_release=TRUE_RELEASE + 12)

    events = refine(tmp_path)

    assert events["release_method"] == "ball_leaves_hands"
    assert abs(events["release_frame"] - TRUE_RELEASE) <= 1
    assert events["pose_release_frame"] == TRUE_RELEASE + 12
    assert events["release_time_ms"] == round(
        events["release_frame"] * 1000 / 30
    )


def test_pose_release_inside_ball_window_is_kept(tmp_path):
    write_shot(tmp_path, pose_release=TRUE_RELEASE)

    events = refine(tmp_path)

    assert events["release_method"] == "pose_confirmed_by_ball"
    assert events["release_frame"] == TRUE_RELEASE


def test_without_wrist_positions_pose_release_is_kept(tmp_path):
    write_shot(tmp_path, pose_release=33)

    # Older measurement files have no wrist columns.
    angles = pd.read_csv(tmp_path / "angles.csv")
    angles.drop(columns=[c for c in angles if "wrist" in c]).to_csv(
        tmp_path / "angles.csv", index=False
    )

    events = refine(tmp_path)

    assert events["release_method"] == "pose_only_no_ball_evidence"
    assert events["release_frame"] == 33
