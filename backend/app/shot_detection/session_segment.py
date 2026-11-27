"""Find repeated, ball-supported shot releases on the recording's original timeline."""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from backend.app.ball_detection.ball_tracker import link_paths, to_camera_stable
from backend.app.measurements.shot_features import FOLLOW_THROUGH_FRAMES
from backend.app.shot_detection.release import OUT_OF_HANDS_RADII, STAY_OUT_POINTS

TRAJECTORY_COLUMNS = ["frame", "timestamp_ms", "center_x", "center_y", "confidence"]


@dataclass(frozen=True)
class Attempt:
    events: dict
    trajectory: pd.DataFrame


def extension_candidates(angles, arm):
    """Find distinct rises in elbow extension, keeping one peak per rising run."""
    time = angles.timestamp_ms.to_numpy()
    step = float(np.median(np.diff(time)))
    if step <= 0:
        raise ValueError("Invalid recording timestamps")
    width = max(1, round(140 / step))
    elbow = angles[f"{arm}_elbow_angle"].rolling(3, center=True, min_periods=2).median()
    change = elbow.shift(-width) - elbow
    # Pose cues nominate windows. They never establish an attempt on their own.
    candidates = np.flatnonzero(change.to_numpy() >= 17)
    groups = np.split(candidates, np.where(np.diff(candidates) > max(1, width // 2))[0] + 1)
    return [int(angles.index[max(group, key=lambda i: change.iloc[i])])
            for group in groups if group.size]


def released_paths(detections, angles, center_time):
    """Require a ball near a tracked wrist followed by persistent upward separation."""
    for path in link_paths(detections, max_distance=200):
        if len(path) < STAY_OUT_POINTS + 1:
            continue
        samples = []
        for point in path:
            frame = point["frame"]
            if frame not in angles.index or not point["radius"] > 0:
                continue
            row = angles.loc[frame]
            x, y = point["picture_position"]
            wrist_distances = [
                np.hypot(x - row.get(f"{side}_wrist_x", np.nan), y - row.get(f"{side}_wrist_y", np.nan))
                for side in ("left", "right")
            ]
            distance = min((d for d in wrist_distances if np.isfinite(d)), default=np.nan)
            if np.isfinite(distance):
                samples.append((point, row.timestamp_ms, distance / point["radius"]))
        for i in range(1, len(samples) - STAY_OUT_POINTS + 1):
            before, time_before, distance_before = samples[i - 1]
            after, time_after, _ = samples[i]
            following = samples[i:i + STAY_OUT_POINTS]
            release_gap = time_after - time_before
            if (distance_before > OUT_OF_HANDS_RADII or not 0 < release_gap <= 230
                    or abs(time_after - center_time) > 500
                    or following[-1][1] - time_after > 430
                    or any(distance <= OUT_OF_HANDS_RADII for _, _, distance in following)):
                continue
            upward = before["position"][1] - min(point["position"][1] for point, _, _ in following)
            if upward >= before["radius"] * 1.5:
                # Prefer the hand separation closest in time to the pose cue.
                yield (abs(time_after - center_time), after["frame"] - 1, path, release_gap)


def segment_attempts(angles, detections, arm, hoop_track_path=None):
    """Return complete measurement windows and explicit review-only candidates."""
    angles = angles.sort_values("frame").set_index("frame")
    if not angles.index.is_unique:
        raise ValueError("Expected a unique measurement row for each recording frame")
    if len(angles) < 3:
        return [], []
    times = angles.timestamp_ms
    poses = extension_candidates(angles, arm)
    if detections.empty:
        return [], [{"pose_frame": frame, "reason": "no_ball_detections"} for frame in poses]

    stabilized = to_camera_stable(detections, hoop_track_path)
    stabilized = stabilized.sort_values("frame")
    ball_frames = stabilized.frame.to_numpy()
    proposals, reviews = [], []
    for center in poses:
        center_time = times.at[center]
        lower, upper = times.searchsorted([center_time - 850, center_time + 3400])
        first_frame, last_frame = angles.index[lower], angles.index[min(len(angles) - 1, upper)]
        left, right = np.searchsorted(ball_frames, [first_frame, last_frame + 1])
        matches = released_paths(stabilized.iloc[left:right], angles, center_time)
        nearest = min(matches, default=None, key=lambda item: (item[0], item[3], -len(item[2])))
        if nearest is None:
            reviews.append({"pose_frame": center, "reason": "release_not_corroborated"})
        else:
            proposals.append(nearest)

    # Suppress overlapping proposals for the same ball departure.
    accepted = []
    for offset, release, path, gap in sorted(proposals, key=lambda item: (item[0], item[3])):
        if release not in angles.index:
            continue
        if any(abs(times.at[release] - times.at[other]) < 650 for other, _ in accepted):
            continue
        accepted.append((release, path))
    accepted.sort(key=lambda item: item[0])

    attempts = []
    previous_end = int(angles.index[0]) - 1
    for index, (release, path) in enumerate(accepted):
        release_time = times.at[release]
        earliest = times.searchsorted(release_time - 1050)
        first = max(int(angles.index[earliest]), previous_end + 1)
        latest = accepted[index + 1][0] if index + 1 < len(accepted) else int(angles.index[-1]) + 1
        end = min(release + FOLLOW_THROUGH_FRAMES, latest - 1, int(angles.index[-1]))
        if first >= release or not all(frame in angles.index for frame in range(first, end + 1)):
            reviews.append({"release_frame": release, "reason": "incomplete_measurement_window"})
            continue
        if end <= release:
            reviews.append({"release_frame": release, "reason": "recording_ends_at_release"})
            continue
        knee = angles.loc[first:release - 1, f"{arm}_knee_angle"].dropna()
        start = first
        if len(knee) >= 2:
            dip = knee.idxmin()
            before_dip = knee.loc[:dip]
            start = int(before_dip.idxmax())
        end_index = min(len(times) - 1, times.searchsorted(release_time + 2700, side="right") - 1)
        flight_end = min(int(angles.index[end_index]), latest - 1)
        events = {
            "start_frame": start, "start_time_ms": int(times.at[start]),
            "release_frame": release, "release_time_ms": int(release_time),
            "end_frame": end, "end_time_ms": int(times.at[end]),
            "end_frame_source": "provisional_follow_through_window",
            "flight_end_frame": flight_end, "flight_end_time_ms": int(times.at[flight_end]),
            "method": "pose_and_ball_departure_v1", "release_method": "ball_leaves_hands",
            "status": "experimental_review_required", "shooting_arm": arm,
        }
        trajectory = pd.DataFrame([
            (p["frame"], int(times.at[p["frame"]]), *p["picture_position"], p["confidence"])
            for p in path if start <= p["frame"] <= flight_end and p["frame"] in times.index
        ], columns=TRAJECTORY_COLUMNS)
        attempts.append(Attempt(events, trajectory))
        previous_end = end
    return attempts, reviews
