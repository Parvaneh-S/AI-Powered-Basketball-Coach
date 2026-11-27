"""
Find moments where the video suddenly jumps: the recording was
paused and resumed, the video was cut, or the camera zoomed or
switched lens.

If such a jump falls inside a shot, part of the shot (often the
release) is missing from the video, and its form cannot be
measured. The shot is still counted, with its made/missed result.

A jump is a frame that differs from the previous one far more
than frames normally do (compared on small greyscale copies).
"""

import cv2
import numpy as np


# A frame is a jump if its change from the previous frame is
# above JUMP_FACTOR x the video's typical change + JUMP_MIN.
JUMP_FACTOR = 4.0
JUMP_MIN = 5.0

# The part of a shot that must be in the video: from the knee
# dip until just after the release. A jump before the dip (the
# recording resumed while the player was getting ready) does no
# harm.
#
# With the moment the ball reaches the hoop known: the dip comes
# about 0.9-1.0 s before it.
SHOT_BEFORE_ARRIVAL_SECONDS = 1.1

# Without it: from just before the dip to just after the release.
BEFORE_DIP_FRAMES = 2
AFTER_RELEASE_FRAMES = 6


def picture_jumps(video_path):
    """Return (fps, frames where the picture suddenly jumps)."""

    capture = cv2.VideoCapture(str(video_path))
    fps = capture.get(cv2.CAP_PROP_FPS)

    changes = []
    previous = None

    try:
        while True:
            ok, frame = capture.read()

            if not ok:
                break

            small = cv2.cvtColor(
                cv2.resize(frame, (160, 90)), cv2.COLOR_BGR2GRAY
            ).astype(float)

            if previous is not None:
                changes.append(np.abs(small - previous).mean())

            previous = small

    finally:
        capture.release()

    if len(changes) < 3:
        return fps, []

    changes = np.array(changes)
    threshold = JUMP_FACTOR * np.median(changes) + JUMP_MIN

    # changes[i] is the change from frame i to frame i + 1.
    return fps, [
        int(index) + 1
        for index in np.where(changes > threshold)[0]
    ]


def jump_during_shot(video_path, events, ball_arrival_frame=None):
    """
    Return the frame of a jump inside the shot, or None.

    events: the shot events (knee_min_frame, release_frame, and
    release_window when the ball confirmed the release).
    ball_arrival_frame: when the ball reaches the hoop, if known.

    If the ball was seen leaving the hands, the dip and release
    frames are reliable, so only a jump between them counts.
    Otherwise a jump can have hidden the release (e.g. recording
    resumed with the ball already in the air), so any jump in the
    time before the ball reaches the hoop counts.
    """

    fps, jumps = picture_jumps(video_path)

    release_seen = bool(events.get("release_window"))

    if ball_arrival_frame is not None and not release_seen:
        first = ball_arrival_frame - round(SHOT_BEFORE_ARRIVAL_SECONDS * fps)
        last = ball_arrival_frame
    else:
        first = int(events["knee_min_frame"]) - BEFORE_DIP_FRAMES
        last = int(events["release_frame"]) + AFTER_RELEASE_FRAMES

    for frame in jumps:
        if first < frame <= last:
            return frame

    return None
