"""Summarize owned attempts and select visuals that represent supported associations."""

from collections import Counter
from statistics import fmean, median, pstdev

from backend.app.agent.evidence import FORM_FIELDS, MEASUREMENTS, measurement

PATTERN_PHASES = {
    "min_knee_angle": ("knee_dip",),
    "knee_angle_range": ("knee_dip", "knee_max"),
    "release_elbow_angle": ("release",),
    "max_elbow_angle": ("elbow_max",),
    "elbow_angle_range": ("elbow_min", "elbow_max"),
    "elbow_extension_after_release": ("release", "post_release_extension"),
    "shooting_motion_ms": ("preparation", "release"),
}


def summarize_session(shots):
    outcomes = Counter(shot.outcome if shot.outcome in ("made", "missed") else "unknown" for shot in shots)
    known = outcomes["made"] + outcomes["missed"]
    reliable = set()
    distributions = {}
    for field in FORM_FIELDS:
        values = []
        by_outcome = {"made": [], "missed": []}
        for shot in shots:
            data = measurement(shot, field)
            if data["status"] == "valid":
                reliable.add(shot.shot_id)
                values.append(data["value"])
                if shot.outcome in by_outcome:
                    by_outcome[shot.outcome].append(data["value"])
        if not values:
            continue
        distributions[field] = {
            "unit": MEASUREMENTS[field]["unit"], "sample": len(values),
            "mean": round(fmean(values), 2), "median": round(median(values), 2),
            "min": min(values), "max": max(values),
            "spread": round(pstdev(values), 2) if len(values) > 1 else None,
            "by_outcome": {outcome: {
                "sample": len(group),
                "median": round(median(group), 2) if group else None,
                "spread": round(pstdev(group), 2) if len(group) > 1 else None,
            } for outcome, group in by_outcome.items()},
        }
        if len(values) > 1 and len({(shot.video_id, repr(sorted(shot.conditions.items()))) for shot in shots}) == 1:
            midpoint = len(values) // 2
            distributions[field]["earlier_mean"] = round(fmean(values[:midpoint]), 2)
            distributions[field]["later_mean"] = round(fmean(values[midpoint:]), 2)
    return {
        "attempts": len(shots), "made": outcomes["made"], "missed": outcomes["missed"],
        "unknown": outcomes["unknown"],
        "accuracy_pct": round(100 * outcomes["made"] / known, 1) if known else None,
        "outcome_coverage_pct": round(100 * known / len(shots), 1) if shots else None,
        "manual_labels": sum(shot.outcome_source == "manual" and shot.outcome in ("made", "missed") for shot in shots),
        "reliable_form_attempts": len(reliable), "measurements": distributions,
        "limitations": [
            "Accuracy uses attempts with a known outcome. Automatic labels are experimental.",
            "Form summaries use available reliable samples; earlier and later values describe recording order only.",
            "Shot type and arm are the recorded conditions. Differences are descriptive.",
            "Outcome-group summaries are descriptive and may mix shooting conditions. Use the matched form profile to assess associations.",
        ],
    }


def representative_pair(tools, profile, field):
    """Use measured group medians, label provenance and decodable matching phases."""
    if field not in profile.get("likely_patterns", ()) or field not in PATTERN_PHASES:
        return None
    result = profile["features"][field]
    phases = PATTERN_PHASES[field]
    groups = []
    for outcome in ("made", "missed"):
        shots = [shot for shot_id in result[f"{outcome}_shot_ids"]
                 if (shot := tools.resolve(shot_id)) and shot.outcome == outcome]
        values = [(shot, measurement(shot, field)["value"]) for shot in shots]
        values = [(shot, value) for shot, value in values if value is not None]
        if not values:
            return None
        center = median(value for _, value in values)
        ranking = sorted(values, key=lambda entry: (abs(entry[1] - center),
                         entry[0].outcome_source != "manual", entry[0].shot_id))
        groups.append(ranking[:4])
    decoded = {}
    # Examine the closest group ranks first. Skip samples that reverse the supported direction.
    options = [(i + j, made, missed) for i, made in enumerate(groups[0])
               for j, missed in enumerate(groups[1])]
    for _, (made, made_value), (missed, missed_value) in sorted(options, key=lambda row: row[0]):
        delta = made_value - missed_value
        if not delta or (delta > 0) != (result["direction"] == "higher_on_makes"):
            continue
        for shot in (made, missed):
            if shot.shot_id not in decoded:
                decoded[shot.shot_id] = tools.video_frames(shot.shot_id, phases)
        first, second = decoded[made.shot_id], decoded[missed.shot_id]
        if {ref.phase for ref, _ in first} == {ref.phase for ref, _ in second} == set(phases):
            pair = tools.compare_shots(made.shot_id, missed.shot_id)
            return pair, first + second
    return None
