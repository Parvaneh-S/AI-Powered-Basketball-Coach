"""
Find the release frame from the ball leaving the hands.

The pose-only method (auto_segment.py) takes the frame before the
largest elbow jump after the knee dip. That works for a standing
free throw, but with a small hop the landing or a pose glitch can
cause a larger jump later, and the release comes out 10+ frames
late.

Here the ball path is used as evidence. While the ball is in the
hands its centre stays close to a wrist (about 1.5 ball radii);
once released, the distance grows quickly. The ball is "clearly
out of the hands" when it is more than 2.5 ball radii from both
wrists and stays out. The release is the frame just before.

If the pose-based release lies between the last in-hand frame and
the first clearly-out frame, both methods agree and the pose-based
frame is kept (it is exact on the hand-labelled samples). If it
lies outside, the ball-based frame is used. Without enough ball
data the pose-based frame is kept.
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd


# Ball centre to nearest wrist, in ball radii.
OUT_OF_HANDS_RADII = 2.5

# Once out, the ball must stay out for this many observed frames
# (ignores a single noisy detection).
STAY_OUT_POINTS = 4

# Consider the ball from shortly before the knee dip.
BEFORE_DIP_FRAMES = 5


def ball_hand_distances(angles_csv, trajectory_csv, detections_csv):
    """
    Return [(frame, distance in ball radii)] for every frame where
    the ball and at least one wrist are known.
    """

    angles = pd.read_csv(angles_csv).set_index("frame")
    trajectory = pd.read_csv(trajectory_csv)
    detections = pd.read_csv(detections_csv)

    wrist_columns = [
        ("left_wrist_x", "left_wrist_y"),
        ("right_wrist_x", "right_wrist_y"),
    ]

    if not all(
        column in angles.columns
        for pair in wrist_columns for column in pair
    ):
        # Older measurement files have no wrist positions.
        return []

    distances = []

    for point in trajectory.itertuples():
        frame = int(point.frame)

        if frame not in angles.index:
            continue

        # Ball radius from the matching detection box.
        same_frame = detections[detections["frame"] == frame]
        if same_frame.empty:
            continue

        nearest = same_frame.iloc[
            (
                (same_frame["center_x"] - point.center_x) ** 2
                + (same_frame["center_y"] - point.center_y) ** 2
            ).to_numpy().argmin()
        ]
        radius = (nearest["x2"] - nearest["x1"]) / 2

        if not radius > 0:
            continue

        wrist_distances = [
            np.hypot(
                point.center_x - angles.at[frame, x_column],
                point.center_y - angles.at[frame, y_column],
            )
            for x_column, y_column in wrist_columns
            if pd.notna(angles.at[frame, x_column])
        ]

        if wrist_distances:
            distances.append(
                (frame, min(wrist_distances) / radius)
            )

    return distances


def release_window(distances, knee_min_frame):
    """
    Return (last_in_hands_frame, first_clearly_out_frame), or None
    if the ball is not seen leaving the hands.
    """

    points = [
        (frame, distance)
        for frame, distance in distances
        if frame >= knee_min_frame - BEFORE_DIP_FRAMES
    ]

    for index, (frame, distance) in enumerate(points):
        if distance <= OUT_OF_HANDS_RADII:
            continue

        following = points[index:index + STAY_OUT_POINTS]

        if len(following) < STAY_OUT_POINTS or any(
            d <= OUT_OF_HANDS_RADII for _, d in following
        ):
            continue

        in_hands = [
            f for f, d in points[:index] if d <= OUT_OF_HANDS_RADII
        ]

        if not in_hands:
            return None

        return in_hands[-1], frame

    return None


def refine_release(
    events_path, angles_csv, trajectory_csv, detections_csv
):
    """
    Update the release frame in predicted_shot_events.json using
    the ball leaving the hands. The pose-based frame is kept as
    pose_release_frame for reference.
    """

    events_path = Path(events_path)
    events = json.loads(events_path.read_text(encoding="utf-8"))

    pose_release = int(
        events.get("pose_release_frame", events["release_frame"])
    )

    window = release_window(
        ball_hand_distances(
            angles_csv, trajectory_csv, detections_csv
        ),
        int(events["knee_min_frame"]),
    )

    if window is None:
        release, method = pose_release, "pose_only_no_ball_evidence"
    elif window[0] <= pose_release <= window[1]:
        release, method = pose_release, "pose_confirmed_by_ball"
    else:
        release, method = window[1] - 1, "ball_leaves_hands"

    # Keep the release time consistent with the frame.
    angles = pd.read_csv(angles_csv).set_index("frame")
    if release in angles.index:
        events["release_time_ms"] = int(
            angles.at[release, "timestamp_ms"]
        )

    events["pose_release_frame"] = pose_release
    events["release_frame"] = int(release)
    events["release_method"] = method
    events["release_window"] = (
        [int(window[0]), int(window[1])] if window else None
    )

    events_path.write_text(
        json.dumps(events, indent=2), encoding="utf-8"
    )

    print(
        f"Release frame: {release} ({method}; "
        f"pose-based {pose_release}, window {window})"
    )

    return events
