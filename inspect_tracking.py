
from pathlib import Path
import cv2

video_path = Path(
    "outputs/free_throw_03/ball_tracking.mp4"
)

output_dir = Path(
    "outputs/free_throw_03/inspection"
)

output_dir.mkdir(parents=True, exist_ok=True)

cap = cv2.VideoCapture(str(video_path))

if not cap.isOpened():
    raise RuntimeError("Cannot open tracking video")

# Frames we want to inspect
frames_to_check = [160, 161, 162, 163, 164, 165, 166]

for frame_number in frames_to_check:
    cap.set(cv2.CAP_PROP_POS_FRAMES, frame_number)

    success, frame = cap.read()

    if success:
        output_path = (
            output_dir / f"tracking_frame_{frame_number}.jpg"
        )

        cv2.imwrite(str(output_path), frame)

        print(f"Saved frame {frame_number}")

cap.release()

print("Inspection complete!")
