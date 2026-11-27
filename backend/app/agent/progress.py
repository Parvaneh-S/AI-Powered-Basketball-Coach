"""Summarize compatible shooting samples and review earlier coaching objectives."""

from collections import defaultdict
from statistics import fmean, pstdev

from backend.app.agent.evidence import FORM_FIELDS, MEASUREMENTS, comparable, measurement
from backend.app.agent.profile import personal_profile


def summarize_set(shots, field):
    values = [item["value"] for shot in shots
              if field and (item := measurement(shot, field))["status"] == "valid"]
    made = sum(shot.outcome == "made" for shot in shots)
    missed = sum(shot.outcome == "missed" for shot in shots)
    known = made + missed
    manual_made = sum(shot.outcome == "made" and shot.outcome_source == "manual" for shot in shots)
    manual_missed = sum(shot.outcome == "missed" and shot.outcome_source == "manual" for shot in shots)
    return {
        "shot_count": len(shots), "made": made, "missed": missed, "unknown": len(shots) - known,
        "manual_labels": manual_made + manual_missed, "manual_made": manual_made,
        "accuracy_pct": round(100 * made / known, 1) if known else None,
        "measurement_count": len(values),
        "mean": round(fmean(values), 2) if values else None,
        "spread": round(pstdev(values), 2) if len(values) >= 2 else None,
    }


def compare_samples(samples, field, camera="unknown"):
    """Use descriptive thresholds for sufficiently covered sets, with each endpoint kept separate."""
    rates = [round(100 * row["manual_made"] / row["manual_labels"], 4)
             if row["manual_labels"] >= 8 and row["manual_labels"] / row["shot_count"] >= .8 else None
             for row in samples]
    spreads = [row["spread"] if row["measurement_count"] >= 5
               and row["measurement_count"] / row["shot_count"] >= .75 else None for row in samples]
    accuracy = compare_series(rates, 10)
    spread_threshold = 30 if field == "shooting_motion_ms" else 2
    consistency = ("camera_changed" if field and camera == "changed" else
                   compare_series([None if value is None else -value for value in spreads], spread_threshold))
    directions = {accuracy, consistency}
    if "mixed" in directions or {"higher", "lower"} <= directions:
        overall = "mixed"
    elif "higher" in directions:
        overall = "favorable"
    elif "lower" in directions:
        overall = "unfavorable"
    else:
        overall = "similar" if "similar" in directions else "insufficient"
    return {"accuracy": accuracy, "consistency": consistency, "overall": overall,
            "camera": camera, "phase": MEASUREMENTS[field]["phase"] if field else None}


def compare_series(values, threshold):
    if values[0] is None or values[-1] is None:
        return "insufficient"
    changes = [current - prior for prior, current in zip(values, values[1:])
               if prior is not None and current is not None]
    if any(change >= threshold for change in changes) and any(change <= -threshold for change in changes):
        return "mixed"
    difference = values[-1] - values[0]
    return "higher" if difference >= threshold else "lower" if difference <= -threshold else "similar"


def compare_sessions(shots, anchor=None, field="release_elbow_angle", *, before_id=None, after_id=None,
                     camera="unknown", different_distance=False):
    """Compare up to three ordered sessions belonging to the caller's owned shot snapshot."""
    sessions = defaultdict(list)
    for shot in shots:
        if shot.session_id is not None:
            sessions[shot.session_id].append(shot)
    after_id = after_id if after_id is not None else (anchor.session_id if anchor else next(reversed(sessions), None))
    if after_id not in sessions or (before_id is not None and before_id not in sessions) or different_distance:
        return {"status": "no_comparable_sessions", "distance_mismatch": different_distance}
    anchor = anchor if anchor in sessions[after_id] else sessions[after_id][-1]
    ordered = list(sessions)
    if before_id is not None and ordered.index(before_id) >= ordered.index(after_id):
        return {"status": "no_comparable_sessions"}
    scopes = [(key, [shot for shot in sessions[key] if comparable(shot, anchor)])
              for key in ordered[:ordered.index(after_id) + 1]]
    scopes = [(key, group) for key, group in scopes if group]
    if before_id is not None:
        scopes = [(key, group) for key, group in scopes if key in (before_id, after_id)]
    else:
        scopes = scopes[-3:]
    if len(scopes) < 2 or scopes[-1][0] != after_id:
        return {"status": "no_comparable_sessions"}
    field = field if field in FORM_FIELDS else None
    summaries = [{"session_id": key, **summarize_set(group, field)} for key, group in scopes]
    return {
        "status": "available", "kind": "sessions", "id": f"progress:sessions:{scopes[0][0]}:{after_id}:{field}",
        "before_session_id": scopes[0][0], "after_session_id": after_id, "field": field,
        "before": summaries[0], "after": summaries[-1], "intermediate": summaries[1:-1],
        "before_shot_ids": representative_ids(scopes[0][1], field, summaries[0]),
        "after_shot_ids": representative_ids(scopes[-1][1], field, summaries[-1]),
        "conditions": anchor.conditions, "completed": False,
        "assessment": compare_samples(summaries, field, camera),
        "provenance": "Owned session records in stored session order",
        "limitations": [
            "Shot type and shooting arm match. Distance, fatigue and camera setup may differ.",
            "Accuracy direction uses player-confirmed outcomes. Movement direction describes spread in one measured phase.",
            "Differences in these samples do not establish lasting improvement or the effect of a cue.",
        ],
    }


def representative_ids(shots, field, summary):
    if field and summary["mean"] is not None:
        usable = [(abs(data["value"] - summary["mean"]), shot.shot_id) for shot in shots
                  if (data := measurement(shot, field))["status"] == "valid"]
        return [shot_id for _, shot_id in sorted(usable)[:3]]
    return [shot.shot_id for shot in shots[-3:]]


def assess_progress(shots, focus, reports, selected_session_id=None, *, camera="unknown", different_distance=False):
    if not focus:
        return {"status": "no_focus"}
    conditions = focus["conditions"]
    later = [shot for shot in shots if shot.row_id > focus["last_row_id"]
             and conditions and conditions == shot.conditions]
    baseline_ids = set(focus["baseline_shot_ids"])
    matched = [shot for shot in shots if shot.shot_id in baseline_ids and shot.conditions == conditions]
    baseline_session = focus.get("session_id")
    session_comparison = {}
    if baseline_session is not None:
        sessions = list(dict.fromkeys(shot.session_id for shot in shots))
        following = set(sessions[sessions.index(baseline_session) + 1:]) if baseline_session in sessions else set()
        candidates = [shot for shot in later if shot.session_id in following]
        target = selected_session_id if selected_session_id not in (None, baseline_session) else (
            candidates[-1].session_id if candidates else None
        )
        later = [shot for shot in candidates if shot.session_id == target]
        session_comparison = {"before_session_id": baseline_session, "after_session_id": target}
        between = [session for session in sessions if session in following and session != target
                   and (target is None or sessions.index(session) < sessions.index(target))]
        if between:
            # Sessions between the endpoints, described but not used in the endpoint assessment.
            session_comparison["intermediate"] = [
                {"session_id": session, **summarize_set([shot for shot in candidates if shot.session_id == session],
                                                        focus["field"])}
                for session in between]
        if later:
            before_profile, after_profile = personal_profile(matched), personal_profile(later)
            session_comparison["pattern_comparison"] = [{
                "field": field,
                "before": pattern_state(before_profile, field),
                "after": pattern_state(after_profile, field),
            } for field in before_profile.get("likely_patterns", []) + [
                field for field in after_profile.get("likely_patterns", [])
                if field not in before_profile.get("likely_patterns", [])
            ]]
    before, after = summarize_set(matched, focus["field"]), summarize_set(later, focus["field"])
    relevant_reports = [report for report in reports if report["focus_id"] == focus["id"]]
    efficacy = next((report["kind"] for report in reversed(relevant_reports)
                     if report["kind"] in ("helped", "did_not_help")), None)
    available = bool(matched and later and not different_distance)
    return {
        **session_comparison,
        "status": "available" if available else "no_comparable_new_shots", "kind": "objective",
        "id": f"progress:{focus['id']}", "focus_id": focus["id"], "field": focus["field"],
        "before": before, "after": after,
        "before_shot_ids": [shot.shot_id for shot in matched],
        "after_shot_ids": [shot.shot_id for shot in later],
        "conditions": conditions, "provenance": "Shot records added after the objective was assigned",
        "sample_shots": len(matched) + len(later),
        "completed": any(report["kind"] == "completed" for report in relevant_reports),
        "player_reported_effect": efficacy,
        "assessment": compare_samples([before, after], focus["field"], camera) if available else None,
        "distance_mismatch": different_distance,
        "limitations": [
            "Matched by recorded shot type and shooting arm. Distance, camera, fatigue and recording order may differ.",
            "Reports of completing the drill are stored separately from uploaded clips.",
            "Changes describe these samples and do not show that the advice caused a change.",
        ],
    }


def pattern_state(profile, field):
    data = profile.get("features", {}).get(field, {})
    return {key: data[key] for key in ("result", "direction", "n_made", "n_missed") if key in data} | {
        "profile_status": profile["status"],
    }
