
from pathlib import Path
import argparse

import cv2
import numpy as np
import pandas as pd


def remove_stationary_detections(
    detections,
    position_tolerance=12,
    min_stationary_frames=15,
):
    """
    Find detections that repeatedly appear at nearly
    the same location across many different frames.
    """

    detections = detections.copy()

    detections["stationary"] = False

    if detections.empty:
        return detections

    points = detections[
        ["center_x", "center_y"]
    ].to_numpy(dtype=float)

    # Build clusters of nearby detections.
    clusters = []

    for index, point in enumerate(points):
        matched_cluster = None

        for cluster in clusters:
            distance = np.linalg.norm(
                point - cluster["center"]
            )

            if distance <= position_tolerance:
                matched_cluster = cluster
                break

        if matched_cluster is None:
            clusters.append({
                "center": point.copy(),
                "indices": [index],
            })
        else:
            matched_cluster["indices"].append(index)

            cluster_points = points[
                matched_cluster["indices"]
            ]

            matched_cluster["center"] = (
                cluster_points.mean(axis=0)
            )

    # Mark locations observed in many distinct frames.
    for cluster in clusters:
        indices = cluster["indices"]

        frame_count = detections.iloc[
            indices
        ]["frame"].nunique()

        if frame_count >= min_stationary_frames:
            detections.iloc[
                indices,
                detections.columns.get_loc("stationary")
            ] = True

    return detections


# Detections before the shot's start (the knee dip, minus this
# margin) belong to an earlier shot.
START_MARGIN_FRAMES = 3

# A ball path may continue after a gap of up to this many
# frames without a detection (e.g. hidden by the net). Same as
# the outcome rule's MAX_BRIDGE_FRAMES. Counted at 30 fps and
# scaled to the video's frame rate (see frames_per_30fps_frame).
MAX_LINK_GAP_FRAMES = 20


def frames_per_30fps_frame(table):
    """
    How many of this video's frames last as long as one frame
    at 30 fps (2.0 for a 60 fps phone video), from the
    timestamp_ms and frame columns. 1.0 when unknown. Frame
    limits tuned on 30 fps videos are multiplied by this.
    """

    if "timestamp_ms" not in table or table.empty:
        return 1.0
    rows = table[table["frame"] > 0]
    if rows.empty:
        return 1.0
    ms_per_frame = float(np.median(rows["timestamp_ms"] / rows["frame"]))
    if not ms_per_frame > 0:
        return 1.0
    return max(1.0, (1000 / 30) / ms_per_frame)

# During a gap the ball may change direction (rim, net), so the
# search area grows by this many pixels per missing frame.
GAP_GROWTH_PX = 20

# A shot's ball rises after the dip: over its first few points
# it must move up by at least this many pixels.
MIN_RISE_PX = 15


def to_camera_stable(detections, hoop_track_path):
    """
    Express detection positions relative to the hoop, which is
    fixed in the real world. Balls lying still on the floor then
    stay at the same place even when the camera moves, so the
    stationary filter works again. Without a hoop track the
    positions are left unchanged.
    """

    detections = detections.copy()
    detections["stable_x"] = detections["center_x"]
    detections["stable_y"] = detections["center_y"]

    if hoop_track_path is None or not Path(hoop_track_path).is_file():
        return detections

    track = pd.read_csv(hoop_track_path).set_index("frame")
    track["cx"] = (track.x1 + track.x2) / 2
    track["cy"] = (track.y1 + track.y2) / 2
    track["w"] = track.x2 - track.x1

    track = track[track.w > 0]
    if track.empty:
        return detections
    reference = track.iloc[0]

    for index, row in detections.iterrows():
        frame = int(row["frame"])

        if frame not in track.index:
            continue

        hoop = track.loc[frame]
        zoom = hoop.w / reference.w

        detections.at[index, "stable_x"] = (
            (row["center_x"] - hoop.cx) / zoom + reference.cx
        )
        detections.at[index, "stable_y"] = (
            (row["center_y"] - hoop.cy) / zoom + reference.cy
        )

    return detections


def link_paths(detections, max_distance):
    """
    Link detections in neighbouring frames into ball paths.
    Each detection joins the path whose predicted position
    (constant velocity) is nearest, or starts a new path.

    Linking uses the camera-stable positions, so a sudden camera
    movement does not break a path; each point keeps its
    picture position for the outcome check.
    """

    paths = []
    scale = frames_per_30fps_frame(detections)
    max_gap = round(MAX_LINK_GAP_FRAMES * scale)

    for frame, group in detections.groupby("frame"):
        frame = int(frame)
        taken = set()

        for _, detection in group.sort_values(
            "confidence", ascending=False
        ).iterrows():
            position = np.array(
                [detection["stable_x"], detection["stable_y"]]
            )

            best, best_distance = None, None

            for number, path in enumerate(paths):
                last = path[-1]
                gap = frame - last["frame"]

                if number in taken or not 1 <= gap <= max_gap:
                    continue

                velocity = np.zeros(2)
                if len(path) >= 2:
                    before = path[-2]
                    velocity = (
                        (last["position"] - before["position"])
                        / (last["frame"] - before["frame"])
                    )

                predicted = last["position"] + velocity * gap

                # Where the ball was heading, or (after a bounce
                # on the rim) near where it was last seen.
                distance = min(
                    np.linalg.norm(position - predicted),
                    np.linalg.norm(position - last["position"]),
                )
                gate = max_distance + GAP_GROWTH_PX * (gap - 1) / scale

                if distance <= gate and (
                    best_distance is None or distance < best_distance
                ):
                    best, best_distance = number, distance

            point = {
                "frame": frame,
                "position": position,
                "picture_position": (
                    float(detection["center_x"]),
                    float(detection["center_y"]),
                ),
                "confidence": float(detection["confidence"]),
                "radius": (detection.get("x2", 0) - detection.get("x1", 0)) / 2,
            }

            if best is None:
                paths.append([point])
                taken.add(len(paths) - 1)
            else:
                paths[best].append(point)
                taken.add(best)

    return paths


# A sudden camera change (zoom, lens switch) can split the ball
# path in two. A path starting within this many frames after
# the shot's path ends is treated as its continuation.
MAX_JOIN_GAP_FRAMES = 3


def choose_shot_path(paths):
    """
    The shot's ball is the first path that rises after the knee
    dip (lifted by the hands, then released).
    Earlier balls are already falling or lying on the floor.
    """

    paths = [path for path in paths if len(path) >= 4]
    paths.sort(key=lambda p: p[0]["frame"])

    shot_path = None

    for path in paths:
        start_y = path[0]["position"][1]
        highest_early_y = min(
            point["position"][1] for point in path[:6]
        )

        if start_y - highest_early_y >= MIN_RISE_PX:
            shot_path = list(path)
            break

    if shot_path is None:
        return None

    # Join pieces split by a sudden camera change.
    while True:
        end = shot_path[-1]["frame"]

        continuations = [
            path for path in paths
            if 1 <= path[0]["frame"] - end <= MAX_JOIN_GAP_FRAMES
        ]

        if not continuations:
            return shot_path

        shot_path += max(continuations, key=len)


def track_ball(
    video_path,
    csv_path,
    output_dir,
    max_distance=200,
    start_frame=None,
    hoop_track_path=None,
    trajectory=None,
):
    """
    Follow the shot's ball through the video.

    With start_frame (the shot's knee dip), only the ball that
    rises from then on is followed: first in the hands, then in
    flight. Earlier balls are ignored.
    With hoop_track_path, camera movement is taken into account
    when removing balls that lie still. Without these, the
    original nearest-neighbour tracker is used.
    """

    video_path = Path(video_path)
    csv_path = Path(csv_path)
    output_dir = Path(output_dir)

    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    if trajectory is not None:
        filtered = trajectory.sort_values("frame").drop_duplicates("frame")
    else:
        detections = pd.read_csv(csv_path)

        if detections.empty:
            print("No ball detections found.")
            return

        detections = to_camera_stable(detections, hoop_track_path)

        # The stationary filter clusters on the stable positions.
        stationary = remove_stationary_detections(
            detections.assign(
                center_x=detections["stable_x"],
                center_y=detections["stable_y"],
            )
        )["stationary"]

        detections["stationary"] = stationary

        filtered = detections[
            ~detections["stationary"]
        ].copy()

        shot_path = None

        if start_frame is not None:
            after_start = filtered[
                filtered["frame"]
                >= start_frame - START_MARGIN_FRAMES
            ]

            shot_path = choose_shot_path(
                link_paths(after_start, max_distance)
            )

            if shot_path is None:
                print("No rising ball found in this shot.")

            # Only the chosen path's detections are kept.
            filtered = pd.DataFrame(
                [
                    {
                        "frame": point["frame"],
                        "center_x": point["picture_position"][0],
                        "center_y": point["picture_position"][1],
                        "confidence": point["confidence"],
                    }
                    for point in (shot_path or [])
                ],
                columns=["frame", "center_x", "center_y", "confidence"],
            )

        print(
            "Stationary detections removed:",
            int(detections["stationary"].sum())
        )

        print(
            "Ball positions used:",
            len(filtered)
        )

    video = cv2.VideoCapture(
        str(video_path)
    )

    if not video.isOpened():
        raise RuntimeError(
            f"Cannot open video: {video_path}"
        )

    fps = video.get(cv2.CAP_PROP_FPS)
    width = int(
        video.get(cv2.CAP_PROP_FRAME_WIDTH)
    )
    height = int(
        video.get(cv2.CAP_PROP_FRAME_HEIGHT)
    )

    if fps <= 0 or width <= 0 or height <= 0:
        video.release()
        raise RuntimeError("Invalid video properties")

    output_video = (
        output_dir / "ball_tracking.mp4"
    )

    output_csv = (
        output_dir / "ball_trajectory.csv"
    )

    writer = cv2.VideoWriter(
        str(output_video),
        cv2.VideoWriter_fourcc(*"mp4v"),
        fps,
        (width, height),
    )

    if not writer.isOpened():
        video.release()
        raise RuntimeError(
            "Cannot create tracking video"
        )

    previous_position = None
    supplied_trajectory = trajectory is not None
    trajectory = []
    frame_index = 0

    grouped = {
        int(frame): group
        for frame, group in filtered.groupby("frame")
    }

    try:
        while True:
            success, frame = video.read()

            if not success:
                break

            candidates = grouped.get(frame_index)

            selected = None

            if candidates is not None:
                if start_frame is not None or supplied_trajectory:
                    # Already linked to the owning attempt.
                    selected = candidates.iloc[0]

                elif previous_position is None:
                    # Initial candidate: highest confidence
                    selected = candidates.loc[
                        candidates["confidence"].idxmax()
                    ]

                else:
                    candidate_positions = candidates[
                        ["center_x", "center_y"]
                    ].to_numpy(dtype=float)

                    distances = np.linalg.norm(
                        candidate_positions
                        - previous_position,
                        axis=1,
                    )

                    nearest = int(
                        np.argmin(distances)
                    )

                    if distances[nearest] <= max_distance:
                        selected = candidates.iloc[nearest]

            if selected is not None:
                x = float(selected["center_x"])
                y = float(selected["center_y"])

                previous_position = np.array(
                    [x, y],
                    dtype=float,
                )

                trajectory.append({
                    "frame": frame_index,
                    "timestamp_ms": round(
                        frame_index * 1000 / fps
                    ),
                    "center_x": round(x, 2),
                    "center_y": round(y, 2),
                    "confidence": float(
                        selected["confidence"]
                    ),
                })

                cv2.circle(
                    frame,
                    (int(x), int(y)),
                    7,
                    (0, 0, 255),
                    -1,
                )

                cv2.putText(
                    frame,
                    "Tracked ball",
                    (int(x) + 10, int(y) - 10),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.6,
                    (0, 0, 255),
                    2,
                )

            writer.write(frame)
            frame_index += 1

    finally:
        video.release()
        writer.release()

    pd.DataFrame(
        trajectory,
        columns=[
            "frame",
            "timestamp_ms",
            "center_x",
            "center_y",
            "confidence",
        ],
    ).to_csv(
        output_csv,
        index=False,
    )

    print(
        f"Tracked frames: {len(trajectory)}"
    )

    print(
        f"Tracking video: {output_video}"
    )

    print(
        f"Trajectory CSV: {output_csv}"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()

    parser.add_argument("video")

    args = parser.parse_args()

    root = Path(__file__).resolve().parents[3]

    video_name = Path(args.video).name
    stem = Path(video_name).stem

    track_ball(
        video_path=(
            root / "sample_videos" / video_name
        ),
        csv_path=(
            root / "outputs" / stem
            / "ball_detections.csv"
        ),
        output_dir=(
            root / "outputs" / stem
        ),
    )
