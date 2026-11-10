
from pathlib import Path
import csv

import cv2
from ultralytics import YOLO


def detect_basketball(video_path, output_dir):
    video_path = Path(video_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Load pretrained YOLO object detection model.
    # We use the sports ball category.
    model = YOLO("yolo26s.pt")

    ball_class_ids = [
        class_id
        for class_id, name in model.names.items()
        if name == "sports ball"
    ]

    if not ball_class_ids:
        raise RuntimeError(
            "The YOLO model does not contain a sports ball class."
        )

    ball_class_id = ball_class_ids[0]

    # Open the input basketball video.
    cap = cv2.VideoCapture(str(video_path))

    if not cap.isOpened():
        raise RuntimeError(f"Cannot open video: {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    if fps <= 0 or width <= 0 or height <= 0:
        cap.release()
        raise RuntimeError("Invalid video properties")

    output_video = output_dir / "ball_detection.mp4"
    output_csv = output_dir / "ball_detections.csv"

    writer = cv2.VideoWriter(
        str(output_video),
        cv2.VideoWriter_fourcc(*"mp4v"),
        fps,
        (width, height),
    )

    if not writer.isOpened():
        cap.release()
        raise RuntimeError("Cannot create output video")

    records = []
    frame_index = 0
    detected_frames = 0

    try:
        while True:
            success, frame = cap.read()

            if not success:
                break

            # Detect sports-ball candidates in this frame.
            result = model.predict(
                source=frame,
                classes=[ball_class_id],
                conf=0.15,
                imgsz=1280,
                verbose=False,
            )[0]

            timestamp_ms = round(frame_index * 1000 / fps)

            detections = []

            for box in result.boxes:
                confidence = float(box.conf[0])

                x1, y1, x2, y2 = [
                    float(value)
                    for value in box.xyxy[0].tolist()
                ]

                detections.append({
                    "confidence": confidence,
                    "x1": x1,
                    "y1": y1,
                    "x2": x2,
                    "y2": y2,
                })

            if detections:
                detected_frames += 1

            # Record every candidate, since there may be
            # multiple sports-ball detections in one frame.
            for detection in detections:
                x1 = detection["x1"]
                y1 = detection["y1"]
                x2 = detection["x2"]
                y2 = detection["y2"]
                confidence = detection["confidence"]

                center_x = (x1 + x2) / 2
                center_y = (y1 + y2) / 2

                records.append({
                    "frame": frame_index,
                    "timestamp_ms": timestamp_ms,
                    "confidence": round(confidence, 4),
                    "center_x": round(center_x, 2),
                    "center_y": round(center_y, 2),
                    "x1": round(x1, 2),
                    "y1": round(y1, 2),
                    "x2": round(x2, 2),
                    "y2": round(y2, 2),
                })

                # Draw a green bounding box.
                point1 = (int(x1), int(y1))
                point2 = (int(x2), int(y2))

                cv2.rectangle(
                    frame,
                    point1,
                    point2,
                    (0, 255, 0),
                    2,
                )

                cv2.putText(
                    frame,
                    f"Ball? {confidence:.2f}",
                    (point1[0], max(20, point1[1] - 10)),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.6,
                    (0, 255, 0),
                    2,
                )

            writer.write(frame)
            frame_index += 1

    finally:
        cap.release()
        writer.release()

    # Export detection results to CSV.
    columns = [
        "frame",
        "timestamp_ms",
        "confidence",
        "center_x",
        "center_y",
        "x1",
        "y1",
        "x2",
        "y2",
    ]

    with output_csv.open(
        "w",
        newline="",
        encoding="utf-8",
    ) as file:
        csv_writer = csv.DictWriter(
            file,
            fieldnames=columns,
        )

        csv_writer.writeheader()
        csv_writer.writerows(records)

    print(f"Total frames: {frame_index}")
    print(f"Frames with ball candidates: {detected_frames}")
    print(f"Total detections: {len(records)}")

    if frame_index:
        coverage = 100 * detected_frames / frame_index
        print(f"Detection coverage: {coverage:.2f}%")

    print(f"Annotated video: {output_video}")
    print(f"Detections CSV: {output_csv}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Detect basketball candidates with YOLO"
    )

    parser.add_argument(
        "video",
        help="Video filename, e.g. free_throw_01.mp4",
    )

    args = parser.parse_args()

    project_root = Path(__file__).resolve().parents[3]

    video_name = Path(args.video).name
    video_stem = Path(video_name).stem

    detect_basketball(
        video_path=(
            project_root / "sample_videos" / video_name
        ),
        output_dir=(
            project_root / "outputs" / video_stem
        ),
    )
