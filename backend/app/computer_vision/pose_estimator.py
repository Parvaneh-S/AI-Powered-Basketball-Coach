
from pathlib import Path
import csv
import json
from tempfile import NamedTemporaryFile

import cv2
import mediapipe as mp

from backend.app.measurements.joint_angles import JOINT_LANDMARKS, POSE_FILENAME, calculate_angle


SKELETON_CONNECTIONS = [
    (11, 13), (13, 15),
    (12, 14), (14, 16),
    (11, 12),
    (11, 23), (12, 24),
    (23, 24),
    (23, 25), (25, 27),
    (24, 26), (26, 28),
]

COACHING_LANDMARKS = sorted({index for side in JOINT_LANDMARKS.values()
                             for joint in side.values() for index in joint})



def get_joint_angle(
    landmarks, a, b, c, width, height, min_visibility=0.5
):
    """
    Calculate the 2D joint angle using pixel coordinates.

    a, b, c: MediaPipe landmark indices
    b: angle vertex
    width, height: video dimensions
    """
    points = [landmarks[i] for i in (a, b, c)]

    if any(p.visibility < min_visibility for p in points):
        return None

    return calculate_angle(
        (points[0].x * width, points[0].y * height),
        (points[1].x * width, points[1].y * height),
        (points[2].x * width, points[2].y * height),
    )



def draw_angle(frame, landmarks, landmark_index, angle, label):
    """Draw a joint-angle label beside the joint."""
    if angle is None:
        return

    height, width = frame.shape[:2]
    joint = landmarks[landmark_index]

    x = int(joint.x * width)
    y = int(joint.y * height)

    cv2.putText(
        frame,
        f"{label}: {angle:.1f} deg",
        (x + 12, y - 12),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.6,
        (255, 255, 0),
        2,
        cv2.LINE_AA,
    )


def process_video(input_path, output_path, model_path, csv_path):
    cap = cv2.VideoCapture(str(input_path))

    if not cap.isOpened():
        raise RuntimeError(f"Cannot open video: {input_path}")

    fps = cap.get(cv2.CAP_PROP_FPS)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    if fps <= 0 or width <= 0 or height <= 0:
        cap.release()
        raise RuntimeError("Invalid video properties")

    csv_path = Path(csv_path)
    csv_path.parent.mkdir(parents=True, exist_ok=True)

    writer = None
    if output_path is not None:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        writer = cv2.VideoWriter(str(output_path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height))
        if not writer.isOpened():
            cap.release()
            writer.release()
            raise RuntimeError("Cannot create output video")

    options = mp.tasks.vision.PoseLandmarkerOptions(
        base_options=mp.tasks.BaseOptions(
            model_asset_path=str(model_path)
        ),
        running_mode=mp.tasks.vision.RunningMode.VIDEO,
        num_poses=1,
    )

    measurements = []
    pose_frames = {}
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

                timestamp_ms = round(frame_index * 1000 / fps)

                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

                mp_image = mp.Image(
                    image_format=mp.ImageFormat.SRGB,
                    data=rgb,
                )

                result = landmarker.detect_for_video(
                    mp_image, timestamp_ms
                )

                # Default: no valid measurements for this frame
                left_elbow = None
                right_elbow = None
                left_knee = None
                right_knee = None
                wrists = {}

                if result.pose_landmarks:
                    detected_frames += 1
                    landmarks = result.pose_landmarks[0]
                    pose_frames[frame_index] = {
                        index: [round(landmarks[index].x, 6), round(landmarks[index].y, 6)]
                        for index in COACHING_LANDMARKS if landmarks[index].visibility >= 0.5
                    }
                    if writer is None:
                        frame_index += 1
                        continue

                    left_elbow = get_joint_angle(
                        landmarks, *JOINT_LANDMARKS["left"]["elbow"], width, height
                    )

                    right_elbow = get_joint_angle(
                        landmarks, *JOINT_LANDMARKS["right"]["elbow"], width, height
                    )

                    left_knee = get_joint_angle(
                        landmarks, *JOINT_LANDMARKS["left"]["knee"], width, height
                    )

                    right_knee = get_joint_angle(
                        landmarks, *JOINT_LANDMARKS["right"]["knee"], width, height
                    )

                    # Wrist positions in pixels, used to find the
                    # moment the ball leaves the hands.
                    for side, index in (("left", 15), ("right", 16)):
                        wrist = landmarks[index]
                        if wrist.visibility >= 0.5:
                            wrists[f"{side}_wrist_x"] = round(
                                wrist.x * width, 1
                            )
                            wrists[f"{side}_wrist_y"] = round(
                                wrist.y * height, 1
                            )


                    # Draw skeleton
                    for start, end in SKELETON_CONNECTIONS:
                        a = landmarks[start]
                        b = landmarks[end]

                        if a.visibility > 0.5 and b.visibility > 0.5:
                            point_a = (
                                int(a.x * width),
                                int(a.y * height),
                            )
                            point_b = (
                                int(b.x * width),
                                int(b.y * height),
                            )

                            cv2.line(
                                frame, point_a, point_b,
                                (0, 255, 0), 3
                            )

                    for landmark in landmarks:
                        if landmark.visibility > 0.5:
                            x = int(landmark.x * width)
                            y = int(landmark.y * height)

                            cv2.circle(
                                frame, (x, y), 4,
                                (0, 0, 255), -1
                            )

                    # Draw measured joint angles
                    draw_angle(
                        frame, landmarks, 13,
                        left_elbow, "L Elbow"
                    )
                    draw_angle(
                        frame, landmarks, 14,
                        right_elbow, "R Elbow"
                    )
                    draw_angle(
                        frame, landmarks, 25,
                        left_knee, "L Knee"
                    )
                    draw_angle(
                        frame, landmarks, 26,
                        right_knee, "R Knee"
                    )

                # Store one record for every frame
                measurements.append({
                    "frame": frame_index,
                    "timestamp_ms": timestamp_ms,
                    "left_elbow_angle": left_elbow,
                    "right_elbow_angle": right_elbow,
                    "left_knee_angle": left_knee,
                    "right_knee_angle": right_knee,
                    **wrists,
                })

                if writer is not None:
                    writer.write(frame)
                frame_index += 1

    finally:
        cap.release()
        if writer is not None:
            writer.release()

    # Publish only a complete pose pass. Readers may be serving an older analysis.
    with NamedTemporaryFile(mode="w", encoding="utf-8", dir=csv_path.parent, delete=False) as stream:
        temporary = Path(stream.name)
    try:
        temporary.write_text(json.dumps(pose_frames, separators=(",", ":")), encoding="utf-8")
        temporary.replace(csv_path.with_name(POSE_FILENAME))
    finally:
        temporary.unlink(missing_ok=True)

    if writer is None:
        print(f"Saved landmarks for {detected_frames} frames to {csv_path.with_name(POSE_FILENAME)}")
        return

    # Save measurements after processing
    with open(csv_path, "w", newline="", encoding="utf-8") as file:
        columns = [
            "frame",
            "timestamp_ms",
            "left_elbow_angle",
            "right_elbow_angle",
            "left_knee_angle",
            "right_knee_angle",
            "left_wrist_x",
            "left_wrist_y",
            "right_wrist_x",
            "right_wrist_y",
        ]

        csv_writer = csv.DictWriter(file, fieldnames=columns)
        csv_writer.writeheader()
        csv_writer.writerows(measurements)

    print(f"Processed frames: {frame_index}")
    print(f"Frames with detected pose: {detected_frames}")
    print(f"Annotated video: {output_path}")
    print(f"Measurements CSV: {csv_path}")



if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Analyze basketball video with MediaPipe"
    )

    parser.add_argument(
        "video",
        help="Video filename inside sample_videos/ or, with --landmarks-only, data/uploads/"
    )
    parser.add_argument("--landmarks-only", action="store_true",
                        help="Save pose coordinates for existing sample analysis.")

    args = parser.parse_args()

    project_root = Path(__file__).resolve().parents[3]

    video_name = Path(args.video).name
    video_stem = Path(video_name).stem

    input_path = project_root / "sample_videos" / video_name
    if args.landmarks_only and not input_path.is_file():
        input_path = project_root / "data" / "uploads" / video_name
    output_dir = project_root / "outputs" / video_stem

    if not input_path.is_file():
        parser.error(f"Video not found: {input_path}")

    process_video(
        input_path=input_path,
        output_path=None if args.landmarks_only else output_dir / "annotated_angles.mp4",
        model_path=(
            project_root
            / "backend/models/pose_landmarker_lite.task"
        ),
        csv_path=output_dir / "joint_angles.csv",
    )

