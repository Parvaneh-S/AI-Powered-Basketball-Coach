
import json
import sys

from sqlalchemy import select

from backend.app.database.models import (
    Player,
    PracticeSession,
    Shot,
    SessionLocal,
)


def get_player_history(player_name):
    with SessionLocal() as db:
        player = db.scalar(
            select(Player).where(
                Player.name == player_name
            )
        )

        if player is None:
            print(f"Player not found: {player_name}")
            return []

        statement = (
            select(Shot, PracticeSession)
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

        records = db.execute(statement).all()

        history = []

        for shot, session in records:
            analysis = json.loads(shot.analysis_json)
            biomechanics = analysis.get(
                "biomechanics", {}
            )

            history.append({
                "session_id": session.id,
                "shot_id": shot.shot_id,
                "video_id": shot.video_id,
                "outcome": shot.outcome,
                "release_elbow_angle": (
                    biomechanics.get(
                        "release_elbow_angle"
                    )
                ),
                "min_knee_angle": (
                    biomechanics.get(
                        "min_knee_angle"
                    )
                ),
                "knee_angle_range": (
                    biomechanics.get(
                        "knee_angle_range"
                    )
                ),
                "elbow_extension_after_release": (
                    biomechanics.get(
                        "elbow_extension_after_release"
                    )
                ),
                "measurement_quality": (
                    biomechanics.get(
                        "measurement_quality"
                    )
                ),
            })

        return history


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(
            "Usage: python -m "
            "backend.app.database.shot_history "
            "<player_name>"
        )

    history = get_player_history(sys.argv[1])

    print(json.dumps(history, indent=2))
