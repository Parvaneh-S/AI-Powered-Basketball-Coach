
from pathlib import Path
import csv
import json
import sys


ROOT = Path(__file__).resolve().parents[3]


def load_json(path):
    with path.open(encoding="utf-8") as file:
        return json.load(file)


def summarize_trajectory(csv_path):
    with csv_path.open(
        newline="", encoding="utf-8"
    ) as file:
        rows = list(csv.DictReader(file))

    if not rows:
        return {
            "tracked_frames": 0,
            "first_tracked_frame": None,
            "last_tracked_frame": None,
            "tracking_coverage_pct": None,
        }

    frame_numbers = sorted({
        int(row["frame"]) for row in rows
    })

    first_frame = frame_numbers[0]
    last_frame = frame_numbers[-1]

    expected_frames = last_frame - first_frame + 1

    coverage = (
        100.0 * len(frame_numbers) / expected_frames
    )

    return {
        "tracked_frames": len(frame_numbers),
        "first_tracked_frame": first_frame,
        "last_tracked_frame": last_frame,
        "tracking_coverage_pct": round(
            coverage, 2
        ),
    }


def build_shot_analysis(video_id, output_dir=None, *, hoop_dir=None):
    output_dir = Path(output_dir) if output_dir is not None else ROOT / "outputs" / video_id
    hoop_dir = Path(hoop_dir) if hoop_dir is not None else output_dir

    features = load_json(
        output_dir / "shot_features.json"
    )

    events = load_json(
        output_dir / "predicted_shot_events.json"
    )

    hoop_path = hoop_dir / "hoop_detection.json"
    hoop = load_json(hoop_path) if hoop_path.is_file() else {}

    outcome = load_json(
        output_dir / "shot_outcome.json"
    )

    trajectory = summarize_trajectory(
        output_dir / "ball_trajectory.csv"
    )

    analysis = {
        "video_id": video_id,
        "shot_id": features["shot_id"],
        "shot_number": events.get("shot_number", 1),
        "shot_type": "free_throw",

        "shot_events": {
            "start_frame": features["start_frame"],
            "start_time_ms": events.get("start_time_ms"),
            "release_time_ms": events.get("release_time_ms"),
            "end_time_ms": events.get("end_time_ms"),
            "flight_end_frame": events.get("flight_end_frame"),
            "flight_end_time_ms": events.get("flight_end_time_ms"),
            "release_method": events.get("release_method"),
            "measurement_frames": features.get("measurement_frames", {}),
            "release_frame": features["release_frame"],
            "end_frame": features["end_frame"],
            "end_frame_source": features[
                "end_frame_source"
            ],
            "segmentation_method": events.get(
                "method"
            ),
            "segmentation_status": events.get(
                "status"
            ),
        },

        "biomechanics": {
            "shooting_arm": features["shooting_arm"],
            "shooting_motion_ms": features[
                "shooting_motion_ms"
            ],
            "min_knee_angle": features[
                "min_knee_angle"
            ],
            "max_elbow_angle": features[
                "max_elbow_angle"
            ],
            "release_elbow_angle": features[
                "release_elbow_angle"
            ],
            "knee_angle_range": features[
                "knee_angle_range"
            ],
            "elbow_angle_range": features[
                "elbow_angle_range"
            ],
            "elbow_extension_after_release": (
                features[
                    "elbow_extension_after_release"
                ]
            ),
            "knee_coverage_pct": features[
                "knee_coverage_pct"
            ],
            "elbow_coverage_pct": features[
                "elbow_coverage_pct"
            ],
            "valid_knee_frames": features.get("valid_knee_frames"),
            "valid_elbow_frames": features.get("valid_elbow_frames"),
            "release_angle_valid": features.get("release_angle_valid"),
            "measurement_quality": features[
                "measurement_quality"
            ],
            # Why the form could not be measured, if so.
            "measurement_note": features.get(
                "measurement_note"
            ),
        },

        "ball_tracking": trajectory,

        "hoop_detection": {
            "rim_center": hoop.get("rim_center"),
            "rim_bbox": hoop.get("rim_bbox"),
            "confidence": hoop.get("confidence"),
        },

        "shot_outcome": {
            "prediction": outcome.get(
                "outcome", "unknown"
            ),
            "observation": outcome.get(
                "observation"
            ),
            "method": outcome.get("method"),
        },

        "analysis_status": "experimental",
    }

    output_path = output_dir / "shot_analysis.json"

    with output_path.open(
        "w", encoding="utf-8"
    ) as file:
        json.dump(analysis, file, indent=2)

    return analysis


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(
            "Usage: python -m "
            "backend.app.analysis.shot_analysis "
            "<video_id>"
        )

    build_shot_analysis(sys.argv[1])
