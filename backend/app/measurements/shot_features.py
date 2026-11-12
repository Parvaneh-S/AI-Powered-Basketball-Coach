
from pathlib import Path
import csv
import json
import sys


MIN_COVERAGE_PCT = 80.0
FOLLOW_THROUGH_FRAMES = 6


def extract_shot_features(
    angles_path,
    annotation_path,
    output_path,
    shooting_arm="right",
    video_id=None,
):
    with open(annotation_path, encoding="utf-8") as f:
        shot = json.load(f)

    with open(
        angles_path, newline="", encoding="utf-8"
    ) as f:
        frames = list(csv.DictReader(f))

    if not frames:
        raise ValueError("Joint-angle CSV is empty")

    frame_lookup = {
        int(row["frame"]): row
        for row in frames
    }

    start = int(shot["start_frame"])
    release = int(shot["release_frame"])

    # Automatic segmentation currently does not predict
    # a shot end. Use a provisional follow-through window.
    predicted_end = shot.get("end_frame")

    if predicted_end is None:
        end = release + FOLLOW_THROUGH_FRAMES
        end_source = "provisional_follow_through_window"
    else:
        end = int(predicted_end)
        end_source = "shot_events"

    if not (0 <= start < release < end):
        raise ValueError("Invalid shot boundaries")

    if any(
        frame not in frame_lookup
        for frame in range(start, end + 1)
    ):
        raise ValueError(
            "Required frames are missing from joint_angles.csv"
        )

    arm = shot.get("shooting_arm") or shooting_arm
    arm = arm.lower()

    if arm not in ("left", "right"):
        raise ValueError("Invalid shooting arm")

    elbow_col = f"{arm}_elbow_angle"
    knee_col = f"{arm}_knee_angle"

    for column in (elbow_col, knee_col):
        if column not in frames[0]:
            raise ValueError(f"Missing column: {column}")

    elbow_end = min(
        release + FOLLOW_THROUGH_FRAMES,
        end,
    )

    def get_angle(frame_number, column):
        raw = frame_lookup[frame_number][column]

        if raw in ("", None):
            return None

        return float(raw)

    def get_values(first, last, column):
        return [
            value
            for frame in range(first, last + 1)
            if (
                value := get_angle(frame, column)
            ) is not None
        ]

    def rounded(value):
        return round(value, 2) if value is not None else None

    def angle_range(values):
        if len(values) < 2:
            return None

        return max(values) - min(values)

    def coverage_pct(values, first, last):
        expected = last - first + 1
        return 100.0 * len(values) / expected

    knee_angles = get_values(
        start, release, knee_col
    )

    elbow_angles = get_values(
        start, elbow_end, elbow_col
    )

    follow_through_angles = get_values(
        release, elbow_end, elbow_col
    )

    release_elbow = get_angle(
        release, elbow_col
    )

    knee_coverage = coverage_pct(
        knee_angles, start, release
    )

    elbow_coverage = coverage_pct(
        elbow_angles, start, elbow_end
    )

    release_angle_valid = (
        release_elbow is not None
    )

    elbow_extension = None

    if (
        release_angle_valid
        and len(follow_through_angles) >= 2
    ):
        elbow_extension = (
            max(follow_through_angles)
            - release_elbow
        )

    quality_ok = (
        knee_coverage >= MIN_COVERAGE_PCT
        and elbow_coverage >= MIN_COVERAGE_PCT
        and release_angle_valid
        and len(knee_angles) >= 2
        and len(elbow_angles) >= 2
    )

    if video_id is None:
        video_id = Path(angles_path).parent.name

    features = {
        "video": video_id,
        "shot_id": shot.get(
            "shot_id", f"{video_id}_shot_1"
        ),
        "shooting_arm": arm,
        "start_frame": start,
        "release_frame": release,
        "end_frame": end,
        "end_frame_source": end_source,
        "shooting_motion_ms": (
            int(shot["release_time_ms"])
            - int(shot["start_time_ms"])
        ),
        "min_knee_angle": rounded(
            min(knee_angles) if knee_angles else None
        ),
        "max_elbow_angle": rounded(
            max(elbow_angles) if elbow_angles else None
        ),
        "release_elbow_angle": rounded(
            release_elbow
        ),
        "knee_angle_range": rounded(
            angle_range(knee_angles)
        ),
        "elbow_angle_range": rounded(
            angle_range(elbow_angles)
        ),
        "elbow_extension_after_release": rounded(
            elbow_extension
        ),
        "valid_knee_frames": len(knee_angles),
        "valid_elbow_frames": len(elbow_angles),
        "knee_coverage_pct": rounded(
            knee_coverage
        ),
        "elbow_coverage_pct": rounded(
            elbow_coverage
        ),
        "release_angle_valid": release_angle_valid,
        "measurement_quality": (
            "pass" if quality_ok else "review"
        ),
        "outcome": shot.get("outcome", "unknown"),
    }

    output_path = Path(output_path)
    output_path.parent.mkdir(
        parents=True, exist_ok=True
    )

    with output_path.open(
        "w", newline="", encoding="utf-8"
    ) as f:
        writer = csv.DictWriter(
            f, fieldnames=list(features.keys())
        )
        writer.writeheader()
        writer.writerow(features)

    json_path = output_path.with_suffix(".json")

    with json_path.open(
        "w", encoding="utf-8"
    ) as f:
        json.dump(features, f, indent=2)

    print("Extracted shot features:")
    print(json.dumps(features, indent=2))
    print(f"\nSaved CSV: {output_path}")
    print(f"Saved JSON: {json_path}")

    return features


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[3]

    if len(sys.argv) < 2:
        raise SystemExit(
            "Usage: python -m "
            "backend.app.measurements.shot_features "
            "<video_id> [left|right]"
        )

    video_id = sys.argv[1]
    arm = (
        sys.argv[2]
        if len(sys.argv) > 2
        else "right"
    )

    output_dir = root / "outputs" / video_id

    extract_shot_features(
        angles_path=output_dir / "joint_angles.csv",
        annotation_path=(
            output_dir / "predicted_shot_events.json"
        ),
        output_path=output_dir / "shot_features.csv",
        shooting_arm=arm,
        video_id=video_id,
    )
