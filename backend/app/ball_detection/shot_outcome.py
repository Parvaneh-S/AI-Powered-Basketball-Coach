
import argparse
import json
from pathlib import Path

import pandas as pd

from backend.app.ball_detection.ball_tracker import frames_per_30fps_frame
from backend.app.ball_detection.hoop_tracker import (
    load_hoop_track,
)


# The ball is often hidden by the rim and net while it
# passes through the hoop. A missing stretch of up to this
# many frames is bridged with a straight line between the
# last point above the rim and the first point below it.
# At 30 fps, 20 frames is about 0.67 seconds. Both frame
# limits below are counted at 30 fps and scaled to the video's
# frame rate, so a 60 fps video bridges 40 frames.
MAX_BRIDGE_FRAMES = 20

# "Made" needs two pieces of evidence (v3):
# 1. The ball crosses the rim height close to the rim centre.
#    A ball (about 24 cm) is about half as wide as the rim
#    (about 45 cm), so its centre must pass within about 0.23
#    rim widths of the centre; 0.35 allows for 2D and box error.
MADE_MAX_OFFSET_RIM_WIDTHS = 0.35

# 2. The ball is hidden for a few frames while crossing: a made
#    ball passes behind the front of the rim into the net. A
#    ball falling just in front of the rim stays visible and
#    looks "in" from the side.
MADE_MIN_HIDDEN_FRAMES = 3


def analyze_outcome(video_name, output_dir, *, hoop_dir=None, release_frame=None):
    output_dir = Path(output_dir)

    trajectory_file = output_dir / "ball_trajectory.csv"
    hoop_dir = Path(hoop_dir) if hoop_dir is not None else output_dir
    hoop_file = hoop_dir / "hoop_detection.json"
    result_file = output_dir / "shot_outcome.json"

    trajectory = pd.read_csv(trajectory_file)
    if release_frame is not None:
        trajectory = trajectory[trajectory.frame >= release_frame]
    if not hoop_file.is_file():
        result = {"outcome": "unknown", "observation": "hoop_detection_unavailable",
                  "method": "2d_trajectory_rim_crossing_v3"}
        result_file.write_text(json.dumps(result, indent=2), encoding="utf-8")
        return result

    with hoop_file.open("r", encoding="utf-8") as file:
        hoop = json.load(file)

    x1, y1, x2, y2 = map(float, hoop["rim_bbox"])

    rim_x = (x1 + x2) / 2
    rim_y = (y1 + y2) / 2
    rim_width = x2 - x1

    if rim_width <= 0:
        raise ValueError("Invalid hoop bounding box")

    # With a moving camera the rim moves in the picture.
    # If the hoop was followed through the video, compare the
    # ball with the rim position in the same frame.
    hoop_track = load_hoop_track(hoop_dir / "hoop_track.csv")

    def rim_at(frame):
        if hoop_track and int(frame) in hoop_track:
            return hoop_track[int(frame)]
        return rim_x, rim_y, rim_width

    trajectory = trajectory.sort_values("frame")
    scale = frames_per_30fps_frame(trajectory)
    max_bridge_frames = round(MAX_BRIDGE_FRAMES * scale)
    min_hidden_frames = round(MADE_MIN_HIDDEN_FRAMES * scale)

    points = trajectory[
        ["frame", "center_x", "center_y"]
    ].dropna().to_dict("records")

    candidates = []

    # Find neighbouring observations where the ball
    # crosses the rim's approximate height downward.
    for previous, current in zip(points, points[1:]):
        frame_gap = int(
            current["frame"] - previous["frame"]
        )

        # Bridge short detection gaps only. Longer gaps
        # could hide a rim bounce or a rebound.
        if frame_gap < 1 or frame_gap > max_bridge_frames:
            continue

        # Ball positions relative to the rim centre in the
        # same frame (equal to the fixed rim without tracking).
        rim_x0, rim_y0, width0 = rim_at(previous["frame"])
        rim_x1, rim_y1, width1 = rim_at(current["frame"])

        px = float(previous["center_x"]) - rim_x0
        py = float(previous["center_y"]) - rim_y0
        cx = float(current["center_x"]) - rim_x1
        cy = float(current["center_y"]) - rim_y1

        # Image y coordinates increase downward, so a downward
        # crossing goes from above the rim (< 0) to at or
        # below it (>= 0).
        if not (py < 0 <= cy):
            continue

        if cy == py:
            continue

        # Estimate horizontal position at the
        # instant the ball crosses the rim's height.
        fraction = -py / (cy - py)
        crossing_dx = px + fraction * (cx - px)

        horizontal_distance = abs(crossing_dx)
        width_at_crossing = width0 + fraction * (width1 - width0)
        crossing_rim_x = rim_x0 + fraction * (rim_x1 - rim_x0)

        candidates.append({
            "frame_before": int(previous["frame"]),
            "frame_after": int(current["frame"]),
            "crossing_x": round(crossing_rim_x + crossing_dx, 2),
            "distance_from_rim_center_px": round(
                horizontal_distance, 2
            ),
            "rim_width_px": round(width_at_crossing, 2),
            # Frames without a detection between the two
            # points, 0 when they are consecutive frames.
            "bridged_gap_frames": frame_gap - 1,
        })

    outcome = "unknown"
    observation = "no_downward_crossing"
    selected_crossing = None

    # This is a preliminary 2D heuristic.
    # The margin accommodates approximate rim boxes.
    if candidates:
        selected_crossing = min(
            candidates,
            key=lambda item: (
                item["distance_from_rim_center_px"]
            ),
        )

        distance = selected_crossing[
            "distance_from_rim_center_px"
        ]
        width = selected_crossing["rim_width_px"]

        possible_opening_half_width = width / 2
        safety_margin = width * 0.5
        hidden_frames = selected_crossing["bridged_gap_frames"]

        if (
            distance <= MADE_MAX_OFFSET_RIM_WIDTHS * width
            and hidden_frames >= min_hidden_frames
        ):
            outcome = "made"
            observation = "made_hidden_in_net"

        elif distance <= possible_opening_half_width:
            # Near the rim, but not enough evidence for a make
            # (e.g. the ball fell just in front of the rim).
            outcome = "unknown"
            observation = "near_rim_not_confirmed"

        elif distance > (
            possible_opening_half_width + safety_margin
        ) and distance <= 2.5 * width:
            observation = "clear_lateral_miss_candidate"
            outcome = "missed"

        else:
            observation = "ambiguous_crossing"
            outcome = "unknown"

    result = {
        "video": video_name,
        "method": "2d_trajectory_rim_crossing_v3",
        "max_bridge_frames": max_bridge_frames,
        "made_max_offset_rim_widths": MADE_MAX_OFFSET_RIM_WIDTHS,
        "made_min_hidden_frames": min_hidden_frames,
        "hoop_tracked": hoop_track is not None,
        "outcome": outcome,
        "observation": observation,
        "rim_center": [rim_x, rim_y],
        "rim_width_px": rim_width,
        "crossings_found": len(candidates),
        "selected_crossing": selected_crossing,
        "note": (
            "Experimental 2D heuristic. A made result "
            "means the ball crossed the rim height close to "
            "the rim centre while hidden by the rim and net "
            "for a few frames. Balls falling just in front of "
            "or behind the rim cannot always be told apart in "
            "2D; those are reported as unknown and can be "
            "corrected manually."
        ),
    }

    with result_file.open(
        "w", encoding="utf-8"
    ) as file:
        json.dump(result, file, indent=4)

    print("\nSHOT OUTCOME ANALYSIS")
    print("-----------------------------")
    print(f"Video: {video_name}")
    print(f"Outcome: {outcome}")
    print(f"Observation: {observation}")
    print(f"Crossings found: {len(candidates)}")
    print(f"Saved: {result_file}")

    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("video")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[3]
    video_name = Path(args.video).name
    stem = Path(video_name).stem

    analyze_outcome(
        video_name=video_name,
        output_dir=root / "outputs" / stem,
    )
