"""
Find every shot in a practice video from the ball's flight.

Every shot sends the ball to the hoop; catching, holding or
fetching the ball does not. So each time the ball arrives near
the rim is one shot.

When shots follow each other quickly, the previous ball can
still be bouncing around the rim when the next one arrives.
A new shot is then recognised by a ball coming in towards the
rim from far away (from the shooter's side); a rebound moves
away from the rim instead.

Positions are measured relative to the rim and in rim widths,
so the rules do not depend on the video's size or zoom.
"""

from pathlib import Path

import cv2
import numpy as np
import pandas as pd

from backend.app.ball_detection.ball_detector import detect_basketball
from backend.app.ball_detection.ball_tracker import (
    remove_stationary_detections,
    to_camera_stable,
)
from backend.app.ball_detection.hoop_detector import detect_hoop
from backend.app.ball_detection.hoop_tracker import track_hoop


# "Near the rim": at most this many rim widths to the side,
# from this far above the rim to this far below it.
NEAR_RIM_SIDE_WIDTHS = 1.5
NEAR_RIM_ABOVE_WIDTHS = 2.5
NEAR_RIM_BELOW_WIDTHS = 1.0

# Ball sightings near the rim less than this far apart belong
# to the same arrival (the ball bouncing on the rim).
SAME_ARRIVAL_GAP_SECONDS = 1.5
MIN_NEAR_RIM_FRAMES = 3

# An incoming ball: first seen at least this far from the rim
# (at about rim height or above), then within this distance of
# the rim, within this time.
INCOMING_FROM_WIDTHS = 2.5
INCOMING_TO_WIDTHS = 1.2
INCOMING_MAX_SECONDS = 1.0

# Clip around each shot: the knee dip and release come about
# 1 s before the ball reaches the rim. The clip starts as early
# as the hands-above-head clips did (0.7 s before the dip):
# starting earlier adds other knee bends (catching, gathering
# the ball) that the single-shot analysis can mistake for the
# dip.
CLIP_BEFORE_ARRIVAL_SECONDS = 1.7
CLIP_AFTER_ARRIVAL_SECONDS = 1.2

# For back-to-back shots, a clip starts no earlier than this
# before the previous ball's arrival, so it does not contain
# the previous shot's release.
CLIP_AFTER_PREVIOUS_ARRIVAL_SECONDS = -0.3

# Typical time from release to the ball reaching the rim, used
# only to show the shot's time in the video.
RELEASE_BEFORE_ARRIVAL_SECONDS = 0.8


def ball_positions_relative_to_rim(detections_csv, hoop_track_csv):
    """
    Ball detections (without balls lying still) with their
    position relative to the rim in that frame, in rim widths:
    dx (sideways) and dy (negative = above the rim).
    """

    detections = pd.read_csv(detections_csv)

    if detections.empty:
        return pd.DataFrame(columns=["frame", "dx", "dy"])

    detections = to_camera_stable(detections, hoop_track_csv)
    detections["stationary"] = remove_stationary_detections(
        detections.assign(
            center_x=detections["stable_x"],
            center_y=detections["stable_y"],
        )
    )["stationary"]
    detections = detections[~detections["stationary"]]

    hoop = pd.read_csv(hoop_track_csv).set_index("frame")
    rim_x = (hoop.x1 + hoop.x2) / 2
    rim_y = (hoop.y1 + hoop.y2) / 2
    rim_width = hoop.x2 - hoop.x1

    detections = detections[detections["frame"].isin(hoop.index)]
    frames = detections["frame"].astype(int)

    return pd.DataFrame({
        "frame": frames.to_numpy(),
        "dx": (
            (detections["center_x"].to_numpy() - rim_x.loc[frames].to_numpy())
            / rim_width.loc[frames].to_numpy()
        ),
        "dy": (
            (detections["center_y"].to_numpy() - rim_y.loc[frames].to_numpy())
            / rim_width.loc[frames].to_numpy()
        ),
    }).sort_values("frame").reset_index(drop=True)


def near_rim_periods(positions, fps):
    """(first_frame, last_frame) of each time the ball is at the rim."""

    near = positions[
        (positions["dx"].abs() < NEAR_RIM_SIDE_WIDTHS)
        & (positions["dy"] > -NEAR_RIM_ABOVE_WIDTHS)
        & (positions["dy"] < NEAR_RIM_BELOW_WIDTHS)
    ]

    periods = []

    for frame in sorted(set(near["frame"].astype(int))):
        if periods and (
            frame - periods[-1][-1] <= SAME_ARRIVAL_GAP_SECONDS * fps
        ):
            periods[-1].append(frame)
        else:
            periods.append([frame])

    return [
        (frames[0], frames[-1])
        for frames in periods
        if len(frames) >= MIN_NEAR_RIM_FRAMES
    ]


def incoming_balls(positions, fps):
    """
    Frames where a ball coming in from far away reaches the
    rim (one per incoming ball).
    """

    points = positions[positions["dy"] < 0.3][["frame", "dx"]].to_numpy()
    max_frames = INCOMING_MAX_SECONDS * fps

    arrivals = []
    last_arrival = -1

    for index, (start, start_dx) in enumerate(points):
        if abs(start_dx) < INCOMING_FROM_WIDTHS or start <= last_arrival:
            continue

        for frame, dx in points[index + 1:]:
            if frame - start > max_frames:
                break

            same_side = np.sign(dx) == np.sign(start_dx)

            if (abs(dx) <= INCOMING_TO_WIDTHS and same_side) or abs(dx) <= 0.5:
                arrivals.append(int(frame))
                last_arrival = frame
                break

    return arrivals


def find_arrivals(positions, fps):
    """
    One frame per shot: when its ball reaches the rim.

    A time at the rim normally counts as one shot. If two or
    more incoming balls reach the rim during it, each of them
    is a separate shot (back-to-back shots).
    """

    incoming = incoming_balls(positions, fps)
    arrivals = []

    for first, last in near_rim_periods(positions, fps):
        inside = [
            frame for frame in incoming
            if first - 5 <= frame <= last + 5
        ]

        if len(inside) >= 2:
            arrivals.extend(inside)
        else:
            arrivals.append(first)

    return sorted(arrivals)


def shot_clips(arrivals, total_frames, fps):
    """
    One shot dict per arrival with the clip to cut around it
    and the shot's (estimated release) time in the video.
    """

    shots = []

    for number, arrival in enumerate(arrivals, start=1):
        first = arrival - round(CLIP_BEFORE_ARRIVAL_SECONDS * fps)

        if number > 1:
            previous = arrivals[number - 2]
            first = max(
                first,
                previous + round(CLIP_AFTER_PREVIOUS_ARRIVAL_SECONDS * fps),
            )

        shots.append({
            "shot": number,
            "arrival_frame": int(arrival),
            "first_frame": int(max(0, first)),
            "last_frame": int(min(
                total_frames - 1,
                arrival + round(CLIP_AFTER_ARRIVAL_SECONDS * fps),
            )),
            "time_s": round(
                max(0.0, arrival / fps - RELEASE_BEFORE_ARRIVAL_SECONDS), 2
            ),
        })

    return shots


def find_ball_shots(video_path, work_dir):
    """
    Detect the ball and the hoop in the whole video and return
    (fps, shots). Writes its working files into work_dir.
    """

    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

    capture = cv2.VideoCapture(str(video_path))
    fps = capture.get(cv2.CAP_PROP_FPS)
    total_frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    capture.release()

    detect_basketball(video_path, work_dir, write_video=False)
    detect_hoop(video_path, work_dir)
    track_hoop(
        video_path,
        work_dir / "hoop_detection.json",
        work_dir / "hoop_track.csv",
    )

    positions = ball_positions_relative_to_rim(
        work_dir / "ball_detections.csv",
        work_dir / "hoop_track.csv",
    )

    return fps, shot_clips(
        find_arrivals(positions, fps), total_frames, fps
    )
