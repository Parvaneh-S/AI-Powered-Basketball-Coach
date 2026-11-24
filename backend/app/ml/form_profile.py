"""
Personal form profile: stage 1 of the form-to-outcome model.

For one player, compares each form measurement on made shots
with the same measurement on missed shots. A bootstrap
confidence interval of the difference shows whether the
difference is likely real for this player or could be chance.

Several features are tested at once, so the intervals are
widened (Bonferroni correction): the 5% false-alarm chance
is shared across all features instead of applying to each.
"""

import json
import sys

import numpy as np
from sqlalchemy import select

from backend.app.database.models import (
    Player,
    PracticeSession,
    SessionLocal,
    Shot,
)


# Form features compared between makes and misses, and the
# landmark coverage each one depends on.
FEATURES = {
    "min_knee_angle": "knee_coverage_pct",
    "knee_angle_range": "knee_coverage_pct",
    "release_elbow_angle": "elbow_coverage_pct",
    "max_elbow_angle": "elbow_coverage_pct",
    "elbow_angle_range": "elbow_coverage_pct",
    "elbow_extension_after_release": "elbow_coverage_pct",
    "shooting_motion_ms": None,
}

# Same threshold the measurement step uses for quality.
MIN_COVERAGE_PCT = 80.0

# Minimum data before any personal conclusion is made.
MIN_LABELLED_SHOTS = 10
MIN_PER_OUTCOME = 3

BOOTSTRAP_SAMPLES = 2000
RANDOM_SEED = 0

# Chance of at least one false "likely pattern" for a player
# whose form does not really differ between makes and misses.
FAMILY_FALSE_ALARM_RATE = 0.05

# Shared across all features (Bonferroni correction).
PER_FEATURE_ALPHA = FAMILY_FALSE_ALARM_RATE / len(FEATURES)
CI_LEVEL = 1.0 - PER_FEATURE_ALPHA


def _is_number(value):
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and np.isfinite(value)
    )


def _feature_value(shot, feature, coverage_key):
    """
    Return the feature value if it was reliably measured,
    otherwise None.
    """

    features = shot.get("features", {})
    value = features.get(feature)

    if not _is_number(value):
        return None

    if coverage_key is not None:
        coverage = features.get(coverage_key)

        if not _is_number(coverage) or coverage < MIN_COVERAGE_PCT:
            return None

    return float(value)


def _bootstrap_difference_ci(made, missed, rng):
    """
    Percentile bootstrap interval (level CI_LEVEL) for
    mean(made) - mean(missed).
    """

    made_samples = rng.choice(
        made, size=(BOOTSTRAP_SAMPLES, len(made)), replace=True
    )
    missed_samples = rng.choice(
        missed, size=(BOOTSTRAP_SAMPLES, len(missed)), replace=True
    )

    differences = (
        made_samples.mean(axis=1) - missed_samples.mean(axis=1)
    )

    tail_pct = 100.0 * PER_FEATURE_ALPHA / 2

    low, high = np.percentile(
        differences, [tail_pct, 100.0 - tail_pct]
    )

    return float(low), float(high)


def _effect_size(made, missed):
    """Cohen's d: the difference in units of typical spread."""

    pooled_sd = np.sqrt(
        (
            (len(made) - 1) * np.var(made, ddof=1)
            + (len(missed) - 1) * np.var(missed, ddof=1)
        )
        / (len(made) + len(missed) - 2)
    )

    if pooled_sd == 0:
        return None

    return float((np.mean(made) - np.mean(missed)) / pooled_sd)


def compute_form_profile(shots, seed=RANDOM_SEED):
    """
    Build a form profile from a list of shots.

    Each shot is a dict:
        {"outcome": "made" | "missed" | ...,
         "features": {feature_name: value, ...,
                      "knee_coverage_pct": ...,
                      "elbow_coverage_pct": ...}}

    Shots without a made/missed outcome are ignored.
    """

    labelled = [
        shot for shot in shots
        if shot.get("outcome") in ("made", "missed")
    ]

    made_count = sum(
        1 for shot in labelled if shot["outcome"] == "made"
    )
    missed_count = len(labelled) - made_count

    profile = {
        "method": "make_vs_miss_bootstrap_bonferroni_v1",
        "ci_level": round(CI_LEVEL, 4),
        "counts": {
            "total_shots": len(shots),
            "labelled_shots": len(labelled),
            "made": made_count,
            "missed": missed_count,
            "unlabelled_shots": len(shots) - len(labelled),
        },
        "requirements": {
            "min_labelled_shots": MIN_LABELLED_SHOTS,
            "min_made": MIN_PER_OUTCOME,
            "min_missed": MIN_PER_OUTCOME,
            "min_coverage_pct": MIN_COVERAGE_PCT,
        },
        "features": {},
        "caveats": [
            "Patterns describe this player's recorded shots, "
            "not universal ideal values.",
            "Angles are measured from 2D video and depend on "
            "camera position.",
            "Intervals are corrected for testing several "
            "features, but about 1 in 20 players without a real "
            "pattern may still see one; patterns that hold "
            "across sessions are more trustworthy.",
        ],
    }

    if (
        len(labelled) < MIN_LABELLED_SHOTS
        or made_count < MIN_PER_OUTCOME
        or missed_count < MIN_PER_OUTCOME
    ):
        profile["status"] = "insufficient_data"
        profile["message"] = (
            f"A personal form profile needs at least "
            f"{MIN_LABELLED_SHOTS} shots with a known outcome, "
            f"including at least {MIN_PER_OUTCOME} makes and "
            f"{MIN_PER_OUTCOME} misses. Currently: "
            f"{made_count} made, {missed_count} missed."
        )
        return profile

    rng = np.random.default_rng(seed)

    for feature, coverage_key in FEATURES.items():
        made_values = []
        missed_values = []

        for shot in labelled:
            value = _feature_value(shot, feature, coverage_key)

            if value is None:
                continue

            if shot["outcome"] == "made":
                made_values.append(value)
            else:
                missed_values.append(value)

        result = {
            "n_made": len(made_values),
            "n_missed": len(missed_values),
        }

        if (
            len(made_values) < MIN_PER_OUTCOME
            or len(missed_values) < MIN_PER_OUTCOME
        ):
            result["result"] = "insufficient_data"
            profile["features"][feature] = result
            continue

        made = np.array(made_values)
        missed = np.array(missed_values)

        difference = float(made.mean() - missed.mean())
        ci_low, ci_high = _bootstrap_difference_ci(made, missed, rng)

        # A difference is only reported as a likely pattern
        # when the whole interval is on one side of zero.
        if ci_low > 0 or ci_high < 0:
            pattern = "likely_pattern"
            direction = (
                "higher_on_makes" if difference > 0
                else "lower_on_makes"
            )
        else:
            pattern = "no_clear_difference"
            direction = None

        effect = _effect_size(made, missed)

        result.update({
            "mean_made": round(float(made.mean()), 2),
            "mean_missed": round(float(missed.mean()), 2),
            "difference_made_minus_missed": round(difference, 2),
            "ci": [round(ci_low, 2), round(ci_high, 2)],
            "effect_size": (
                round(effect, 2) if effect is not None else None
            ),
            "result": pattern,
            "direction": direction,
        })

        profile["features"][feature] = result

    profile["status"] = "ok"
    profile["likely_patterns"] = [
        feature
        for feature, result in profile["features"].items()
        if result.get("result") == "likely_pattern"
    ]

    return profile


def load_player_shots(player_name):
    """Read all of a player's shots from every session."""

    with SessionLocal() as db:
        statement = (
            select(Shot)
            .join(
                PracticeSession,
                Shot.session_id == PracticeSession.id,
            )
            .join(
                Player,
                PracticeSession.player_id == Player.id,
            )
            .where(Player.name == player_name)
        )

        shots = []

        for shot in db.scalars(statement).all():
            analysis = json.loads(shot.analysis_json)

            shots.append({
                "shot_id": shot.shot_id,
                "session_id": shot.session_id,
                "outcome": shot.outcome,
                "outcome_source": shot.outcome_source,
                "features": analysis.get("biomechanics", {}),
            })

        return shots


def build_form_profile(player_name):
    """Build the personal form profile for a stored player."""

    profile = compute_form_profile(load_player_shots(player_name))
    profile["player"] = player_name

    return profile


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(
            "Usage: python -m backend.app.ml.form_profile "
            "<player_name>"
        )

    print(json.dumps(build_form_profile(sys.argv[1]), indent=2))
