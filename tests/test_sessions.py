"""
Each player sees their own session numbers (1, 2, ...), even
though the database numbers sessions across all players.
"""

from datetime import datetime, timedelta, timezone

from backend.app.database.models import (
    Player,
    PracticeSession,
    SessionLocal,
)
from backend.app.database.sessions import list_player_sessions


def add_player_with_sessions(name, count):
    start = datetime.now(timezone.utc) - timedelta(days=count)

    with SessionLocal.begin() as db:
        player = Player(name=name)
        db.add(player)
        db.flush()

        for day in range(count):
            db.add(PracticeSession(
                player_id=player.id,
                created_at=start + timedelta(days=day),
            ))


def test_session_numbers_count_per_player():
    add_player_with_sessions("NumberingA", 2)
    add_player_with_sessions("NumberingB", 3)

    for name, count in (("NumberingA", 2), ("NumberingB", 3)):
        sessions = list_player_sessions(name)

        # Newest first: the newest has the highest number,
        # the oldest is 1.
        assert [s["session_number"] for s in sessions] == list(
            range(count, 0, -1)
        )

    # The database IDs are still unique across players.
    ids = [s["session_id"] for s in list_player_sessions("NumberingA")]
    ids += [s["session_id"] for s in list_player_sessions("NumberingB")]
    assert len(set(ids)) == 5
