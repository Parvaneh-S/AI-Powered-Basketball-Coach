"""
Find every shot in a video that contains several shots.

The single-shot pipeline expects one shot per video. This module
scans a whole practice video once with MediaPipe Pose and finds
each shot, so the video can later be cut into one clip per shot.

How a shot is recognised:
    Players bend their knees for many reasons (dribbling, picking
    up the ball), so a knee bend alone is not a shot. During a
    shot, however, the hands rise above the head. Each period
    where a wrist is above the nose marks one shot. The deepest
    knee bend shortly before that period is the shot's dip.
"""

import csv
import json
import subprocess
import time
from pathlib import Path

import cv2
import imageio_ffmpeg
import mediapipe as mp
import numpy as np
import pandas as pd

from backend.app.computer_vision.pose_estimator import (
    get_joint_angle,
)


ROOT = Path(__file__).resolve().parents[3]

POSE_MODEL = (
    ROOT / "backend" / "models" / "pose_landmarker_lite.task"
)

MIN_VISIBILITY = 0.5

# A hands-up period must last at least this long to count.
MIN_RAISE_SECONDS = 0.10

# Hands-up periods closer together than this are one shot
# (e.g. a wrist briefly dropping below the nose mid-shot).
MERGE_GAP_SECONDS = 0.70

# A hands-up period starting this early is treated as "already
# up when the video started" (see find_raise_periods).
STARTS_RAISED_SECONDS = 0.2

# Where to look for the knee dip before the hands go up.
# Real dips were 0.2-0.5 s before; a longer window can pick
# up knee bends from walking back to the line.
DIP_LOOKBACK_SECONDS = 0.6

# Clip length around each shot. The single-shot analysis needs
# the knee dip early in the clip and about 1.5 s of ball flight
# after release.
CLIP_BEFORE_DIP_SECONDS = 0.7
CLIP_AFTER_HANDS_UP_SECONDS = 1.8

# MediaPipe landmark indices.
NOSE = 0
LEFT_WRIST, RIGHT_WRIST = 15, 16


def extract_pose_signals(video_path, csv_path, model_path=POSE_MODEL):
    """
    Run MediaPipe Pose over the whole video and save, for every
    frame, the joint angles and the heights of the nose and
    wrists. No annotated video is written (faster).
    """

    capture = cv2.VideoCapture(str(video_path))

    if not capture.isOpened():
        raise RuntimeError(f"Cannot open video: {video_path}")

    fps = capture.get(cv2.CAP_PROP_FPS)
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))

    if fps <= 0 or width <= 0 or height <= 0:
        capture.release()
        raise RuntimeError("Invalid video properties")

    options = mp.tasks.vision.PoseLandmarkerOptions(
        base_options=mp.tasks.BaseOptions(
            model_asset_path=str(model_path)
        ),
        running_mode=mp.tasks.vision.RunningMode.VIDEO,
        num_poses=1,
    )

    def visible_y(landmarks, index):
        point = landmarks[index]
        if point.visibility < MIN_VISIBILITY:
            return None
        return point.y * height

    rows = []
    frame_index = 0

    try:
        with mp.tasks.vision.PoseLandmarker.create_from_options(
            options
        ) as landmarker:

            while True:
                ok, frame = capture.read()

                if not ok:
                    break

                timestamp_ms = round(frame_index * 1000 / fps)

                image = mp.Image(
                    image_format=mp.ImageFormat.SRGB,
                    data=cv2.cvtColor(frame, cv2.COLOR_BGR2RGB),
                )

                result = landmarker.detect_for_video(
                    image, timestamp_ms
                )

                row = {
                    "frame": frame_index,
                    "timestamp_ms": timestamp_ms,
                }

                if result.pose_landmarks:
                    lm = result.pose_landmarks[0]

                    row.update({
                        "left_elbow_angle": get_joint_angle(
                            lm, 11, 13, 15, width, height
                        ),
                        "right_elbow_angle": get_joint_angle(
                            lm, 12, 14, 16, width, height
                        ),
                        "left_knee_angle": get_joint_angle(
                            lm, 23, 25, 27, width, height
                        ),
                        "right_knee_angle": get_joint_angle(
                            lm, 24, 26, 28, width, height
                        ),
                        "nose_y": visible_y(lm, NOSE),
                        "left_wrist_y": visible_y(lm, LEFT_WRIST),
                        "right_wrist_y": visible_y(lm, RIGHT_WRIST),
                    })

                rows.append(row)
                frame_index += 1

    finally:
        capture.release()

    columns = [
        "frame", "timestamp_ms",
        "left_elbow_angle", "right_elbow_angle",
        "left_knee_angle", "right_knee_angle",
        "nose_y", "left_wrist_y", "right_wrist_y",
    ]

    csv_path = Path(csv_path)
    csv_path.parent.mkdir(parents=True, exist_ok=True)

    with csv_path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)

    return fps


def find_raise_periods(signals, fps):
    """
    Return (first_index, last_index) for every period where a
    wrist is above the nose. Image y grows downwards, so
    "above" means a smaller y.
    """

    nose = signals["nose_y"].to_numpy(dtype=float)
    wrists = signals[
        ["left_wrist_y", "right_wrist_y"]
    ].to_numpy(dtype=float)

    # Frames without visible wrists count as "not raised".
    highest_wrist = np.where(
        np.isnan(wrists).all(axis=1),
        np.inf,
        np.nanmin(np.where(np.isnan(wrists), np.inf, wrists), axis=1),
    )

    with np.errstate(invalid="ignore"):
        raised = highest_wrist < nose

    # Remove single-frame flickers from pose glitches.
    raised = (
        pd.Series(raised.astype(float))
        .rolling(window=5, center=True, min_periods=1)
        .median()
        .to_numpy() >= 0.5
    )

    periods = []
    start = None

    for index, is_raised in enumerate(raised):
        if is_raised and start is None:
            start = index
        elif not is_raised and start is not None:
            periods.append([start, index - 1])
            start = None

    if start is not None:
        periods.append([start, len(raised) - 1])

    merged = []
    for period in periods:
        if merged and (
            period[0] - merged[-1][1]
        ) <= MERGE_GAP_SECONDS * fps:
            merged[-1][1] = period[1]
        else:
            merged.append(period)

    min_frames = MIN_RAISE_SECONDS * fps

    # Hands already up when the video starts: the end of an
    # earlier shot (or the player holding the ball up). Its knee
    # dip is not in the video, so it is not counted as a shot.
    already_up = STARTS_RAISED_SECONDS * fps

    return [
        (first, last)
        for first, last in merged
        if last - first + 1 >= min_frames and first >= already_up
    ]


def find_shots(signals_csv, fps):
    """
    Find the shots in a whole-video pose signal file.

    Returns one dict per shot, in time order, with the frame
    where the knees bend deepest and the frames where the hands
    go up and come back down.
    """

    signals = (
        pd.read_csv(signals_csv)
        .sort_values("frame")
        .reset_index(drop=True)
    )

    knee = (
        signals[["left_knee_angle", "right_knee_angle"]]
        .mean(axis=1, skipna=True)
        .rolling(window=5, center=True, min_periods=3)
        .median()
        .to_numpy(dtype=float)
    )

    shots = []

    for number, (raise_start, raise_end) in enumerate(
        find_raise_periods(signals, fps), start=1
    ):
        left = max(
            0, raise_start - round(DIP_LOOKBACK_SECONDS * fps)
        )
        window = knee[left:raise_start + 1]

        if np.isfinite(window).any():
            dip_index = left + int(np.nanargmin(window))
            dip_angle = round(float(knee[dip_index]), 1)
        else:
            dip_index = None
            dip_angle = None

        shots.append({
            "shot": number,
            "dip_frame": dip_index,
            "dip_knee_angle": dip_angle,
            "hands_up_frame": int(raise_start),
            "hands_down_frame": int(raise_end),
            "hands_up_time_s": round(raise_start / fps, 2),
        })

    return shots


def clip_window(shot, total_frames, fps):
    """
    Frame range [first, last] for one shot's clip: from a little
    before the knee dip until the ball has had time to reach the
    hoop. Neighbouring clips may overlap.
    """

    dip = shot["dip_frame"]
    if dip is None:
        dip = shot["hands_up_frame"]

    first = max(0, dip - round(CLIP_BEFORE_DIP_SECONDS * fps))
    last = min(
        total_frames - 1,
        shot["hands_up_frame"]
        + round(CLIP_AFTER_HANDS_UP_SECONDS * fps),
    )

    return first, last


def cut_clip(video_path, destination, first_frame, last_frame):
    """
    Copy frames first_frame..last_frame (inclusive) of a constant
    frame rate video into a new H.264 MP4. Cutting by frame
    number keeps the clip frame-exact.
    """

    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()

    result = subprocess.run(
        [
            ffmpeg, "-y", "-loglevel", "error",
            "-i", str(video_path),
            "-vf",
            (
                f"trim=start_frame={first_frame}"
                f":end_frame={last_frame + 1},"
                "setpts=PTS-STARTPTS"
            ),
            "-c:v", "libx264",
            "-crf", "18",
            "-preset", "veryfast",
            "-pix_fmt", "yuv420p",
            "-an",
            "-movflags", "+faststart",
            str(destination),
        ],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        raise RuntimeError(
            f"Could not cut clip: {result.stderr.strip()}"
        )


def find_shots_in_video(video_path, work_dir):
    """
    Convert the video to 30 fps / at most 1920 px (see
    convert_for_analysis) inside work_dir, then find its shots.

    Returns (analysis_video_path, fps, shots).
    """

    # Imported here: video_input is part of the pipeline package.
    from backend.app.pipeline.video_input import convert_for_analysis

    work_dir = Path(work_dir)
    analysis_video = work_dir / "video.mp4"
    signals_csv = work_dir / "pose_signals.csv"

    convert_for_analysis(video_path, analysis_video)
    fps = extract_pose_signals(analysis_video, signals_csv)

    return analysis_video, fps, find_shots(signals_csv, fps)


def format_time(seconds):
    minutes, seconds = divmod(seconds, 60)
    return f"{int(minutes)}:{seconds:04.1f}"


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Find every shot in a multi-shot video"
    )
    parser.add_argument("video", help="Path to the video")
    parser.add_argument(
        "--out", required=True,
        help="Folder for the pose signals and shot list",
    )
    args = parser.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    signals_csv = out_dir / "pose_signals.csv"

    started = time.perf_counter()
    fps = extract_pose_signals(args.video, signals_csv)
    pose_seconds = time.perf_counter() - started

    shots = find_shots(signals_csv, fps)

    (out_dir / "shots.json").write_text(
        json.dumps(
            {"fps": fps, "shots": shots}, indent=2
        ),
        encoding="utf-8",
    )

    print(f"Pose tracking took {pose_seconds:.0f} s")
    print(f"Shots found: {len(shots)}\n")

    for shot in shots:
        print(
            f"Shot {shot['shot']:2d}: "
            f"hands up at {format_time(shot['hands_up_frame'] / fps)} "
            f"(frames {shot['hands_up_frame']}-{shot['hands_down_frame']}), "
            f"dip at frame {shot['dip_frame']} "
            f"({shot['dip_knee_angle']} deg)"
        )
