
from pathlib import Path
import json
import cv2


import argparse

parser = argparse.ArgumentParser(
    description="Manually annotate a basketball shot"
)

parser.add_argument(
    "video",
    help="Video filename, e.g. free_throw_02.mp4"
)

args = parser.parse_args()

video_name = Path(args.video).name
video_stem = Path(video_name).stem

VIDEO = Path("sample_videos") / video_name
OUTPUT = Path("outputs") / video_stem / "shot_annotations.json"


cap = cv2.VideoCapture(str(VIDEO))

if not cap.isOpened():
    raise RuntimeError(f"Cannot open {VIDEO}")

fps = cap.get(cv2.CAP_PROP_FPS)
total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

if fps <= 0 or total_frames <= 0:
    cap.release()
    raise RuntimeError("Invalid video properties")

frame_index = 0
start_frame = None
release_frame = None
end_frame = None
outcome = "unknown"

print("Controls:")
print("D = next frame")
print("A = previous frame")
print("S = mark shot start")
print("R = mark ball release")
print("E = mark shot end")
print("M = made, X = missed, U = unknown")
print("ENTER = save, Q = quit")


def display_frame(index):
    cap.set(cv2.CAP_PROP_POS_FRAMES, index)
    success, frame = cap.read()

    if not success:
        raise RuntimeError(f"Cannot read frame {index}")

    height, width = frame.shape[:2]
    scale = min(1000 / width, 700 / height, 1.0)

    frame = cv2.resize(
        frame,
        (int(width * scale), int(height * scale))
    )

    lines = [
        f"Frame: {index}/{total_frames - 1}"
        f" | Time: {index / fps:.3f}s",
        f"Start: {start_frame} | Release: {release_frame}"
        f" | End: {end_frame}",
        f"Outcome: {outcome}",
        "A/D: frames | S: start | R: release | E: end",
        "M: made | X: missed | U: unknown",
        "ENTER: save | Q: quit",
    ]

    for i, line in enumerate(lines):
        y = 30 + i * 28

        cv2.putText(
            frame, line, (15, y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55, (255, 255, 255), 2,
            cv2.LINE_AA
        )

        cv2.putText(
            frame, line, (15, y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55, (0, 0, 0), 1,
            cv2.LINE_AA
        )

    cv2.imshow("Shot Annotation", frame)


try:
    while True:
        display_frame(frame_index)

        key = cv2.waitKey(0) & 0xFF

        if key == ord("d"):
            frame_index = min(
                frame_index + 1, total_frames - 1
            )

        elif key == ord("a"):
            frame_index = max(frame_index - 1, 0)

        elif key == ord("s"):
            start_frame = frame_index
            print(f"Start: frame {start_frame}")

        elif key == ord("r"):
            release_frame = frame_index
            print(f"Release: frame {release_frame}")

        elif key == ord("e"):
            end_frame = frame_index
            print(f"End: frame {end_frame}")

        elif key == ord("m"):
            outcome = "made"

        elif key == ord("x"):
            outcome = "missed"

        elif key == ord("u"):
            outcome = "unknown"

        elif key == 13:  # Enter
            if None in (start_frame, release_frame, end_frame):
                print("Mark start, release, and end first.")
                continue

            if not (
                0 <= start_frame
                < release_frame
                < end_frame
                < total_frames
            ):
                print("Required: start < release < end.")
                continue

            annotation = {
                "video": VIDEO.name,
                "shot_id": 1,
                "start_frame": start_frame,
                "release_frame": release_frame,
                "end_frame": end_frame,
                "start_time_ms": round(
                    start_frame * 1000 / fps
                ),
                "release_time_ms": round(
                    release_frame * 1000 / fps
                ),
                "end_time_ms": round(
                    end_frame * 1000 / fps
                ),
                "shooting_arm": "right",
                "outcome": outcome,
            }

            OUTPUT.parent.mkdir(
                parents=True, exist_ok=True
            )

            with OUTPUT.open(
                "w", encoding="utf-8"
            ) as file:
                json.dump(annotation, file, indent=2)

            print(f"Annotation saved to {OUTPUT}")
            print(json.dumps(annotation, indent=2))
            break

        elif key == ord("q"):
            print("Exited without saving.")
            break

finally:
    cap.release()
    cv2.destroyAllWindows()
