"""Adapt the team's existing form-profile model to the coach's evidence policy."""

from backend.app.agent.evidence import FORM_FIELDS, comparable, measurement


def personal_profile(shots, anchor=None):
    try:
        from backend.app.ml.form_profile import FEATURES, _feature_value, compute_form_profile
    except ImportError:
        return {"status": "unavailable", "reason": "Personal form profile is unavailable."}

    # A selected shot defines a cohort when condition metadata exists.
    # Segment-derived measurements that failed the coach's quality policy are excluded.
    anchor = anchor or (shots[-1] if shots else None)
    cohort = [shot for shot in shots if anchor is not None and comparable(anchor, shot)]
    rows = []
    for shot in cohort:
        features = dict(shot.analysis.get("biomechanics", {}))
        for field in FORM_FIELDS:
            features[field] = measurement(shot, field)["value"]
        rows.append({"shot_id": shot.shot_id, "outcome": shot.outcome,
                     "features": features, "outcome_source": shot.outcome_source})
    result = compute_form_profile(rows)
    for field, feature in result["features"].items():
        for outcome in ("made", "missed"):
            feature[f"{outcome}_shot_ids"] = [
                row["shot_id"] for row in rows if row["outcome"] == outcome
                and _feature_value(row, field, FEATURES[field]) is not None
            ]
    result["provenance"] = "Existing form_profile.make_vs_miss_bootstrap_bonferroni_v1"
    result["conditions"] = anchor.conditions if anchor else {}
    result["sample_shots"] = len(rows)
    result["auto_label_count"] = sum(
        row["outcome_source"] != "manual" and row["outcome"] in ("made", "missed") for row in rows
    )
    result["caveats"] += [
        "Only recorded shot type and shooting arm are matched; distance, fatigue and camera equivalence may be unknown.",
        "Automatic labels are experimental. Associations cannot establish causation.",
    ]
    return result
