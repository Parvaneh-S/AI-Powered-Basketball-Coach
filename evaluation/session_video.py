"""Run the local recording pipeline on repeated real demo footage or a supplied video."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile
from unittest.mock import patch

import imageio_ffmpeg

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, help="Local recording. Default uses stitched copies of free_throw_03.")
    parser.add_argument("--copies", type=int, default=3)
    parser.add_argument("--saved-demo-detections", action="store_true",
                        help="Replay real demo detector outputs at each clip's original frame offsets.")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.copies < 1 or (args.input and args.saved_demo_detections):
        parser.error("Use a positive copy count. Detection replay is available for the bundled sample.")
    with tempfile.TemporaryDirectory(prefix="shotcoach_session_") as directory, patch.dict(
        os.environ, {"SHOTCOACH_DB_PATH": str(Path(directory) / "demo.db"), "ROBOFLOW_API_KEY": "",
                     "OPENAI_API_KEY": "", "GEMINI_API_KEY": "", "OMP_NUM_THREADS": "2"},
    ):
        import cv2
        import pandas as pd
        import torch

        cv2.setNumThreads(2)
        torch.set_num_threads(2)
        folder = Path(directory)
        demo = ROOT / "sample_videos" / "free_throw_03.mp4"
        clip = args.input.resolve() if args.input else folder / "stitched.mp4"
        if not args.input:
            concatenation = folder / "inputs.txt"
            concatenation.write_text("".join(f"file '{demo.as_posix()}'\n" for _ in range(args.copies)),
                                     encoding="utf-8")
            subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-f", "concat", "-safe", "0", "-i",
                            str(concatenation), "-c", "copy", str(clip)], check=True, capture_output=True)

        from backend.app.agent.coaching_agent import coach
        from backend.app.agent.evidence import load_shots
        from backend.app.agent.video import shot_frames
        from backend.app.database.models import engine
        from backend.app.pipeline import video_pipeline

        def replay_detections(video_path, output_dir):
            track = pd.read_csv(ROOT / "outputs" / "free_throw_03" / "ball_detections.csv")
            camera = cv2.VideoCapture(str(demo))
            try:
                count = int(camera.get(cv2.CAP_PROP_FRAME_COUNT))
                fps = camera.get(cv2.CAP_PROP_FPS)
            finally:
                camera.release()
            slices = []
            for index in range(args.copies):
                shifted = track.copy()
                shifted["frame"] += index * count
                shifted["timestamp_ms"] = (shifted["frame"] * 1000 / fps).round().astype(int)
                slices.append(shifted)
            pd.concat(slices, ignore_index=True).to_csv(output_dir / "ball_detections.csv", index=False)

        with patch.object(video_pipeline, "ROOT", folder):
            if args.saved_demo_detections:
                with patch.object(video_pipeline, "detect_basketball", replay_detections):
                    result = video_pipeline.process_uploaded_video(str(clip), "RecordingVerification")
            else:
                result = video_pipeline.process_uploaded_video(str(clip), "RecordingVerification")
        shots = load_shots("RecordingVerification")
        feedback = coach("RecordingVerification", "How did I do this session?", selected=result["video_id"],
                         session_id=result["session_id"], persist=False, memory_state=("", {
                             "goal": "", "experience": "", "preferences": {}, "recommendations": [], "reports": [],
                         }))
        record = {
            "footage": "local input video" if args.input else f"{args.copies} stitched copies of real demo footage",
            "ball_detection": "saved detections from the real demo" if args.saved_demo_detections else "fresh YOLO inference",
            "pose_tracking": "fresh MediaPipe inference",
            "hoop_detection": "disabled for this local check",
            "detected_attempts": len(shots), "review_candidate_count": result["review_candidate_count"],
            "attempts": [{
                "number": shot.shot_number,
                "events": shot.analysis["shot_events"],
                "outcome": shot.outcome,
                "decoded_release": [ref.timestamp_s for ref, _ in shot_frames(shot, ("release",), root=folder)],
            } for shot in shots],
            "coaching_message": feedback.message, "session_summary": feedback.session_summary,
        }
        engine.dispose()
    print(json.dumps(record, indent=2))
    if args.output:
        args.output.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
