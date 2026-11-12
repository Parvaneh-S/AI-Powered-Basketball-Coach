
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


def build_shot_analysis(video_id):
    output_dir = ROOT / "outputs" / video_id

    features = load_json(
        output_dir / "shot_features.json"
    )

    events = load_json(
        output_dir / "predicted_shot_events.json"
    )

    hoop = load_json(
        output_dir / "hoop_detection.json"
    )

    outcome = load_json(
        output_dir / "shot_outcome.json"
    )

    trajectory = summarize_trajectory(
        output_dir / "ball_trajectory.csv"
    )

    analysis = {
        "video_id": video_id,
        "shot_id": features["shot_id"],
        "shot_type": "free_throw",

        "shot_events": {
            "start_frame": features["start_frame"],
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
            "measurement_quality": features[
                "measurement_quality"
            ],
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

    print(json.dumps(analysis, indent=2))
    print(f"\nSaved: {output_path}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(
            "Usage: python -m "
            "backend.app.analysis.shot_analysis "
            "<video_id>"
        )

    build_shot_analysis(sys.argv[1])
