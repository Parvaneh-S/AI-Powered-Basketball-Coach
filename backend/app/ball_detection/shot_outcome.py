
import argparse
import json
from pathlib import Path

import pandas as pd


# The ball is often hidden by the rim and net while it
# passes through the hoop. A missing stretch of up to this
# many frames is bridged with a straight line between the
# last point above the rim and the first point below it.
# At 30 fps, 20 frames is about 0.67 seconds.
MAX_BRIDGE_FRAMES = 20


def analyze_outcome(video_name, output_dir):
    output_dir = Path(output_dir)

    trajectory_file = output_dir / "ball_trajectory.csv"
    hoop_file = output_dir / "hoop_detection.json"
    result_file = output_dir / "shot_outcome.json"

    trajectory = pd.read_csv(trajectory_file)

    with hoop_file.open("r", encoding="utf-8") as file:
        hoop = json.load(file)

    x1, y1, x2, y2 = map(float, hoop["rim_bbox"])

    rim_x = (x1 + x2) / 2
    rim_y = (y1 + y2) / 2
    rim_width = x2 - x1

    if rim_width <= 0:
        raise ValueError("Invalid hoop bounding box")

    trajectory = trajectory.sort_values("frame")

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
        if frame_gap < 1 or frame_gap > MAX_BRIDGE_FRAMES:
            continue

        px = float(previous["center_x"])
        py = float(previous["center_y"])
        cx = float(current["center_x"])
        cy = float(current["center_y"])

        # Image y coordinates increase downward.
        if not (py < rim_y <= cy):
            continue

        if cy == py:
            continue

        # Estimate horizontal position at the
        # instant the ball crosses the rim's height.
        fraction = (rim_y - py) / (cy - py)
        crossing_x = px + fraction * (cx - px)

        horizontal_distance = abs(crossing_x - rim_x)

        candidates.append({
            "frame_before": int(previous["frame"]),
            "frame_after": int(current["frame"]),
            "crossing_x": round(crossing_x, 2),
            "distance_from_rim_center_px": round(
                horizontal_distance, 2
            ),
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

        possible_opening_half_width = rim_width / 2
        safety_margin = rim_width * 0.5

        if distance <= possible_opening_half_width:
            outcome = "made"

            if selected_crossing["bridged_gap_frames"] > 0:
                observation = "made_bridged_gap"
            else:
                observation = "made_crossing_inside_rim"

        elif distance > (
            possible_opening_half_width + safety_margin
        ) and distance <= 2.5 * rim_width:
            observation = "clear_lateral_miss_candidate"
            outcome = "missed"

        else:
            observation = "ambiguous_crossing"
            outcome = "unknown"

    result = {
        "video": video_name,
        "method": "2d_trajectory_rim_crossing_v2",
        "max_bridge_frames": MAX_BRIDGE_FRAMES,
        "outcome": outcome,
        "observation": observation,
        "rim_center": [rim_x, rim_y],
        "rim_width_px": rim_width,
        "crossings_found": len(candidates),
        "selected_crossing": selected_crossing,
        "note": (
            "Experimental 2D heuristic. A made result "
            "means the ball crossed the rim height inside "
            "the rim opening, possibly across a short "
            "detection gap. Rim bounces cannot be told "
            "apart in 2D, so results should be confirmed "
            "visually or corrected manually."
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
