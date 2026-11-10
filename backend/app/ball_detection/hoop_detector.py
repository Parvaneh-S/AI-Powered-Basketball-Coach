
import argparse
import json
import os
from pathlib import Path

import cv2
from inference_sdk import (
    InferenceHTTPClient,
    InferenceConfiguration,
)


MODEL_ID = "basketball-hoop-images/2"


def detect_hoop(video_path, output_dir, frame_number=40):
    video_path = Path(video_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    api_key = os.getenv("ROBOFLOW_API_KEY")

    if not api_key:
        raise RuntimeError(
            "ROBOFLOW_API_KEY environment variable is missing."
        )

    cap = cv2.VideoCapture(str(video_path))

    if not cap.isOpened():
        raise RuntimeError(f"Cannot open video: {video_path}")

    try:
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_number)
        success, frame = cap.read()
    finally:
        cap.release()

    if not success:
        raise RuntimeError(
            f"Cannot read frame {frame_number}"
        )

    client = InferenceHTTPClient(
        api_url="https://serverless.roboflow.com",
        api_key=api_key,
    ).configure(
        InferenceConfiguration(
            api_key_transport="header"
        )
    )

    # Send one frame to the hosted model.
    result = client.infer(
        frame,
        model_id=MODEL_ID,
    )

    # Ignore predictions belonging to other classes.
    rim_predictions = [
        prediction
        for prediction in result.get("predictions", [])
        if prediction.get("class", "").lower() == "rim"
    ]

    if not rim_predictions:
        print("No rim detected.")
        print("Returned classes:", [
            p.get("class")
            for p in result.get("predictions", [])
        ])
        return

    # For this MVP, choose the most confident rim candidate.
    rim = max(
        rim_predictions,
        key=lambda prediction: prediction["confidence"],
    )

    center_x = float(rim["x"])
    center_y = float(rim["y"])
    width = float(rim["width"])
    height = float(rim["height"])

    # Roboflow uses center-based bounding boxes.
    x1 = center_x - width / 2
    y1 = center_y - height / 2
    x2 = center_x + width / 2
    y2 = center_y + height / 2

    annotation = {
        "video": video_path.name,
        "method": "roboflow_hosted_inference",
        "model_id": MODEL_ID,
        "reference_frame": frame_number,
        "class": rim["class"],
        "confidence": round(float(rim["confidence"]), 4),
        "rim_bbox": [
            round(x1, 2),
            round(y1, 2),
            round(x2, 2),
            round(y2, 2),
        ],
        "rim_center": [
            round(center_x, 2),
            round(center_y, 2),
        ],
        "rim_width_px": round(width, 2),
        "rim_height_px": round(height, 2),
    }

    json_path = output_dir / "hoop_detection.json"

    with json_path.open("w", encoding="utf-8") as file:
        json.dump(annotation, file, indent=4)

    # Visual verification.
    annotated_frame = frame.copy()

    cv2.rectangle(
        annotated_frame,
        (int(x1), int(y1)),
        (int(x2), int(y2)),
        (255, 0, 255),
        3,
    )

    cv2.putText(
        annotated_frame,
        f"Rim {rim['confidence']:.2f}",
        (int(x1), max(20, int(y1) - 10)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.7,
        (255, 0, 255),
        2,
    )

    image_path = output_dir / "hoop_detection.jpg"

    cv2.imwrite(str(image_path), annotated_frame)

    print("Hoop detected successfully!")
    print(json.dumps(annotation, indent=4))
    print(f"Saved JSON: {json_path}")
    print(f"Saved image: {image_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("video")
    parser.add_argument(
        "--frame",
        type=int,
        default=40,
    )

    args = parser.parse_args()

    root = Path(__file__).resolve().parents[3]
    video_name = Path(args.video).name
    video_stem = Path(video_name).stem

    detect_hoop(
        video_path=root / "sample_videos" / video_name,
        output_dir=root / "outputs" / video_stem,
        frame_number=args.frame,
    )
