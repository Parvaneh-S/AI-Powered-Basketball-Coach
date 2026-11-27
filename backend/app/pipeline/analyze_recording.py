"""Apply the existing per-shot measurements and outcome rules to bounded attempts."""

import json

import pandas as pd

from backend.app.analysis.shot_analysis import build_shot_analysis
from backend.app.ball_detection.shot_outcome import analyze_outcome
from backend.app.measurements.shot_features import extract_shot_features
from backend.app.shot_detection.session_segment import TRAJECTORY_COLUMNS, segment_attempts


def analyze_attempts(video_id, output_dir, arm):
    angles = pd.read_csv(output_dir / "joint_angles.csv")
    detections = pd.read_csv(output_dir / "ball_detections.csv")
    attempts, reviews = segment_attempts(angles, detections, arm, output_dir / "hoop_track.csv")
    analyses, trajectories = [], []
    for number, attempt in enumerate(attempts, start=1):
        shot_id = f"{video_id}_shot_{number}"
        folder = output_dir / "attempts" / shot_id
        folder.mkdir(parents=True)
        events = {**attempt.events, "shot_id": shot_id, "shot_number": number}
        end = events["flight_end_frame"]
        if number < len(attempts):
            # The ball is often still flying while the next attempt's
            # preparation starts, so only the next release ends it.
            end = min(end, attempts[number].events["release_frame"] - 1)
        events["flight_end_frame"] = end
        events["flight_end_time_ms"] = int(angles.loc[angles.frame == end, "timestamp_ms"].iloc[0])
        event_path = folder / "predicted_shot_events.json"
        event_path.write_text(json.dumps(events, indent=2), encoding="utf-8")
        # Preserve absolute frame numbers, while giving each analysis only its own samples.
        angle_path = folder / "joint_angles.csv"
        angles[angles.frame.between(events["start_frame"], events["end_frame"])].to_csv(angle_path, index=False)
        trajectory = attempt.trajectory[attempt.trajectory.frame <= end]
        trajectory.to_csv(folder / "ball_trajectory.csv", index=False)
        extract_shot_features(angle_path, event_path, folder / "shot_features.csv", arm, video_id)
        analyze_outcome(shot_id, folder, hoop_dir=output_dir, release_frame=events["release_frame"])
        analyses.append(build_shot_analysis(video_id, folder, hoop_dir=output_dir))
        trajectories.append(trajectory)
    processing = {"attempt_count": len(analyses), "review_candidate_count": len(reviews),
                  "hoop_available": (output_dir / "hoop_detection.json").is_file(),
                  "detector_status": "experimental", "review_candidates": reviews}
    (output_dir / "recording_analysis.json").write_text(json.dumps(processing, indent=2), encoding="utf-8")
    if analyses:
        (output_dir / "shot_analysis.json").write_text(json.dumps(analyses[0], indent=2), encoding="utf-8")
    overlay = (pd.concat(trajectories, ignore_index=True).drop_duplicates("frame")
               if trajectories else pd.DataFrame(columns=TRAJECTORY_COLUMNS))
    return analyses, processing, overlay
