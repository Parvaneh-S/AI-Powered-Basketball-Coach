"""Build compact, player-scoped evidence from stored analysis snapshots."""

import csv
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select

from backend.app.database.models import Player, PracticeSession, SessionLocal, Shot
from backend.app.measurements.shot_features import MIN_COVERAGE_PCT

ROOT = Path(__file__).resolve().parents[3]
VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{1,150}")


def definition(name, unit, calculation, phase, indicator, interpretation, unsupported):
    return dict(name=name, unit=unit, calculation=calculation, phase=phase,
                reliability_indicator=indicator, supported_interpretation=interpretation,
                unsupported_interpretation=unsupported)


KNEE = "Sufficient knee coverage and ordered shot events"
ELBOW = "Sufficient elbow coverage, ordered shot events and any required release-frame value"
ANGLES = "Ideal form, shooting effectiveness, force, power, or cause of a miss"
MEASUREMENTS = {
    "min_knee_angle": definition("Smallest knee angle", "degrees",
        "Minimum 2D shooting-side knee angle over valid frames", "start through estimated release",
        KNEE, "How bent the knee appeared at its most bent point", ANGLES),
    "knee_angle_range": definition("Knee angle change across the shot", "degrees",
        "Maximum minus minimum 2D knee angle over valid frames", "start through estimated release",
        KNEE, "Size of the measured knee angle range", ANGLES + ", movement direction or speed"),
    "release_elbow_angle": definition("Elbow angle at estimated release", "degrees",
        "2D shoulder–elbow–wrist joint angle at the estimated release frame", "estimated release",
        ELBOW, "How bent the shooting elbow appeared in that frame", ANGLES + ", ball launch angle"),
    "max_elbow_angle": definition("Largest elbow angle", "degrees",
        "Maximum 2D elbow angle from start to the earlier of end and six frames after release",
        "start through early follow-through", ELBOW, "Straightest visible elbow position in that window", ANGLES),
    "elbow_angle_range": definition("Elbow angle range", "degrees",
        "Maximum minus minimum 2D elbow angle in the maximum-elbow window",
        "start through early follow-through", ELBOW, "Size of the measured elbow angle range", ANGLES),
    "elbow_extension_after_release": definition("Elbow straightening after estimated release", "degrees",
        "Maximum 2D elbow angle from estimated release through the early follow-through window minus release elbow angle",
        "early follow-through", ELBOW, "How much farther the elbow straightened during that measured window",
        ANGLES + ", how long the arm stayed up or what the wrist did"),
    "shooting_motion_ms": definition("Time from detected start to estimated release", "ms",
        "Stored estimated release time minus detected start time", "start through estimated release",
        "Pipeline quality pass and ordered shot events", "Estimated time between those events",
        "Total shot duration, power, or confirmed release timing"),
    "knee_coverage_pct": definition("Knee tracking coverage", "%",
        "100 × valid knee frames divided by expected frames", "start through estimated release",
        "Pipeline window and finite percentage", "Share of frames with an angle", "Angle accuracy"),
    "elbow_coverage_pct": definition("Elbow tracking coverage", "%",
        "100 × valid elbow frames divided by expected frames", "start through early follow-through",
        "Pipeline window and finite percentage", "Share of frames with an angle", "Angle accuracy"),
    "tracking_coverage_pct": definition("Ball tracking coverage", "%",
        "100 × tracked frame count divided by inclusive span of tracked frames",
        "first through last tracked ball frame", "Nonempty tracked frame interval",
        "How often the tracker supplied a position in its observed span",
        "Tracking accuracy, uninterrupted flight, release speed or power"),
}

FORM_FIELDS = tuple(field for field in MEASUREMENTS if not field.endswith("_coverage_pct"))
ANGLE_CALCULATION = ("Angle between the two limb segments in the image plane using pixel-scaled "
                     "MediaPipe landmarks. The pipeline requires all three landmarks to pass its visibility check.")
for field, info in MEASUREMENTS.items():
    if info["unit"] == "degrees":
        info["calculation"] += ". " + ANGLE_CALCULATION

LIMITATIONS = [
    "Angles are 2D camera estimates. Coverage describes availability, not accuracy.",
    "Start and release are estimated. Early follow-through can be a provisional window.",
    "Outcomes and form observations do not establish causes or shooting power.",
]


@dataclass(frozen=True)
class RecordedShot:
    player: str
    session_id: int
    shot_id: str
    video_id: str
    outcome: str
    outcome_source: str
    analysis: dict
    row_id: int = 0

    @property
    def shot_number(self):
        return self.analysis.get("shot_number", 1)

    @property
    def conditions(self):
        return {key: value for key, value in {
            "shot_type": self.analysis.get("shot_type"),
            "shooting_arm": self.analysis.get("biomechanics", {}).get("shooting_arm"),
        }.items() if value}


def load_shots(player):
    with SessionLocal() as db:
        rows = db.execute(
            select(Shot, PracticeSession.id)
            .join(PracticeSession).join(Player).where(Player.name == player)
            .order_by(PracticeSession.created_at, PracticeSession.id, Shot.id)
        )
        shots = []
        for shot, session_id in rows:
            try:
                analysis = json.loads(shot.analysis_json)
            except (TypeError, ValueError):
                analysis = {}
            shots.append(RecordedShot(player, session_id, shot.shot_id, shot.video_id,
                         shot.outcome, shot.outcome_source,
                         analysis if isinstance(analysis, dict) else {}, shot.id))
        return shots


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def measurement(shot, field):
    biomech = shot.analysis.get("biomechanics", {})
    events = shot.analysis.get("shot_events", {})
    tracking = shot.analysis.get("ball_tracking", {})
    value = tracking.get(field) if field == "tracking_coverage_pct" else biomech.get(field)
    sample = None
    quality = biomech.get("measurement_quality")
    start, release, end = (events.get(key) for key in ("start_frame", "release_frame", "end_frame"))
    ordered_events = type(start) is int and type(release) is int and 0 <= start < release
    coverage = None
    if not number(value):
        status = "missing"
    elif field.endswith("coverage_pct"):
        status = "valid" if 0 <= value <= 100 else "unreliable"
        if field == "tracking_coverage_pct":
            sample = tracking.get("tracked_frames")
            if not number(sample) or sample < 1:
                status = "unreliable"
    elif field == "shooting_motion_ms":
        status = "valid" if quality == "pass" and value > 0 and ordered_events else "unreliable"
    else:
        joint = "knee" if "knee" in field else "elbow"
        coverage = biomech.get(joint + "_coverage_pct")
        release_value = biomech.get("release_elbow_angle")
        requires_release = field in ("release_elbow_angle", "elbow_extension_after_release")
        has_release = number(release_value) and 0 <= release_value <= 180 and biomech.get("release_angle_valid") is not False
        has_end = ordered_events and type(end) is int and release < end
        needs_end = joint == "elbow" and field != "release_elbow_angle"
        valid = ordered_events and number(coverage) and MIN_COVERAGE_PCT <= coverage <= 100 and 0 <= value <= 180
        valid = valid and (not requires_release or has_release) and (not needs_end or has_end)
        status = "valid" if valid else "unreliable"
        if field == "release_elbow_angle" and valid:
            sample = 1
        elif joint == "knee":
            sample = biomech.get("valid_knee_frames")
        else:
            sample = biomech.get("valid_elbow_frames") if field != "elbow_extension_after_release" else None
    return {"field": field, "unit": MEASUREMENTS[field]["unit"], "status": status,
            "reliability": {"pipeline_quality": quality, "event_status": events.get("segmentation_status"),
                            "joint_coverage_pct": coverage if number(coverage) else None},
            "value": value if status == "valid" else None,
            "sample_frames": sample if type(sample) is int and sample >= 0 else None}


# Horizontal ball travel from release to rim, in rim widths, that suggests a camera view.
SIDE_ON_MIN_RIM_WIDTHS = 4
HEAD_ON_MAX_RIM_WIDTHS = 1


def saved_flight(shot, root=ROOT):
    """Read the saved outcome and trajectory artifacts that belong to this shot's analysis run."""
    if not VIDEO_ID.fullmatch(shot.video_id) or not VIDEO_ID.fullmatch(shot.shot_id):
        return None, None
    base = root / "outputs" / shot.video_id
    for folder in (base / "attempts" / shot.shot_id, base):
        try:
            outcome = json.loads((folder / "shot_outcome.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        saved = shot.analysis.get("shot_outcome") or {}
        # Only use artifacts from the same detector run as the stored snapshot.
        if not isinstance(outcome, dict) or outcome.get("observation") != saved.get("observation"):
            return None, None
        try:
            with (folder / "ball_trajectory.csv").open(encoding="utf-8", newline="") as stream:
                points = [(int(row["frame"]), float(row["center_x"]), float(row["center_y"]))
                          for row in csv.DictReader(stream)]
        except (OSError, ValueError, KeyError, TypeError):
            points = []
        return outcome, points
    return None, None


def flight_geometry(shot, outcome, points):
    """Describe where the tracked ball came down relative to the rim, in rim widths and image terms."""
    crossing = (outcome or {}).get("selected_crossing")
    rim = (outcome or {}).get("rim_center")
    width = (crossing or {}).get("rim_width_px") or (outcome or {}).get("rim_width_px")
    if not (isinstance(rim, list) and len(rim) == 2 and all(map(number, rim)) and number(width) and width > 0):
        return None
    release = (shot.analysis.get("shot_events") or {}).get("release_frame")
    flight = [point for point in points if type(release) is not int or point[0] >= release]
    if len(flight) < 2:
        return None
    rim_x, rim_y = rim
    start_x = flight[0][1]
    travel = math.copysign(1, rim_x - start_x) if rim_x != start_x else 0
    horizontal = abs(rim_x - start_x) / width
    moving_camera = (ROOT / "outputs" / shot.video_id / "hoop_track.csv").is_file()
    # Only a clearly sideways or clearly head-on ball path suggests the camera view. Angled or moving
    # cameras mix depth and sideways motion in the picture, so their direction stays unclear.
    view = ("unclear" if moving_camera else "side_on_likely" if horizontal >= SIDE_ON_MIN_RIM_WIDTHS
            else "front_or_rear_likely" if horizontal <= HEAD_ON_MAX_RIM_WIDTHS else "unclear")
    geometry = {
        "release_to_rim_horizontal_rim_widths": round(horizontal, 2),
        "camera_view_estimate": view,
    }
    if not moving_camera:
        # A fixed rim position is only meaningful for apex height without camera motion.
        geometry["apex_above_rim_rim_widths"] = round((rim_y - min(y for _, _, y in flight)) / width, 2)
    if isinstance(crossing, dict) and number(crossing.get("crossing_x")) and travel:
        offset = (crossing["crossing_x"] - rim_x) * travel / width
        geometry["crossing_offset_rim_widths"] = round(abs(offset), 2)
        side = "before_rim_centre" if offset < 0 else "beyond_rim_centre"
        geometry["crossing_side_along_travel"] = side
        if view == "side_on_likely":
            meaning = ("came down through rim height on the shooter's side of the rim centre. If the camera was "
                       "side-on, as the ball path suggests, that is consistent with a short arrival"
                       if side == "before_rim_centre" else
                       "came down through rim height past the rim centre. If the camera was side-on, as the ball "
                       "path suggests, that is consistent with a long arrival")
        elif view == "front_or_rear_likely":
            meaning = ("came down through rim height to one side of the rim centre in the image. If the camera faced "
                       "the shooter or the basket, that is consistent with a left or right miss")
        else:
            meaning = "came down through rim height away from the rim centre; the camera view leaves the direction unclear"
        geometry["interpretation"] = (
            f"In this 2D view the tracked ball {meaning}. Rim contact, depth and spin are not visible in this estimate."
        )
    elif outcome.get("observation") == "no_downward_crossing":
        geometry["interpretation"] = "The tracked ball path never crossed rim height downward, so its arrival point is unknown."
    return geometry


def shot_evidence(shot):
    tracking = shot.analysis.get("ball_tracking") or {}
    outcome = shot.analysis.get("shot_outcome") or {}
    saved_outcome, points = saved_flight(shot)
    if not outcome.get("selected_crossing") and saved_outcome:
        outcome = {**outcome, "selected_crossing": saved_outcome.get("selected_crossing")}
    geometry = flight_geometry(shot, saved_outcome, points or []) if saved_outcome else None
    crossing = outcome.get("selected_crossing")
    tracked_frames = tracking.get("tracked_frames")
    return {
        "id": f"shot:{shot.shot_id}", "player": shot.player, "session_id": shot.session_id,
        "video_id": shot.video_id, "shot_id": shot.shot_id, "shot_number": shot.shot_number,
        "events": shot.analysis.get("shot_events", {}), "conditions": shot.conditions,
        "sample_shots": 1, "provenance": ("SYNTHETIC development fixture, not video measurements"
                                           if shot.analysis.get("synthetic") is True else
                                           "SQLite shot analysis snapshot and current outcome label"),
        "outcome": shot.outcome if shot.outcome in ("made", "missed") else "unknown",
        "outcome_source": "player label" if shot.outcome_source == "manual" else
                          "unavailable" if shot.outcome not in ("made", "missed") else "experimental detector",
        "outcome_observation": outcome.get("observation"),
        "ball_flight": {
            "status": "available_2d" if number(tracked_frames) and tracked_frames > 0 else "unavailable",
            "tracking": {key: tracking[key] for key in
                         ("tracked_frames", "first_tracked_frame", "last_tracked_frame", "tracking_coverage_pct")
                         if number(tracking.get(key))},
            "rim_crossing_estimate": {key: value for key, value in crossing.items() if number(value)}
                                     if isinstance(crossing, dict) else None,
            "detector_method": outcome.get("method"), "observation": outcome.get("observation"),
            **({"path_relative_to_rim": geometry} if geometry else {}),
            "limitations": "Image-plane tracking cannot establish ball depth, launch angle, release speed or force." + (
                " The detector's 'lateral' label means sideways in the image, which is short or long in a side-on view."
                if "lateral" in str(outcome.get("observation")) else ""),
        },
        "measurements": {field: measurement(shot, field) for field in MEASUREMENTS},
        "limitations": LIMITATIONS,
    }


def comparable(first, second):
    return set(first.conditions) == {"shot_type", "shooting_arm"} and first.conditions == second.conditions
