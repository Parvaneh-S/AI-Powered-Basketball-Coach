
from pathlib import Path
import csv
import json
import statistics


def evaluate_all(output_root):
    results = []

    for folder in sorted(Path(output_root).iterdir()):
        if not folder.is_dir():
            continue

        manual_path = folder / "shot_annotations.json"
        predicted_path = folder / "predicted_shot_events.json"
        angles_path = folder / "joint_angles.csv"

        if not (
            manual_path.exists()
            and predicted_path.exists()
            and angles_path.exists()
        ):
            continue

        with manual_path.open(encoding="utf-8") as f:
            manual = json.load(f)

        with predicted_path.open(encoding="utf-8") as f:
            predicted = json.load(f)

        # Determine frame interval from actual measurement timestamps.
        with angles_path.open(
            newline="", encoding="utf-8"
        ) as f:
            angles = list(csv.DictReader(f))

        timestamps = [
            float(row["timestamp_ms"])
            for row in angles
        ]

        if len(timestamps) < 2:
            print(f"Skipping {folder.name}: too few frames")
            continue

        intervals = [
            b - a
            for a, b in zip(timestamps, timestamps[1:])
            if b > a
        ]

        if not intervals:
            print(f"Skipping {folder.name}: invalid timestamps")
            continue

        frame_interval_ms = statistics.median(intervals)

        start_error = abs(
            int(predicted["start_frame"])
            - int(manual["start_frame"])
        )

        release_error = abs(
            int(predicted["release_frame"])
            - int(manual["release_frame"])
        )

        results.append({
            "video": folder.name,
            "manual_start": manual["start_frame"],
            "predicted_start": predicted["start_frame"],
            "start_error_frames": start_error,
            "start_error_ms": round(
                start_error * frame_interval_ms, 1
            ),
            "manual_release": manual["release_frame"],
            "predicted_release": predicted["release_frame"],
            "release_error_frames": release_error,
            "release_error_ms": round(
                release_error * frame_interval_ms, 1
            ),
        })

    if not results:
        print("No complete evaluation records found.")
        return

    report_path = Path(output_root) / "segmentation_evaluation.csv"

    with report_path.open(
        "w", newline="", encoding="utf-8"
    ) as f:
        writer = csv.DictWriter(
            f, fieldnames=list(results[0].keys())
        )
        writer.writeheader()
        writer.writerows(results)

    print("\nAUTOMATIC SEGMENTATION EVALUATION")
    print("-" * 45)

    for row in results:
        print(f"\nVideo: {row['video']}")
        print(
            f"  Start error: "
            f"{row['start_error_frames']} frames"
        )
        print(
            f"  Release error: "
            f"{row['release_error_frames']} frames"
        )

    mean_start_error = statistics.mean(
        r["start_error_frames"] for r in results
    )

    mean_release_error = statistics.mean(
        r["release_error_frames"] for r in results
    )

    print("\nSUMMARY")
    print(f"Videos evaluated: {len(results)}")
    print(f"Mean start error: {mean_start_error:.2f} frames")
    print(
        f"Mean release error: "
        f"{mean_release_error:.2f} frames"
    )
    print(f"Report saved to: {report_path}")


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[3]
    evaluate_all(root / "outputs")
