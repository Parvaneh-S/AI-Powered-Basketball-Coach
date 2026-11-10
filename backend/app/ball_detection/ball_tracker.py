
from pathlib import Path
import argparse

import cv2
import numpy as np
import pandas as pd


def remove_stationary_detections(
    detections,
    position_tolerance=12,
    min_stationary_frames=15,
):
    """
    Find detections that repeatedly appear at nearly
    the same location across many different frames.
    """

    detections = detections.copy()

    detections["stationary"] = False

    if detections.empty:
        return detections

    points = detections[
        ["center_x", "center_y"]
    ].to_numpy(dtype=float)

    # Build clusters of nearby detections.
    clusters = []

    for index, point in enumerate(points):
        matched_cluster = None

        for cluster in clusters:
            distance = np.linalg.norm(
                point - cluster["center"]
            )

            if distance <= position_tolerance:
                matched_cluster = cluster
                break

        if matched_cluster is None:
            clusters.append({
                "center": point.copy(),
                "indices": [index],
            })
        else:
            matched_cluster["indices"].append(index)

            cluster_points = points[
                matched_cluster["indices"]
            ]

            matched_cluster["center"] = (
                cluster_points.mean(axis=0)
            )

    # Mark locations observed in many distinct frames.
    for cluster in clusters:
        indices = cluster["indices"]

        frame_count = detections.iloc[
            indices
        ]["frame"].nunique()

        if frame_count >= min_stationary_frames:
            detections.iloc[
                indices,
                detections.columns.get_loc("stationary")
            ] = True

    return detections


def track_ball(
    video_path,
    csv_path,
    output_dir,
    max_distance=200,
):
    video_path = Path(video_path)
    csv_path = Path(csv_path)
    output_dir = Path(output_dir)

    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    detections = pd.read_csv(csv_path)

    if detections.empty:
        print("No ball detections found.")
        return

    detections = remove_stationary_detections(
        detections
    )

    filtered = detections[
        ~detections["stationary"]
    ].copy()

    print(
        "Stationary detections removed:",
        int(detections["stationary"].sum())
    )

    print(
        "Remaining detections:",
        len(filtered)
    )

    video = cv2.VideoCapture(
        str(video_path)
    )

    if not video.isOpened():
        raise RuntimeError(
            f"Cannot open video: {video_path}"
        )

    fps = video.get(cv2.CAP_PROP_FPS)
    width = int(
        video.get(cv2.CAP_PROP_FRAME_WIDTH)
    )
    height = int(
        video.get(cv2.CAP_PROP_FRAME_HEIGHT)
    )

    if fps <= 0 or width <= 0 or height <= 0:
        video.release()
        raise RuntimeError("Invalid video properties")

    output_video = (
        output_dir / "ball_tracking.mp4"
    )

    output_csv = (
        output_dir / "ball_trajectory.csv"
    )

    writer = cv2.VideoWriter(
        str(output_video),
        cv2.VideoWriter_fourcc(*"mp4v"),
        fps,
        (width, height),
    )

    if not writer.isOpened():
        video.release()
        raise RuntimeError(
            "Cannot create tracking video"
        )

    previous_position = None
    trajectory = []
    frame_index = 0

    grouped = {
        int(frame): group
        for frame, group in filtered.groupby("frame")
    }

    try:
        while True:
            success, frame = video.read()

            if not success:
                break

            candidates = grouped.get(frame_index)

            selected = None

            if candidates is not None:
                if previous_position is None:
                    # Initial candidate: highest confidence
                    selected = candidates.loc[
                        candidates["confidence"].idxmax()
                    ]

                else:
                    candidate_positions = candidates[
                        ["center_x", "center_y"]
                    ].to_numpy(dtype=float)

                    distances = np.linalg.norm(
                        candidate_positions
                        - previous_position,
                        axis=1,
                    )

                    nearest = int(
                        np.argmin(distances)
                    )

                    if distances[nearest] <= max_distance:
                        selected = candidates.iloc[nearest]

            if selected is not None:
                x = float(selected["center_x"])
                y = float(selected["center_y"])

                previous_position = np.array(
                    [x, y],
                    dtype=float,
                )

                trajectory.append({
                    "frame": frame_index,
                    "timestamp_ms": round(
                        frame_index * 1000 / fps
                    ),
                    "center_x": round(x, 2),
                    "center_y": round(y, 2),
                    "confidence": float(
                        selected["confidence"]
                    ),
                })

                cv2.circle(
                    frame,
                    (int(x), int(y)),
                    7,
                    (0, 0, 255),
                    -1,
                )

                cv2.putText(
                    frame,
                    "Tracked ball",
                    (int(x) + 10, int(y) - 10),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.6,
                    (0, 0, 255),
                    2,
                )

            writer.write(frame)
            frame_index += 1

    finally:
        video.release()
        writer.release()

    pd.DataFrame(
        trajectory,
        columns=[
            "frame",
            "timestamp_ms",
            "center_x",
            "center_y",
            "confidence",
        ],
    ).to_csv(
        output_csv,
        index=False,
    )

    print(
        f"Tracked frames: {len(trajectory)}"
    )

    print(
        f"Tracking video: {output_video}"
    )

    print(
        f"Trajectory CSV: {output_csv}"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()

    parser.add_argument("video")

    args = parser.parse_args()

    root = Path(__file__).resolve().parents[3]

    video_name = Path(args.video).name
    stem = Path(video_name).stem

    track_ball(
        video_path=(
            root / "sample_videos" / video_name
        ),
        csv_path=(
            root / "outputs" / stem
            / "ball_detections.csv"
        ),
        output_dir=(
            root / "outputs" / stem
        ),
    )
