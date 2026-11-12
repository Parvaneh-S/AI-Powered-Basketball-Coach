
import json
from pathlib import Path

import cv2
from ultralytics import YOLO


ROOT = Path(__file__).resolve().parents[3]
VIDEO = ROOT / "sample_videos" / "free_throw_03.mp4"
OUTPUT_DIR = ROOT / "outputs" / "free_throw_03"

with (OUTPUT_DIR / "hoop_detection.json").open() as file:
    hoop = json.load(file)

cap = cv2.VideoCapture(str(VIDEO))
model = YOLO("yolo26s.pt")

# Find the sports ball class.
ball_class_id = next(
    index
    for index, name in model.names.items()
    if name == "sports ball"
)

x1, y1, x2, y2 = map(int, hoop["rim_bbox"])

frame_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
frame_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

# Add context around the detected rim.
margin = 180

crop_x1 = max(0, x1 - margin)
crop_y1 = max(0, y1 - margin)
crop_x2 = min(frame_width, x2 + margin)
crop_y2 = min(frame_height, y2 + margin)

for frame_number in range(160, 181):
    cap.set(cv2.CAP_PROP_POS_FRAMES, frame_number)
    success, frame = cap.read()

    if not success:
        continue

    crop = frame[
        crop_y1:crop_y2,
        crop_x1:crop_x2
    ]

    results = model.predict(
        crop,
        classes=[ball_class_id],
        conf=0.10,
        imgsz=1280,
        verbose=False,
    )[0]

    # Draw detections onto the original full frame.
    for box in results.boxes:
        bx1, by1, bx2, by2 = box.xyxy[0].tolist()

        bx1 += crop_x1
        bx2 += crop_x1
        by1 += crop_y1
        by2 += crop_y1

        confidence = float(box.conf[0])

        cv2.rectangle(
            frame,
            (int(bx1), int(by1)),
            (int(bx2), int(by2)),
            (0, 255, 0),
            2,
        )

        cv2.putText(
            frame,
            f"Ball {confidence:.2f}",
            (int(bx1), max(20, int(by1) - 10)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (0, 255, 0),
            2,
        )

    output_path = (
        OUTPUT_DIR
        / f"hoop_region_frame_{frame_number}.jpg"
    )

    cv2.imwrite(str(output_path), frame)

    print(
        f"Frame {frame_number}: "
        f"{len(results.boxes)} detections"
    )

cap.release()
print("Hoop-region detection test complete.")
