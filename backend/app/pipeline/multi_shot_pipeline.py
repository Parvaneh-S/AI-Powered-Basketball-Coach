"""
Analyse a video that contains several free throws.

Steps:
    1. Convert the video to 30 fps, at most 1920 px, normal colours.
    2. Find every shot with MediaPipe Pose (hands above the head).
    3. Cut one short clip per shot.
    4. Run the single-shot pipeline on each clip. All shots are
       saved in one practice session.

A shot that fails is reported and the remaining shots continue.
"""

import argparse
import json
import logging
import shutil
import time
from pathlib import Path
from uuid import uuid4

import cv2

from backend.app.database.duplicates import (
    DuplicateVideoError,
    file_sha256,
    find_duplicate,
)
from backend.app.database.sessions import validate_session
from backend.app.pipeline.video_input import (
    SUPPORTED_EXTENSIONS,
    UnsupportedVideoError,
    WrongUploadModeError,
)
from backend.app.pipeline.video_pipeline import (
    ROOT,
    process_uploaded_video,
)
from backend.app.shot_detection.multi_shot import (
    clip_window,
    cut_clip,
    find_shots_in_video,
    format_time,
)


class NoShotsFoundError(ValueError):
    """Raised when no shot can be found in the video."""


def no_progress(stage, done=0, total=0):
    """Default progress callback: do nothing."""


def count_frames(video_path):
    capture = cv2.VideoCapture(str(video_path))
    total = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    capture.release()
    return total


def process_multi_shot_video(
    video_path,
    player_name,
    shooting_arm="right",
    original_filename=None,
    session_id=None,
    progress=no_progress,
):
    """
    Find, cut and analyse every shot in the video.

    progress(stage, done, total) is called as the work goes on,
    so the app can show how far it is.

    Returns a summary with one entry per shot.
    """

    source = Path(video_path).resolve()
    player_name = player_name.strip()

    if not source.is_file():
        raise FileNotFoundError(f"Video file not found: {source}")

    if source.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise UnsupportedVideoError(
            "Only MP4 and MOV videos are supported."
        )

    if not player_name:
        raise ValueError("Player name cannot be empty.")

    if shooting_arm not in ("left", "right"):
        raise ValueError("shooting_arm must be 'left' or 'right'.")

    if original_filename is None:
        original_filename = source.name

    validate_session(player_name, session_id)

    # The same video for the same player is analysed only once.
    progress("Checking for duplicates")
    source_sha256 = file_sha256(source)
    existing = find_duplicate(player_name, source_sha256)

    if existing is not None:
        raise DuplicateVideoError(existing)

    work_dir = ROOT / "data" / "uploads" / f"multi_{uuid4().hex[:12]}"
    work_dir.mkdir(parents=True)

    started = time.perf_counter()

    try:
        # 1 + 2. Convert and find the shots.
        progress("Converting the video and finding the shots")
        analysis_video, fps, shots = find_shots_in_video(
            source, work_dir
        )

        if not shots:
            raise NoShotsFoundError(
                "No shots were found in the video. Make sure "
                "the player's whole body is visible."
            )

        if len(shots) == 1:
            raise WrongUploadModeError(
                "Only one shot was found in this video. "
                "Please upload it as 'One shot'."
            )

        total_frames = count_frames(analysis_video)

        # 3 + 4. Cut and analyse each shot.
        results = []

        for shot in shots:
            number = shot["shot"]
            time_in_video = format_time(shot["hands_up_frame"] / fps)

            progress(
                f"Analysing shot {number} of {len(shots)}",
                number - 1,
                len(shots),
            )

            entry = {
                "shot": number,
                "time_in_video": time_in_video,
            }

            try:
                first, last = clip_window(shot, total_frames, fps)
                clip = work_dir / f"shot_{number:02d}.mp4"
                cut_clip(analysis_video, clip, first, last)

                result = process_uploaded_video(
                    video_path=str(clip),
                    player_name=player_name,
                    shooting_arm=shooting_arm,
                    original_filename=(
                        f"{original_filename} "
                        f"(shot {number}, {time_in_video})"
                    ),
                    session_id=session_id,
                    source_sha256=source_sha256,
                )

                # The first shot creates the session if needed;
                # all other shots join it.
                session_id = result["session_id"]

                entry.update({
                    "status": "success",
                    "video_id": result["video_id"],
                    "outcome": result["shot_outcome"].get(
                        "prediction", "unknown"
                    ),
                })

            except Exception as error:
                logging.exception(
                    "Shot %s of %s failed", number, original_filename
                )
                entry.update({
                    "status": "failed",
                    "error": str(error),
                })

            results.append(entry)

        progress("Done", len(shots), len(shots))

        return {
            "status": "success",
            "player_name": player_name,
            "session_id": session_id,
            "shots_found": len(shots),
            "shots_analysed": sum(
                1 for r in results if r["status"] == "success"
            ),
            "processing_seconds": round(
                time.perf_counter() - started
            ),
            "shots": results,
        }

    finally:
        # Each clip was copied for its own analysis; the work
        # folder (converted video, clips) is no longer needed.
        shutil.rmtree(work_dir, ignore_errors=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Analyse every shot in a multi-shot video"
    )
    parser.add_argument("video_path")
    parser.add_argument("player_name")
    parser.add_argument(
        "--shooting-arm", choices=["left", "right"], default="right"
    )
    parser.add_argument("--session-id", type=int, default=None)
    args = parser.parse_args()

    summary = process_multi_shot_video(
        args.video_path,
        args.player_name,
        args.shooting_arm,
        session_id=args.session_id,
        progress=lambda stage, done=0, total=0: print(
            f"\n>>> {stage}" + (f" ({done}/{total})" if total else "")
        ),
    )

    print(json.dumps(summary, indent=2))
