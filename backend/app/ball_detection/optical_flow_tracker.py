
from pathlib import Path

import cv2
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
VIDEO = ROOT / "sample_videos" / "free_throw_03.mp4"
OUTPUT_DIR = ROOT / "outputs" / "free_throw_03"

TRAJECTORY = OUTPUT_DIR / "ball_trajectory.csv"

# Frame 163 was visually verified to be on the basketball.
START_FRAME = 163
END_FRAME = 180

# Approximate radius of the region used to find ball features.
PATCH_RADIUS = 17


def main():
    trajectory = pd.read_csv(TRAJECTORY)
    start_row = trajectory.loc[
        trajectory["frame"] == START_FRAME
    ]

    if start_row.empty:
        raise ValueError(
            f"No ball position found at frame {START_FRAME}"
        )

    start_x = float(start_row.iloc[0]["center_x"])
    start_y = float(start_row.iloc[0]["center_y"])

    cap = cv2.VideoCapture(str(VIDEO))

    if not cap.isOpened():
        raise RuntimeError(f"Cannot open video: {VIDEO}")

    cap.set(cv2.CAP_PROP_POS_FRAMES, START_FRAME)
    success, frame = cap.read()

    if not success:
        raise RuntimeError("Cannot read starting frame")

    previous_gray = cv2.cvtColor(
        frame, cv2.COLOR_BGR2GRAY
    )

    height, width = previous_gray.shape

    # Find trackable corners near the basketball.
    mask = np.zeros_like(previous_gray)

    cv2.circle(
        mask,
        (round(start_x), round(start_y)),
        PATCH_RADIUS,
        255,
        -1,
    )

    points = cv2.goodFeaturesToTrack(
        previous_gray,
        maxCorners=25,
        qualityLevel=0.01,
        minDistance=3,
        mask=mask,
        blockSize=3,
    )

    if points is None:
        raise RuntimeError(
            "No trackable features found near basketball"
        )

    print(f"Initial features: {len(points)}")

    current_x = start_x
    current_y = start_y

    output_rows = [
        {
            "frame": START_FRAME,
            "center_x": current_x,
            "center_y": current_y,
            "feature_count": len(points),
            "status": "initial_detection",
        }
    ]

    output_frames = []

    for frame_number in range(
        START_FRAME + 1, END_FRAME + 1
    ):
        success, frame = cap.read()

        if not success:
            break

        current_gray = cv2.cvtColor(
            frame, cv2.COLOR_BGR2GRAY
        )

        next_points, status, errors = (
            cv2.calcOpticalFlowPyrLK(
                previous_gray,
                current_gray,
                points,
                None,
                winSize=(21, 21),
                maxLevel=3,
                criteria=(
                    cv2.TERM_CRITERIA_EPS
                    | cv2.TERM_CRITERIA_COUNT,
                    30,
                    0.01,
                ),
            )
        )

        if next_points is None or status is None:
            print(
                f"Frame {frame_number}: tracking lost"
            )
            break

        valid = status.flatten() == 1

        old_points = points.reshape(-1, 2)[valid]
        new_points = next_points.reshape(-1, 2)[valid]

        if len(new_points) < 3:
            print(
                f"Frame {frame_number}: too few features"
            )
            break

        # Estimate movement using median feature displacement.
        displacement = np.median(
            new_points - old_points,
            axis=0,
        )

        current_x += float(displacement[0])
        current_y += float(displacement[1])

        feature_count = len(new_points)

        output_rows.append(
            {
                "frame": frame_number,
                "center_x": current_x,
                "center_y": current_y,
                "feature_count": feature_count,
                "status": "optical_flow",
            }
        )

        # Draw estimated basketball center in cyan.
        cv2.circle(
            frame,
            (round(current_x), round(current_y)),
            7,
            (255, 255, 0),
            -1,
        )

        for px, py in new_points:
            cv2.circle(
                frame,
                (round(float(px)), round(float(py))),
                2,
                (0, 255, 0),
                -1,
            )

        cv2.putText(
            frame,
            f"Frame {frame_number} | Features: {feature_count}",
            (15, 30),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (255, 255, 255),
            2,
        )

        output_frames.append(frame)

        print(
            f"Frame {frame_number}: "
            f"({current_x:.1f}, {current_y:.1f}), "
            f"features={feature_count}"
        )

        previous_gray = current_gray
        points = new_points.reshape(-1, 1, 2).astype(
            np.float32
        )

    cap.release()

    OUTPUT_DIR.mkdir(
        parents=True, exist_ok=True
    )

    csv_path = (
        OUTPUT_DIR / "optical_flow_trajectory.csv"
    )

    pd.DataFrame(output_rows).to_csv(
        csv_path, index=False
    )

    if output_frames:
        video_path = (
            OUTPUT_DIR / "optical_flow_tracking.mp4"
        )

        fourcc = cv2.VideoWriter_fourcc(
            *"mp4v"
        )

        writer = cv2.VideoWriter(
            str(video_path),
            fourcc,
            30,
            (width, height),
        )

        for image in output_frames:
            writer.write(image)

        writer.release()

        print(f"Saved video: {video_path}")

    print(f"Saved CSV: {csv_path}")


if __name__ == "__main__":
    main()
