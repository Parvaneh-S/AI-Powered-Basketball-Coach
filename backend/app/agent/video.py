"""Locate and decode real frames without returning filesystem paths."""

import csv
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import get_args

import cv2

from backend.app.agent.annotations import Focus, annotate, measured_angle
from backend.app.agent.evidence import ROOT, VIDEO_ID
from backend.app.measurements.joint_angles import POSE_FILENAME
from backend.app.measurements.shot_features import FOLLOW_THROUGH_FRAMES


FOCUSES = get_args(Focus)


@dataclass(frozen=True)
class FrameReference:
    id: str
    video_id: str
    shot_id: str
    frame: int
    timestamp_s: float
    phase: str
    uncertainty: str
    source: str
    shot_number: int = 1
    session_id: int | None = None
    playback_end_s: float | None = None
    annotation: dict | None = None

    def public(self):
        return asdict(self)


def video_source(video_id, root=ROOT):
    if not VIDEO_ID.fullmatch(video_id):
        return None
    candidates = (
        ("uploaded video", root / "data" / "uploads" / f"{video_id}.mp4"),
        ("sample video", root / "sample_videos" / f"{video_id}.mp4"),
        ("annotated video", root / "outputs" / video_id / "annotated_angles_web.mp4"),
        ("annotated video", root / "outputs" / video_id / "annotated_angles.mp4"),
    )
    for label, path in candidates:
        if path.is_file() and path.resolve().is_relative_to(root.resolve()):
            return label, path
    return None


def extract_frame(path: Path, frame_number: int, overlay=None):
    if type(frame_number) is not int or frame_number < 0 or not path.is_file():
        return None
    cap = cv2.VideoCapture(str(path))
    try:
        count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
        if not cap.isOpened() or (count > 0 and frame_number >= count):
            return None
        if not cap.set(cv2.CAP_PROP_POS_FRAMES, frame_number):
            return None
        success, frame = cap.read()
        if not success or cap.get(cv2.CAP_PROP_POS_FRAMES) != frame_number + 1:
            return None
        height, width = frame.shape[:2]
        scale = min(1, 768 / max(height, width))
        if scale < 1:
            frame = cv2.resize(frame, (max(1, round(width * scale)), max(1, round(height * scale))),
                               interpolation=cv2.INTER_AREA)
        if overlay is not None:
            overlay(frame)
        success, jpg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 82])
        return jpg.tobytes() if success else None
    except cv2.error:
        return None
    finally:
        cap.release()


def angle_file(shot, folder):
    attempt = folder / "attempts" / shot.shot_id / "joint_angles.csv"
    return attempt if VIDEO_ID.fullmatch(shot.shot_id) and attempt.is_file() else folder / "joint_angles.csv"


def stored_landmarks(folder):
    try:
        data = json.loads((folder / POSE_FILENAME).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def shot_frames(shot, phases=None, root=ROOT, *, focus="", from_phase=""):
    if focus not in FOCUSES:
        return []
    source = video_source(shot.video_id, root)
    if not source:
        return []
    label, path = source
    if focus and label == "annotated video":
        return []  # Focused overlays require the original, clean recording.
    folder = root / "outputs" / shot.video_id
    side = shot.conditions.get("shooting_arm")
    events = shot.analysis.get("shot_events", {})
    try:
        if not events and (folder / "predicted_shot_events.json").is_file():
            events = json.loads((folder / "predicted_shot_events.json").read_text(encoding="utf-8"))
        with angle_file(shot, folder).open(encoding="utf-8", newline="") as stream:
            rows = {int(row["frame"]): row for row in csv.DictReader(stream)}
    except (OSError, ValueError, TypeError, KeyError):
        return []
    start, release, end = (events.get(key) for key in ("start_frame", "release_frame", "end_frame"))
    if not (type(start) is int and type(release) is int and 0 <= start < release):
        return []
    candidates = {
        "preparation": (start, "Detected start of preparation"),
        "release": (release, "Estimated release"),
    }
    early_end = None
    if type(end) is int and end > release:
        try:
            release_ms = float(rows[release]["timestamp_ms"])
        except (KeyError, ValueError, TypeError):
            release_ms = math.nan
        for frame in range(min(end, release + FOLLOW_THROUGH_FRAMES), release, -1):
            try:
                elapsed_ms = float(rows[frame]["timestamp_ms"]) - release_ms
            except (KeyError, ValueError, TypeError):
                continue
            if 0 < elapsed_ms <= 250:
                early_end = frame
                candidates["follow_through"] = (frame, "Early post-release frame, not a confirmed shot end")
                break
    # The present detector never establishes landing. Only accept an explicit verified event.
    if events.get("landing_status") == "confirmed" and type(release) is int:
        landing = events.get("landing_frame")
        if type(landing) is int and release < landing <= events.get("flight_end_frame", landing):
            candidates["landing"] = (landing, "Confirmed landing")
    labels = {
        "knee_dip": "Deepest measured knee bend", "knee_max": "Straightest measured knee position",
        "elbow_min": "Most bent measured shooting elbow", "elbow_max": "Straightest measured shooting elbow",
        "post_release_extension": "Peak measured extension in early follow-through",
    }
    if phases:
        for phase, frame in events.get("measurement_frames", {}).items():
            if (phase in labels and type(frame) is int and start <= frame <= (early_end or release)
                    and (phase != "post_release_extension" or frame > release)):
                candidates[phase] = (frame, labels[phase])
        if {"knee_dip", "knee_extension"}.intersection((*phases, from_phase)):
            knee = [(frame, angle) for frame, row in rows.items() if start <= frame <= release
                    and (angle := measured_angle(row, side, "knee")) is not None]
            if knee:
                dip = candidates.get("knee_dip", min(knee, key=lambda sample: (sample[1], sample[0])))[0]
                candidates.setdefault("knee_dip", (dip, labels["knee_dip"]))
                later = [(frame, angle) for frame, angle in knee if frame > dip]
                if later:
                    extension, value = max(later, key=lambda sample: (sample[1], -sample[0]))
                    dip_angle = measured_angle(rows.get(dip, {}), side, "knee")
                    if dip_angle is not None and value > dip_angle:
                        candidates["knee_extension"] = (extension, "Straightest measured knee after loading through release")
    landmarks = stored_landmarks(folder) if focus else {}
    previous = candidates.get(from_phase)
    results = []
    for phase in dict.fromkeys(phases if phases is not None else candidates):
        if phase not in candidates:
            continue
        frame, uncertainty = candidates[phase]
        try:
            timestamp = float(rows[frame]["timestamp_ms"]) / 1000
        except (ValueError, KeyError, TypeError):
            continue
        if not math.isfinite(timestamp) or timestamp < 0:
            continue
        annotation = None
        overlay = None
        suffix = ""
        if focus:
            prior_phase = from_phase if previous and previous[0] < frame else ""
            suffix = f":{focus}:{prior_phase}"
            angle = measured_angle(rows[frame], side, focus)
            if angle is not None:
                angle = round(angle, 1)
            current = landmarks.get(str(frame))
            prior = landmarks.get(str(previous[0])) if prior_phase else None
            annotation = {"focus": focus, "side": side, "angle_deg": angle,
                          "angle_source": "saved_angle" if angle is not None else None, "marks": []}

            def overlay(image):
                annotate(image, current, annotation, prior)
                if "image_plane_displacement" in annotation["marks"]:
                    annotation["from_phase"] = prior_phase

            if not isinstance(current, dict):
                overlay = None
            elif not isinstance(prior, dict):
                prior = None
        jpg = extract_frame(path, frame, overlay)
        if jpg is not None:
            ref = FrameReference(f"frame:{shot.shot_id}:{phase}:{frame}{suffix}", shot.video_id,
                                 shot.shot_id, frame, timestamp, phase, uncertainty, label,
                                 shot.shot_number, shot.session_id,
                                 events["flight_end_time_ms"] / 1000 if events.get("flight_end_time_ms") is not None else None,
                                 annotation)
            results.append((ref, jpg))
    return results
