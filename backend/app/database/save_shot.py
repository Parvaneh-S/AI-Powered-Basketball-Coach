
import json
import sys
from pathlib import Path

from sqlalchemy import select

from backend.app.database.models import (
    Player,
    PracticeSession,
    Shot,
    SessionLocal,
)


ROOT = Path(__file__).resolve().parents[3]


def save_shot(video_id, player_name, session_id=None):
    analysis_path = (
        ROOT / "outputs" / video_id / "shot_analysis.json"
    )

    if not analysis_path.exists():
        raise FileNotFoundError(
            f"Analysis file not found: {analysis_path}"
        )

    with analysis_path.open(encoding="utf-8") as file:
        analysis = json.load(file)

    shot_id = analysis["shot_id"]
    outcome = analysis["shot_outcome"]["prediction"]

    with SessionLocal.begin() as db:
        # Avoid inserting the same shot twice.
        existing_shot = db.scalar(
            select(Shot).where(Shot.shot_id == shot_id)
        )

        if existing_shot is not None:
            print(f"Shot already exists: {shot_id}")
            return

        # Find or create the player.
        player = db.scalar(
            select(Player).where(
                Player.name == player_name
            )
        )

        if player is None:
            player = Player(name=player_name)
            db.add(player)
            db.flush()

        # Find or create a practice session.
        if session_id is not None:
            practice_session = db.get(
                PracticeSession, session_id
            )

            if practice_session is None:
                raise ValueError(
                    f"Session {session_id} does not exist"
                )

            if practice_session.player_id != player.id:
                raise ValueError(
                    "Session belongs to a different player"
                )
        else:
            practice_session = PracticeSession(
                player_id=player.id
            )
            db.add(practice_session)
            db.flush()

        shot = Shot(
            session_id=practice_session.id,
            shot_id=shot_id,
            video_id=video_id,
            outcome=outcome,
            analysis_json=json.dumps(analysis),
        )

        db.add(shot)
        db.flush()

        print("Shot saved successfully!")
        print(f"Player ID: {player.id}")
        print(f"Session ID: {practice_session.id}")
        print(f"Shot ID: {shot.shot_id}")
        print(f"Outcome: {shot.outcome}")


if __name__ == "__main__":
    if len(sys.argv) not in (3, 4):
        raise SystemExit(
            "Usage: python -m "
            "backend.app.database.save_shot "
            "<video_id> <player_name> [session_id]"
        )

    video_id = sys.argv[1]
    player_name = sys.argv[2]
    session_id = (
        int(sys.argv[3])
        if len(sys.argv) == 4
        else None
    )

    save_shot(video_id, player_name, session_id)
