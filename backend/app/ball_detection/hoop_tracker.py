"""
Follow the hoop through the video when the camera moves.

The hoop is found by Roboflow on one reference frame only
(see hoop_detector.py). With a handheld camera the hoop then
drifts away from that position in the other frames, and the
made/missed check compares the ball with a rim that is no
longer there.

This module estimates how the camera moves between neighbouring
frames (from background feature points, on this computer; no
images are sent anywhere) and moves the reference rim box along
with it. The result is one rim box per frame.

With a steady camera the box simply stays where it is.
"""

import json
from pathlib import Path

import cv2
import numpy as np
import pandas as pd


# Motion is estimated on a smaller copy of each frame (faster).
ANALYSIS_WIDTH = 960

# Feature points used to estimate camera motion.
MAX_FEATURES = 400
MIN_FEATURES = 12


def _as_3x3(affine_2x3):
    matrix = np.eye(3)
    matrix[:2, :] = affine_2x3
    return matrix


def _frame_to_frame_motion(previous_gray, current_gray):
    """
    Estimate the camera motion from previous_gray to
    current_gray as a 3x3 similarity transform (shift, rotation,
    zoom). Moving objects such as the player and the ball are
    ignored as outliers. Returns None if it cannot be estimated.
    """

    points = cv2.goodFeaturesToTrack(
        previous_gray,
        maxCorners=MAX_FEATURES,
        qualityLevel=0.01,
        minDistance=8,
    )

    if points is None or len(points) < MIN_FEATURES:
        return None

    moved, status, _ = cv2.calcOpticalFlowPyrLK(
        previous_gray, current_gray, points, None,
        winSize=(21, 21), maxLevel=4,
    )

    found = status.reshape(-1) == 1

    if found.sum() < MIN_FEATURES:
        return None

    affine, inliers = cv2.estimateAffinePartial2D(
        points[found], moved[found],
        method=cv2.RANSAC,
        ransacReprojThreshold=2.0,
    )

    if affine is None or inliers is None or inliers.sum() < MIN_FEATURES:
        return None

    return _as_3x3(affine)


def track_hoop(video_path, hoop_json_path, output_csv):
    """
    Write one rim box per frame to output_csv, starting from the
    Roboflow detection on the reference frame.

    Returns a short summary (largest shift, frames where motion
    could not be estimated).
    """

    hoop = json.loads(
        Path(hoop_json_path).read_text(encoding="utf-8")
    )

    reference = int(hoop["reference_frame"])
    x1, y1, x2, y2 = map(float, hoop["rim_bbox"])

    capture = cv2.VideoCapture(str(video_path))

    if not capture.isOpened():
        raise RuntimeError(f"Cannot open video: {video_path}")

    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    scale = min(1.0, ANALYSIS_WIDTH / width)

    # Undo the downscaling: full-size motion = S^-1 * M * S.
    to_small = np.diag([scale, scale, 1.0])
    to_full = np.diag([1 / scale, 1 / scale, 1.0])

    # steps[i] maps frame i-1 to frame i (steps[0] is unused).
    steps = [np.eye(3)]
    failed_frames = []
    previous = None

    try:
        while True:
            ok, frame = capture.read()

            if not ok:
                break

            gray = cv2.cvtColor(
                cv2.resize(frame, None, fx=scale, fy=scale),
                cv2.COLOR_BGR2GRAY,
            )

            if previous is not None:
                motion = _frame_to_frame_motion(previous, gray)

                if motion is None:
                    # Assume no movement for this step.
                    failed_frames.append(len(steps))
                    motion = np.eye(3)

                steps.append(to_full @ motion @ to_small)

            previous = gray

    finally:
        capture.release()

    total_frames = len(steps)

    if not 0 <= reference < total_frames:
        raise ValueError(
            f"Reference frame {reference} is outside the video"
        )

    # Transform from the reference frame to every frame.
    to_frame = [None] * total_frames
    to_frame[reference] = np.eye(3)

    for index in range(reference + 1, total_frames):
        to_frame[index] = steps[index] @ to_frame[index - 1]

    for index in range(reference - 1, -1, -1):
        to_frame[index] = (
            np.linalg.inv(steps[index + 1]) @ to_frame[index + 1]
        )

    center = np.array([(x1 + x2) / 2, (y1 + y2) / 2, 1.0])
    half_w, half_h = (x2 - x1) / 2, (y2 - y1) / 2

    rows = []
    for index, transform in enumerate(to_frame):
        cx, cy, _ = transform @ center
        # Similarity transform: same zoom in x and y.
        zoom = float(np.sqrt(abs(np.linalg.det(transform[:2, :2]))))

        rows.append({
            "frame": index,
            "x1": round(cx - half_w * zoom, 2),
            "y1": round(cy - half_h * zoom, 2),
            "x2": round(cx + half_w * zoom, 2),
            "y2": round(cy + half_h * zoom, 2),
        })

    track = pd.DataFrame(rows)
    track.to_csv(output_csv, index=False)

    shift = np.hypot(
        (track.x1 + track.x2) / 2 - (x1 + x2) / 2,
        (track.y1 + track.y2) / 2 - (y1 + y2) / 2,
    )

    summary = {
        "frames": total_frames,
        "reference_frame": reference,
        "max_shift_px": round(float(shift.max()), 1),
        "motion_failed_frames": failed_frames,
    }

    print(f"Hoop tracked: {summary}")

    return summary


def load_hoop_track(path):
    """
    Return {frame: (center_x, center_y, width)} from a hoop track
    CSV, or None if the file does not exist.
    """

    path = Path(path)

    if not path.is_file():
        return None

    track = pd.read_csv(path)

    return {
        int(row.frame): (
            (row.x1 + row.x2) / 2,
            (row.y1 + row.y2) / 2,
            row.x2 - row.x1,
        )
        for row in track.itertuples()
    }
