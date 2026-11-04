from pathlib import Path
import csv
import json


# Initial engineering thresholds; refine after testing.
MIN_COVERAGE_PCT = 80.0
FOLLOW_THROUGH_FRAMES = 6


def extract_shot_features(angles_path, annotation_path, output_path):
    # Load shot annotations
    with open(annotation_path, encoding="utf-8") as f:
        shot = json.load(f)

    # Load frame-by-frame measurements
    with open(angles_path, newline="", encoding="utf-8") as f:
        frames = list(csv.DictReader(f))

    frame_lookup = {
        int(row["frame"]): row
        for row in frames
    }

    start = int(shot["start_frame"])
    release = int(shot["release_frame"])
    end = int(shot["end_frame"])

    if not (0 <= start < release < end):
        raise ValueError("Invalid shot boundaries")

    if any(i not in frame_lookup for i in range(start, end + 1)):
        raise ValueError("Annotated frames are missing from CSV")

    arm = shot["shooting_arm"].lower()

    if arm not in ("left", "right"):
        raise ValueError("Invalid shooting arm")

    elbow_col = f"{arm}_elbow_angle"
    knee_col = f"{arm}_knee_angle"

    # Analysis windows:
    # Knee: shot start through release
    # Elbow: shot start through early follow-through
    elbow_end = min(release + FOLLOW_THROUGH_FRAMES, end)

    def get_angle(frame_number, column):
        raw = frame_lookup[frame_number][column]

        if raw in ("", None):
            return None

        return float(raw)

    def get_values(first, last, column):
        return [
            value
            for i in range(first, last + 1)
            if (value := get_angle(i, column)) is not None
        ]

    def angle_range(values):
        if len(values) < 2:
            return None

        return max(values) - min(values)

    def coverage_pct(values, first, last):
        expected_count = last - first + 1
        return 100.0 * len(values) / expected_count

    def rounded(value):
        return round(value, 2) if value is not None else None

    knee_angles = get_values(start, release, knee_col)

    elbow_angles = get_values(
        start, elbow_end, elbow_col
    )

    # Only after release, including release frame
    follow_through_angles = get_values(
        release, elbow_end, elbow_col
    )

    release_elbow = get_angle(release, elbow_col)

    knee_coverage = coverage_pct(
        knee_angles, start, release
    )

    elbow_coverage = coverage_pct(
        elbow_angles, start, elbow_end
    )

    release_angle_valid = release_elbow is not None

    # Elbow extension from release to the maximum
    # observed angle in the early follow-through.
    elbow_extension = None

    if release_angle_valid and len(follow_through_angles) >= 2:
        elbow_extension = max(
            follow_through_angles
        ) - release_elbow

    # Preliminary measurement quality.
    # Coverage alone does not prove accuracy.
    quality_ok = (
        knee_coverage >= MIN_COVERAGE_PCT
        and elbow_coverage >= MIN_COVERAGE_PCT
        and release_angle_valid
        and len(knee_angles) >= 2
        and len(elbow_angles) >= 2
    )

    features = {
        "video": shot["video"],
        "shot_id": shot["shot_id"],
        "shooting_arm": arm,
        "start_frame": start,
        "release_frame": release,
        "end_frame": end,
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
        "release_elbow_angle": rounded(release_elbow),
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
        "knee_coverage_pct": rounded(knee_coverage),
        "elbow_coverage_pct": rounded(elbow_coverage),
        "release_angle_valid": release_angle_valid,
        "measurement_quality": (
            "pass" if quality_ok else "review"
        ),
        "outcome": shot["outcome"],
    }

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open(
        "w", newline="", encoding="utf-8"
    ) as f:
        writer = csv.DictWriter(
            f, fieldnames=list(features.keys())
        )
        writer.writeheader()
        writer.writerow(features)

    print("Extracted shot features (v2):")
    print(json.dumps(features, indent=2))
    print(f"\nSaved to: {output_path}")


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[3]

    extract_shot_features(
        root / "outputs/joint_angles.csv",
        root / "outputs/shot_annotations.json",
        root / "outputs/shot_features.csv",
    )
