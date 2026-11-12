
import argparse
import json
from collections import deque
from pathlib import Path

import cv2
import pandas as pd


def visualize_trajectory(video_path, output_dir):
    video_path = Path(video_path)
    output_dir = Path(output_dir)

    trajectory_path = output_dir / "ball_trajectory.csv"
    hoop_path = output_dir / "hoop_detection.json"
    output_path = output_dir / "trajectory_with_hoop.mp4"

    if not trajectory_path.exists():
        raise FileNotFoundError(trajectory_path)

    if not hoop_path.exists():
        raise FileNotFoundError(hoop_path)

    # Read tracked basketball positions.
    trajectory = pd.read_csv(trajectory_path)

    required_columns = {
        "frame", "center_x", "center_y"
    }

    if not required_columns.issubset(trajectory.columns):
        raise ValueError(
            "Trajectory CSV is missing required columns."
        )

    trajectory = trajectory.dropna(
        subset=["frame", "center_x", "center_y"]
    )

    trajectory_by_frame = {
        int(row["frame"]): (
            float(row["center_x"]),
            float(row["center_y"]),
        )
        for _, row in trajectory.iterrows()
    }

    # Read the automatically detected hoop.
    with hoop_path.open("r", encoding="utf-8") as file:
        hoop = json.load(file)

    x1, y1, x2, y2 = map(float, hoop["rim_bbox"])
    hoop_x, hoop_y = map(float, hoop["rim_center"])

    cap = cv2.VideoCapture(str(video_path))

    if not cap.isOpened():
        raise RuntimeError(
            f"Cannot open video: {video_path}"
        )

    fps = cap.get(cv2.CAP_PROP_FPS)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    if fps <= 0 or width <= 0 or height <= 0:
        cap.release()
        raise RuntimeError("Invalid video properties")

    writer = cv2.VideoWriter(
        str(output_path),
        cv2.VideoWriter_fourcc(*"mp4v"),
        fps,
        (width, height),
    )

    if not writer.isOpened():
        cap.release()
        raise RuntimeError("Cannot create output video")

    # Store recent positions for visualization.
    recent_positions = deque(maxlen=45)

    frame_index = 0
    matched_frames = 0

    try:
        while True:
            success, frame = cap.read()

            if not success:
                break

            # Draw hoop bounding box in purple.
            cv2.rectangle(
                frame,
                (int(x1), int(y1)),
                (int(x2), int(y2)),
                (255, 0, 255),
                3,
            )

            # Mark hoop center in yellow.
            cv2.circle(
                frame,
                (int(hoop_x), int(hoop_y)),
                6,
                (0, 255, 255),
                -1,
            )

            cv2.putText(
                frame,
                "Detected Rim",
                (int(x1), max(25, int(y1) - 12)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.65,
                (255, 0, 255),
                2,
            )

            # Read basketball position for this frame.
            position = trajectory_by_frame.get(frame_index)

            if position is not None:
                matched_frames += 1

                ball_x = int(position[0])
                ball_y = int(position[1])

                recent_positions.append(
                    (frame_index, (ball_x, ball_y))
                )

                # Current basketball position: red dot.
                cv2.circle(
                    frame,
                    (ball_x, ball_y),
                    8,
                    (0, 0, 255),
                    -1,
                )

                cv2.putText(
                    frame,
                    "Basketball",
                    (ball_x + 12, max(20, ball_y - 10)),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.6,
                    (0, 0, 255),
                    2,
                )

            # Draw recent trajectory in cyan.
            # Do not connect across missing frames.
            for i in range(1, len(recent_positions)):
                prev_frame, prev_point = recent_positions[i - 1]
                curr_frame, curr_point = recent_positions[i]

                if curr_frame - prev_frame <= 1:
                    cv2.line(
                        frame,
                        prev_point,
                        curr_point,
                        (255, 255, 0),
                        2,
                    )

            cv2.putText(
                frame,
                f"Frame: {frame_index}",
                (15, 35),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (255, 255, 255),
                2,
            )

            writer.write(frame)
            frame_index += 1

    finally:
        cap.release()
        writer.release()

    print("\nTRAJECTORY + HOOP VISUALIZATION")
    print("--------------------------------")
    print(f"Video: {video_path.name}")
    print(f"Total frames: {frame_index}")
    print(f"Frames with tracked ball: {matched_frames}")

    if frame_index:
        coverage = matched_frames / frame_index * 100
        print(f"Tracking coverage: {coverage:.2f}%")

    print(f"Hoop center: ({hoop_x:.1f}, {hoop_y:.1f})")
    print(f"Output video: {output_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "video",
        help="Example: free_throw_01.mp4"
    )

    args = parser.parse_args()

    root = Path(__file__).resolve().parents[3]
    video_name = Path(args.video).name
    video_stem = Path(video_name).stem

    visualize_trajectory(
        video_path=root / "sample_videos" / video_name,
        output_dir=root / "outputs" / video_stem,
    )
