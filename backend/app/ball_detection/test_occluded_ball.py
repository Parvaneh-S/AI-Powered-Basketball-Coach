
import os
from pathlib import Path

import cv2
from inference_sdk import (
    InferenceHTTPClient,
    InferenceConfiguration,
)

ROOT = Path(__file__).resolve().parents[3]

VIDEO = ROOT / "sample_videos" / "free_throw_03.mp4"
OUTPUT = ROOT / "outputs" / "free_throw_03"

FRAME_NUMBER = 170

api_key = os.getenv("ROBOFLOW_API_KEY")

if not api_key:
    raise RuntimeError("ROBOFLOW_API_KEY is not configured")

cap = cv2.VideoCapture(str(VIDEO))

if not cap.isOpened():
    raise RuntimeError("Cannot open video")

cap.set(cv2.CAP_PROP_POS_FRAMES, FRAME_NUMBER)
success, frame = cap.read()
cap.release()

if not success:
    raise RuntimeError("Cannot read frame")

client = InferenceHTTPClient(
    api_url="https://serverless.roboflow.com",
    api_key=api_key,
).configure(
    InferenceConfiguration(
        api_key_transport="header"
    )
)

result = client.infer(
    frame,
    model_id="basketball-hoop-images/2",
)

print(f"\nFrame: {FRAME_NUMBER}")
print("Detections:")

for prediction in result.get("predictions", []):
    label = prediction["class"]
    confidence = prediction["confidence"]

    print(f"{label}: {confidence:.2f}")

    x = prediction["x"]
    y = prediction["y"]
    w = prediction["width"]
    h = prediction["height"]

    x1 = int(x - w / 2)
    y1 = int(y - h / 2)
    x2 = int(x + w / 2)
    y2 = int(y + h / 2)

    color = (
        (0, 255, 0)
        if label.lower() == "basketball"
        else (255, 0, 255)
    )

    cv2.rectangle(
        frame,
        (x1, y1),
        (x2, y2),
        color,
        2,
    )

    cv2.putText(
        frame,
        f"{label} {confidence:.2f}",
        (x1, max(20, y1 - 10)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.6,
        color,
        2,
    )

OUTPUT.mkdir(parents=True, exist_ok=True)

image_path = OUTPUT / "occluded_ball_test.jpg"

cv2.imwrite(str(image_path), frame)

print(f"\nSaved: {image_path}")
