
from datetime import date, timezone

from sqlalchemy import func, select

from backend.app.database.models import (
    Player,
    PracticeSession,
    SessionLocal,
    Shot,
)


class InvalidSessionError(ValueError):
    """Raised when an upload names a session it cannot use."""


def local_date(created_at):
    """
    Convert a stored session time (saved in UTC) to the
    local calendar date.
    """

    if created_at is None:
        return None

    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)

    return created_at.astimezone().date()


def list_player_sessions(player_name):
    """
    Return the player's practice sessions, newest first,
    with their local date and number of shots.
    """

    with SessionLocal() as db:
        statement = (
            select(
                PracticeSession,
                func.count(Shot.id),
                func.count().filter(Shot.outcome == "made"),
                func.count().filter(Shot.outcome == "missed"),
            )
            .join(
                Player,
                PracticeSession.player_id == Player.id,
            )
            .outerjoin(
                Shot,
                Shot.session_id == PracticeSession.id,
            )
            .where(Player.name == player_name)
            .group_by(PracticeSession.id)
            .order_by(
                PracticeSession.created_at.desc(),
                PracticeSession.id.desc(),
            )
        )

        today = date.today()
        sessions = []

        rows = db.execute(statement).all()
        for index, (session, shot_count, made, missed) in enumerate(rows):
            session_date = local_date(session.created_at)

            sessions.append({
                "session_id": session.id,
                "session_number": len(rows) - index,
                "name": session.name,
                "date": (
                    session_date.isoformat()
                    if session_date
                    else None
                ),
                "is_today": session_date == today,
                "shot_count": shot_count,
                "made": made,
                "missed": missed,
                "unknown": shot_count - made - missed,
                "accuracy_pct": round(100 * made / (made + missed), 1) if made + missed else None,
            })

        return sessions


def validate_session(player_name, session_id):
    """
    Check before processing that the chosen session exists
    and belongs to this player.
    """

    if session_id is None:
        return

    with SessionLocal() as db:
        session = db.get(PracticeSession, session_id)

        if session is None:
            raise InvalidSessionError(
                f"Session {session_id} does not exist."
            )

        player = db.get(Player, session.player_id)

        if player is None or player.name != player_name:
            raise InvalidSessionError(
                f"Session {session_id} belongs to a "
                "different player."
            )


def owns_session(player_name, session_id):
    with SessionLocal() as db:
        statement = select(PracticeSession.id).join(Player).where(
            Player.name == player_name, PracticeSession.id == session_id,
        )
        return db.scalar(statement) is not None
