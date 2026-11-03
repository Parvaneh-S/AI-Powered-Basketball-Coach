
from pathlib import Path
import cv2

# Input video
video_path = Path("sample_videos/free_throw_01.mp4")

# Output directory
output_dir = Path("outputs/frames")
output_dir.mkdir(parents=True, exist_ok=True)

# Open the video
cap = cv2.VideoCapture(str(video_path))

if not cap.isOpened():
    raise RuntimeError(f"Cannot open video: {video_path}")

# Get video properties
fps = cap.get(cv2.CAP_PROP_FPS)
frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

print(f"FPS: {fps}")
print(f"Total frames: {frame_count}")
print(f"Resolution: {width} x {height}")

if fps <= 0:
    cap.release()
    raise RuntimeError("Invalid video FPS")

print(f"Duration: {frame_count / fps:.2f} seconds")

# Extract approximately one frame per second
frame_index = 0
saved_count = 0
next_sample_time = 0.0

while True:
    success, frame = cap.read()

    if not success:
        break

    timestamp = frame_index / fps

    if timestamp >= next_sample_time:
        output_path = output_dir / f"frame_{frame_index:05d}.jpg"
        cv2.imwrite(str(output_path), frame)
        saved_count += 1
        next_sample_time += 1.0

    frame_index += 1

cap.release()

print(f"Saved {saved_count} frames to {output_dir}")
