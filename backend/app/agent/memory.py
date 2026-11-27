"""Private local coaching records in the existing SQLite database."""

import json
from datetime import datetime, timezone
from functools import lru_cache
from threading import Lock
from uuid import uuid4

from sqlalchemy import update
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.schema import CreateTable

from backend.app.database.models import Base, SessionLocal, engine


class CoachingMemory(Base):
    __tablename__ = "coaching_memory"

    player: Mapped[str] = mapped_column(primary_key=True)
    revision: Mapped[str]
    payload: Mapped[str]


_schema_lock = Lock()


@lru_cache(maxsize=1)
def _create_table():
    with engine.begin() as connection:
        connection.execute(CreateTable(CoachingMemory.__table__, if_not_exists=True))


def _initialize():
    with _schema_lock:
        _create_table()


def empty_memory():
    return {"goal": "", "experience": "", "preferences": {}, "recommendations": [], "reports": []}


def read_memory(player):
    _initialize()
    with SessionLocal() as db:
        row = db.get(CoachingMemory, player)
        if not row:
            return "", empty_memory()
        memory = {**empty_memory(), **json.loads(row.payload)}
        memory["recommendations"] = latest_distinct(memory["recommendations"], lambda item: item["id"])
        for recommendation in memory["recommendations"]:
            if recommendation.get("verified_personal_correction"):
                recommendation["verified_personal_correction"] = False
        memory["reports"] = latest_distinct(memory["reports"], report_key)
        return row.revision, memory


def latest_distinct(items, key):
    latest = {}
    for item in items:
        identity = key(item)
        latest.pop(identity, None)
        latest[identity] = item
    return list(latest.values())


def report_key(report):
    kind = report["kind"]
    return report["focus_id"], "effect" if kind in ("helped", "did_not_help") else kind


def update_report(reports, focus_id, kind, text="", *, remove=False):
    """Replace the player's prior statement about the same outcome or retract it."""
    entry = {"focus_id": focus_id, "kind": kind, "text": text.strip()}
    key = report_key(entry)
    remaining = [report for report in reports if report_key(report) != key]
    if remove:
        return remaining
    previous = next((report for report in reversed(reports) if report_key(report) == key), None)
    if previous and all(previous.get(field) == value for field, value in entry.items()):
        return reports
    return (remaining + [{**entry, "recorded_at": datetime.now(timezone.utc).isoformat()}])[-50:]


def save_memory(player, revision, memory):
    _initialize()
    values = {"revision": uuid4().hex, "payload": json.dumps(memory, allow_nan=False)}
    if revision:
        statement = update(CoachingMemory).where(
            CoachingMemory.player == player, CoachingMemory.revision == revision
        ).values(**values)
    else:
        statement = insert(CoachingMemory).values(player=player, **values).on_conflict_do_nothing(
            index_elements=["player"]
        )
    with SessionLocal.begin() as db:
        return db.execute(statement).rowcount == 1


def reset_memory(player):
    # Rotate the revision and erase the payload so in-flight requests cannot restore it.
    _initialize()
    statement = insert(CoachingMemory).values(
        player=player, revision=uuid4().hex, payload=json.dumps(empty_memory())
    )
    statement = statement.on_conflict_do_update(
        index_elements=["player"], set_={"payload": statement.excluded.payload,
                                       "revision": statement.excluded.revision}
    )
    with SessionLocal.begin() as db:
        db.execute(statement)


def active_focus(memory):
    recommendations = memory["recommendations"]
    if recommendations and recommendations[-1]["decision"] != "discontinue":
        return recommendations[-1]
    return None
