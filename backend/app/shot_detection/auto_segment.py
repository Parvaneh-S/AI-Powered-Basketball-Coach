
from pathlib import Path
import json

import numpy as np
import pandas as pd


def detect_shot_events(csv_path, output_path, annotation_path=None):
    df = pd.read_csv(csv_path).sort_values("frame").reset_index(drop=True)

    required = [
        "frame",
        "timestamp_ms",
        "right_knee_angle",
        "right_elbow_angle",
    ]

    if any(col not in df.columns for col in required):
        raise ValueError("Required measurement columns are missing")

    if len(df) < 15:
        raise ValueError("Not enough video frames")

    frame = df["frame"].to_numpy(dtype=int)
    time = df["timestamp_ms"].to_numpy(dtype=float)
    knee = df["right_knee_angle"].to_numpy(dtype=float)
    elbow = df["right_elbow_angle"].to_numpy(dtype=float)

    # Approximate recorded video frame rate
    step_ms = float(np.median(np.diff(time)))
    if step_ms <= 0:
        raise ValueError("Invalid timestamps")

    fps = 1000.0 / step_ms

    # STEP 1: Identify the knee's deepest flexion.
    # Smooth only the detection signal; do not alter raw CSV.
    knee_smooth = (
        pd.Series(knee)
        .rolling(window=5, center=True, min_periods=3)
        .median()
        .to_numpy()
    )

    # Single-shot assumption: shooting preparation occurs
    # in the first 70% of this recording.
    search_end = max(1, int(len(df) * 0.70))
    knee_candidates = np.where(
        np.isfinite(knee_smooth[:search_end])
    )[0]

    if len(knee_candidates) == 0:
        raise ValueError("No usable knee measurements")

    knee_idx = int(
        knee_candidates[
            np.argmin(knee_smooth[knee_candidates])
        ]
    )

    # STEP 2: Estimate shot start.
    # Look backward up to 0.9 seconds for the knee angle
    # preceding flexion. This is a preliminary heuristic.
    lookback = round(0.9 * fps)
    left = max(0, knee_idx - lookback)

    candidates = np.where(
        np.isfinite(knee_smooth[left:knee_idx + 1])
    )[0] + left

    start_idx = int(
        candidates[np.argmax(knee_smooth[candidates])]
    )

    # STEP 3: Estimate release from rapid elbow extension.
    # Search after deepest knee flexion for up to 1 second.
    right = min(len(df) - 1, knee_idx + round(1.0 * fps))

    release_candidates = []

    for i in range(knee_idx + 1, right + 1):
        # Compare only truly consecutive, valid frames.
        if not (np.isfinite(elbow[i]) and np.isfinite(elbow[i - 1])):
            continue

        if frame[i] != frame[i - 1] + 1:
            continue

        delta = elbow[i] - elbow[i - 1]

        if delta > 0:
            release_candidates.append((delta, i))

    if not release_candidates:
        raise ValueError(
            "No valid elbow extension detected near knee extension"
        )

    largest_change, extension_idx = max(
        release_candidates,
        key=lambda item: item[0],
    )

    # A rapid elbow extension is only a proxy for release.
    # Use the frame immediately preceding the largest jump.
    release_idx = extension_idx - 1

    prediction = {
        "video": Path(csv_path).stem,
        "method": "pose_angle_heuristic_v1",
        "start_frame": int(frame[start_idx]),
        "start_time_ms": int(time[start_idx]),
        "knee_min_frame": int(frame[knee_idx]),
        "release_frame": int(frame[release_idx]),
        "release_time_ms": int(time[release_idx]),
        "max_elbow_change_deg_per_frame": round(
            float(largest_change), 2
        ),
        "end_frame": None,
        "outcome": "unknown",
        "status": "experimental_review_required",
    }

    # Validate AFTER prediction, never use manual values
    # to select predicted events.
    if annotation_path and Path(annotation_path).exists():
        with open(annotation_path, encoding="utf-8") as f:
            actual = json.load(f)

        prediction["validation"] = {
            "manual_start_frame": actual["start_frame"],
            "manual_release_frame": actual["release_frame"],
            "start_error_frames": abs(
                prediction["start_frame"] - actual["start_frame"]
            ),
            "release_error_frames": abs(
                prediction["release_frame"] - actual["release_frame"]
            ),
        }

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", encoding="utf-8") as f:
        json.dump(prediction, f, indent=2)

    print(json.dumps(prediction, indent=2))
    print(f"\nSaved to: {output_path}")

    return prediction



if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Detect basketball shot events"
    )

    parser.add_argument(
        "video_stem",
        help="Video name without extension, e.g. free_throw_01"
    )

    args = parser.parse_args()

    root = Path(__file__).resolve().parents[3]
    output_dir = root / "outputs" / args.video_stem

    csv_path = output_dir / "joint_angles.csv"
    annotation_path = output_dir / "shot_annotations.json"

    if not csv_path.is_file():
        parser.error(f"Measurements not found: {csv_path}")

    detect_shot_events(
        csv_path=csv_path,
        output_path=(
            output_dir / "predicted_shot_events.json"
        ),
        annotation_path=(
            annotation_path
            if annotation_path.exists()
            else None
        ),
    )

