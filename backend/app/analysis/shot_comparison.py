
import json
import sys

from sqlalchemy import select

from backend.app.database.models import (
    Player,
    PracticeSession,
    Shot,
    SessionLocal,
)


METRICS = [
    "release_elbow_angle",
    "min_knee_angle",
    "max_elbow_angle",
    "knee_angle_range",
    "elbow_angle_range",
    "elbow_extension_after_release",
    "shooting_motion_ms",
]


def compare_shots(player_name):
    with SessionLocal() as db:
        player = db.scalar(
            select(Player).where(
                Player.name == player_name
            )
        )

        if player is None:
            print(f"Player not found: {player_name}")
            return None

        statement = (
            select(Shot)
            .join(
                PracticeSession,
                Shot.session_id == PracticeSession.id,
            )
            .where(PracticeSession.player_id == player.id)
            .order_by(
                PracticeSession.created_at,
                PracticeSession.id,
                Shot.id,
            )
        )

        shots = db.scalars(statement).all()

        if len(shots) < 2:
            print(
                "At least two shots are required "
                "for comparison."
            )
            return None

        previous = json.loads(shots[-2].analysis_json)
        latest = json.loads(shots[-1].analysis_json)

        previous_features = previous.get(
            "biomechanics", {}
        )
        latest_features = latest.get(
            "biomechanics", {}
        )

        differences = {}

        for metric in METRICS:
            old_value = previous_features.get(metric)
            new_value = latest_features.get(metric)

            if (
                isinstance(old_value, (int, float))
                and not isinstance(old_value, bool)
                and isinstance(new_value, (int, float))
                and not isinstance(new_value, bool)
            ):
                change = round(
                    new_value - old_value, 2
                )
            else:
                change = None

            differences[metric] = {
                "previous": old_value,
                "latest": new_value,
                "change": change,
            }

        result = {
            "player": player_name,
            "previous_shot": shots[-2].shot_id,
            "latest_shot": shots[-1].shot_id,
            "previous_outcome": shots[-2].outcome,
            "latest_outcome": shots[-1].outcome,
            "differences": differences,
        }

        return result


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(
            "Usage: python -m "
            "backend.app.analysis.shot_comparison "
            "<player_name>"
        )

    comparison = compare_shots(sys.argv[1])

    if comparison:
        print(json.dumps(comparison, indent=2))
