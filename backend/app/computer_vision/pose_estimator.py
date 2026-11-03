
from pathlib import Path
import cv2
import mediapipe as mp


# Connections between important body landmarks
SKELETON_CONNECTIONS = [
    (11, 13), (13, 15),  # Left arm
    (12, 14), (14, 16),  # Right arm
    (11, 12),            # Shoulders
    (11, 23), (12, 24),  # Torso
    (23, 24),            # Hips
    (23, 25), (25, 27),  # Left leg
    (24, 26), (26, 28),  # Right leg
]


def process_video(input_path, output_path, model_path):
    cap = cv2.VideoCapture(str(input_path))

    if not cap.isOpened():
        raise RuntimeError(f"Cannot open video: {input_path}")

    fps = cap.get(cv2.CAP_PROP_FPS)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    if fps <= 0 or width <= 0 or height <= 0:
        cap.release()
        raise RuntimeError("Invalid video properties")

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    writer = cv2.VideoWriter(
        str(output_path),
        cv2.VideoWriter_fourcc(*"mp4v"),
        fps,
        (width, height),
    )

    if not writer.isOpened():
        cap.release()
        raise RuntimeError("Cannot create output video")

    options = mp.tasks.vision.PoseLandmarkerOptions(
        base_options=mp.tasks.BaseOptions(
            model_asset_path=str(model_path)
        ),
        running_mode=mp.tasks.vision.RunningMode.VIDEO,
        num_poses=1,
    )

    frame_index = 0
    detected_frames = 0

    try:
        with mp.tasks.vision.PoseLandmarker.create_from_options(
            options
        ) as landmarker:

            while True:
                success, frame = cap.read()

                if not success:
                    break

                # OpenCV uses BGR; MediaPipe expects RGB.
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

                mp_image = mp.Image(
                    image_format=mp.ImageFormat.SRGB,
                    data=rgb,
                )

                timestamp_ms = round(frame_index * 1000 / fps)

                result = landmarker.detect_for_video(
                    mp_image, timestamp_ms
                )

                if result.pose_landmarks:
                    detected_frames += 1
                    landmarks = result.pose_landmarks[0]

                    # Draw body connections
                    for start, end in SKELETON_CONNECTIONS:
                        a = landmarks[start]
                        b = landmarks[end]

                        if a.visibility > 0.5 and b.visibility > 0.5:
                            point_a = (int(a.x * width), int(a.y * height))
                            point_b = (int(b.x * width), int(b.y * height))

                            cv2.line(
                                frame, point_a, point_b,
                                (0, 255, 0), 3
                            )

                    # Draw visible landmarks
                    for landmark in landmarks:
                        if landmark.visibility > 0.5:
                            x = int(landmark.x * width)
                            y = int(landmark.y * height)

                            cv2.circle(
                                frame, (x, y), 4,
                                (0, 0, 255), -1
                            )

                writer.write(frame)
                frame_index += 1

    finally:
        cap.release()
        writer.release()

    print(f"Processed frames: {frame_index}")
    print(f"Frames with detected pose: {detected_frames}")
    print(f"Output saved to: {output_path}")


if __name__ == "__main__":
    project_root = Path(__file__).resolve().parents[3]

    process_video(
        input_path=project_root / "sample_videos/free_throw_01.mp4",
        output_path=project_root / "outputs/annotated_video.mp4",
        model_path=project_root / "backend/models/pose_landmarker_lite.task",
    )
