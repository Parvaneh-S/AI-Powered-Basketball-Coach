"""
Tests for the made/missed rule (v3).

Rim: 100 px wide, centre at (500, 200).
"""

import json

import pandas as pd
import pytest

from backend.app.ball_detection.shot_outcome import analyze_outcome


RIM = [450.0, 185.0, 550.0, 215.0]


def outcome_for(tmp_path, frames, xs, ys):
    (tmp_path / "hoop_detection.json").write_text(
        json.dumps({"reference_frame": 0, "rim_bbox": RIM})
    )
    pd.DataFrame(
        {"frame": frames, "center_x": xs, "center_y": ys}
    ).to_csv(tmp_path / "ball_trajectory.csv", index=False)

    analyze_outcome("test", tmp_path)

    return json.loads((tmp_path / "shot_outcome.json").read_text())


def test_centred_and_hidden_in_net_is_made(tmp_path):
    # Hidden for 5 frames (11-15) while passing through.
    result = outcome_for(
        tmp_path, [9, 10, 16, 17], [505, 505, 505, 505], [150, 170, 240, 260]
    )
    assert result["outcome"] == "made"
    assert result["observation"] == "made_hidden_in_net"


def test_centred_but_always_visible_is_unknown(tmp_path):
    # Seen in every frame: fell in front of the rim, not into it.
    result = outcome_for(
        tmp_path, [9, 10, 11, 12], [505, 505, 505, 505], [150, 190, 210, 240]
    )
    assert result["outcome"] == "unknown"
    assert result["observation"] == "near_rim_not_confirmed"


def test_hidden_but_too_far_from_centre_is_unknown(tmp_path):
    # 40 px = 0.4 rim widths from the centre: more than 0.35.
    result = outcome_for(
        tmp_path, [9, 10, 16, 17], [540, 540, 540, 540], [150, 170, 240, 260]
    )
    assert result["outcome"] == "unknown"


@pytest.mark.parametrize("x", [620, 380])
def test_clearly_beside_the_rim_is_missed(tmp_path, x):
    # 120 px = 1.2 rim widths from the centre.
    result = outcome_for(
        tmp_path, [9, 10, 11, 12], [x, x, x, x], [150, 190, 210, 240]
    )
    assert result["outcome"] == "missed"


def test_frame_limits_scale_with_frame_rate(tmp_path):
    # At 60 fps the same 0.13 s hidden in the net spans 8 frames,
    # and a 0.6 s gap spans 36 frames (more than 20).
    (tmp_path / "hoop_detection.json").write_text(
        json.dumps({"reference_frame": 0, "rim_bbox": RIM})
    )
    frames = [100, 101, 137, 138]
    pd.DataFrame({
        "frame": frames, "timestamp_ms": [round(f * 1000 / 60) for f in frames],
        "center_x": [505] * 4, "center_y": [150, 170, 240, 260],
    }).to_csv(tmp_path / "ball_trajectory.csv", index=False)

    result = analyze_outcome("sixty", tmp_path)

    assert result["outcome"] == "made"
    assert result["max_bridge_frames"] == 40 and result["made_min_hidden_frames"] == 6


def test_short_hidden_gap_at_60fps_is_not_made(tmp_path):
    # 3 hidden frames at 60 fps is only 0.05 s: not enough evidence.
    (tmp_path / "hoop_detection.json").write_text(
        json.dumps({"reference_frame": 0, "rim_bbox": RIM})
    )
    frames = [100, 101, 105, 106]
    pd.DataFrame({
        "frame": frames, "timestamp_ms": [round(f * 1000 / 60) for f in frames],
        "center_x": [505] * 4, "center_y": [150, 170, 240, 260],
    }).to_csv(tmp_path / "ball_trajectory.csv", index=False)

    assert analyze_outcome("sixty", tmp_path)["outcome"] == "unknown"
