
from pathlib import Path

import cv2
import numpy as np


video_path = Path("sample_videos/free_throw_03.mp4")
output_path = Path(
    "outputs/free_throw_03/hoop_frames_contact_sheet.jpg"
)

cap = cv2.VideoCapture(str(video_path))

if not cap.isOpened():
    raise RuntimeError("Cannot open video")

frames = []

for frame_number in range(163, 181):
    cap.set(cv2.CAP_PROP_POS_FRAMES, frame_number)
    success, frame = cap.read()

    if not success:
        continue

    # Display a resized copy of each original frame.
    thumbnail = cv2.resize(frame, (320, 180))

    cv2.putText(
        thumbnail,
        f"Frame {frame_number}",
        (10, 25),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.6,
        (255, 255, 255),
        2,
    )

    frames.append(thumbnail)

cap.release()

if not frames:
    raise RuntimeError("No frames extracted")

columns = 3
rows = []

for start in range(0, len(frames), columns):
    row_frames = frames[start:start + columns]

    while len(row_frames) < columns:
        row_frames.append(
            np.zeros_like(frames[0])
        )

    rows.append(np.hstack(row_frames))

contact_sheet = np.vstack(rows)

output_path.parent.mkdir(
    parents=True,
    exist_ok=True
)

cv2.imwrite(str(output_path), contact_sheet)

print(f"Saved: {output_path}")
