"""
Tests for finding shots from the ball arriving at the hoop
(ball_shot_finder.py).

Positions are in rim widths relative to the rim: dx sideways
(the shooter is on the left, dx < 0), dy negative = above the
rim.
"""

import pandas as pd

from backend.app.shot_detection.ball_shot_finder import (
    find_arrivals,
    shot_clips,
)


FPS = 30


def flight(start_frame, frames=12):
    """A ball coming in from the shooter's side to the rim."""
    return [
        (start_frame + i, -4.0 + 4.0 * i / (frames - 1), -1.5)
        for i in range(frames)
    ]


def bounce_at_rim(start_frame, frames=20):
    """The ball bouncing around the rim, then dropping away."""
    return [
        (start_frame + i, 0.3 * ((-1) ** i), -0.5 + 0.1 * i)
        for i in range(frames)
    ]


def positions(*parts):
    rows = [row for part in parts for row in part]
    return pd.DataFrame(rows, columns=["frame", "dx", "dy"])


def test_separate_shots_are_each_found():
    data = positions(
        flight(30), bounce_at_rim(42),
        flight(200), bounce_at_rim(212),
    )

    assert len(find_arrivals(data, FPS)) == 2


def test_back_to_back_shots_are_not_merged():
    # The second ball arrives while the first is still at the
    # rim (one long time at the rim, two incoming balls).
    data = positions(
        flight(30), bounce_at_rim(42, frames=30),
        flight(60), bounce_at_rim(72),
    )

    arrivals = find_arrivals(data, FPS)

    assert len(arrivals) == 2
    assert arrivals[1] > arrivals[0] + 15


def test_rebound_leaving_the_rim_is_not_a_shot():
    rebound = [(54 + i, 0.5 - 0.4 * i, -1.0) for i in range(12)]
    data = positions(flight(30), bounce_at_rim(42, frames=12), rebound)

    assert len(find_arrivals(data, FPS)) == 1


def test_ball_never_near_the_rim_is_not_a_shot():
    # Holding, dribbling or passing far from the hoop.
    data = positions([(f, -6.0, 3.0) for f in range(100)])

    assert find_arrivals(data, FPS) == []


def test_back_to_back_clip_does_not_start_before_previous_arrival():
    shots = shot_clips([100, 136], total_frames=1000, fps=FPS)

    first, second = shots
    assert first["first_frame"] == 100 - 51
    # 1.7 s before arrival would be frame 85, before the first
    # ball's arrival; the clip starts just before it instead.
    assert second["first_frame"] == 100 - 9
    assert second["last_frame"] == 136 + 36
