"""
Tests for the personal form profile, using simulated players.
Run from the project root:  python -m pytest
"""

import numpy as np

from backend.app.ml.form_profile import (
    FEATURES,
    compute_form_profile,
)


# Typical values for a player whose form does not depend
# on the outcome.
BASE = {
    "min_knee_angle": (140.0, 6.0),
    "knee_angle_range": (35.0, 5.0),
    "release_elbow_angle": (128.0, 5.0),
    "max_elbow_angle": (170.0, 4.0),
    "elbow_angle_range": (90.0, 8.0),
    "elbow_extension_after_release": (45.0, 6.0),
    "shooting_motion_ms": (600.0, 60.0),
}


def simulated_shots(
    n_made,
    n_missed,
    made_shift=None,
    seed=1,
    knee_coverage=100.0,
):
    """
    Create shots whose features are drawn from BASE.
    made_shift moves the mean of chosen features on makes only.
    """

    made_shift = made_shift or {}
    rng = np.random.default_rng(seed)
    shots = []

    for outcome, count in (("made", n_made), ("missed", n_missed)):
        for _ in range(count):
            features = {
                "knee_coverage_pct": knee_coverage,
                "elbow_coverage_pct": 100.0,
            }

            for feature, (mean, sd) in BASE.items():
                if outcome == "made":
                    mean += made_shift.get(feature, 0.0)

                features[feature] = float(rng.normal(mean, sd))

            shots.append({"outcome": outcome, "features": features})

    return shots


def test_finds_a_real_pattern():
    # Makes bend the knees 13 degrees deeper (smaller angle).
    shots = simulated_shots(
        20, 20, made_shift={"min_knee_angle": -13.0}
    )

    profile = compute_form_profile(shots)
    knee = profile["features"]["min_knee_angle"]

    assert profile["status"] == "ok"
    assert knee["result"] == "likely_pattern"
    assert knee["direction"] == "lower_on_makes"
    assert knee["ci"][1] < 0
    assert "min_knee_angle" in profile["likely_patterns"]


def test_finds_no_pattern_when_form_does_not_differ():
    shots = simulated_shots(20, 20)

    profile = compute_form_profile(shots)

    assert profile["status"] == "ok"
    assert profile["likely_patterns"] == []

    for result in profile["features"].values():
        assert result["result"] == "no_clear_difference"
        assert result["ci"][0] <= 0 <= result["ci"][1]


def test_too_few_shots_gives_insufficient_data():
    # Like the current demo: 3 makes and 1 miss.
    shots = simulated_shots(3, 1)

    profile = compute_form_profile(shots)

    assert profile["status"] == "insufficient_data"
    assert profile["counts"]["made"] == 3
    assert profile["counts"]["missed"] == 1
    assert profile["features"] == {}


def test_needs_both_makes_and_misses():
    shots = simulated_shots(15, 2)

    profile = compute_form_profile(shots)

    assert profile["status"] == "insufficient_data"


def test_unknown_outcomes_are_ignored():
    shots = simulated_shots(10, 10)
    shots += [
        {"outcome": "unknown", "features": shot["features"]}
        for shot in shots[:5]
    ]

    profile = compute_form_profile(shots)

    assert profile["counts"]["labelled_shots"] == 20
    assert profile["counts"]["unlabelled_shots"] == 5


def test_poorly_tracked_knees_only_affect_knee_features():
    shots = simulated_shots(10, 10, knee_coverage=40.0)

    profile = compute_form_profile(shots)

    for feature, coverage_key in FEATURES.items():
        result = profile["features"][feature]

        if coverage_key == "knee_coverage_pct":
            assert result["result"] == "insufficient_data"
            assert result["n_made"] == 0
        else:
            assert result["n_made"] == 10


def test_few_false_alarms_across_many_players():
    # 100 players whose form does not depend on the outcome.
    # With the correction, about 5% should see any pattern;
    # without it, about 30% did.
    players = 100

    false_alarms = sum(
        bool(
            compute_form_profile(
                simulated_shots(20, 20, seed=seed)
            )["likely_patterns"]
        )
        for seed in range(players)
    )

    assert false_alarms <= 0.10 * players


def test_strong_patterns_are_still_found():
    # 100 players whose makes bend the knees 13 degrees deeper,
    # each with only 10 makes and 10 misses.
    players = 100

    found = sum(
        "min_knee_angle" in compute_form_profile(
            simulated_shots(
                10, 10,
                made_shift={"min_knee_angle": -13.0},
                seed=seed,
            )
        )["likely_patterns"]
        for seed in range(players)
    )

    assert found >= 0.90 * players


def test_results_are_reproducible():
    shots = simulated_shots(
        20, 20, made_shift={"release_elbow_angle": 6.0}
    )

    assert compute_form_profile(shots) == compute_form_profile(shots)
