"""Persist a recording and all of its detected shots as one transaction."""

import json
from functools import lru_cache
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.schema import CreateTable, CreateIndex

from backend.app.database.models import Player, PracticeSession, Recording, SessionLocal, Shot, engine


@lru_cache(maxsize=1)
def ensure_recordings():
    with engine.begin() as connection:
        connection.execute(CreateTable(Recording.__table__, if_not_exists=True))
        for index in Recording.__table__.indexes:
            connection.execute(CreateIndex(index, if_not_exists=True))


def save_recording(video_id, player_name, session_id, fingerprint, filename, analyses, processing, session_name=None):
    from backend.app.database.duplicates import DuplicateVideoError, find_duplicate_in_session

    ensure_recordings()
    with SessionLocal.begin() as db:
        # Serialize the final duplicate check and publication, including legacy rows.
        db.connection().exec_driver_sql("BEGIN IMMEDIATE")
        if existing := find_duplicate_in_session(db, player_name, fingerprint):
            raise DuplicateVideoError(existing)
        player = db.scalar(select(Player).where(Player.name == player_name))
        if player is None:
            player = Player(name=player_name)
            db.add(player)
            db.flush()

        if session_id is None:
            session = PracticeSession(player_id=player.id, name=session_name)
            db.add(session)
            db.flush()
        else:
            from backend.app.database.sessions import InvalidSessionError

            session = db.get(PracticeSession, session_id)
            if session is None or session.player_id != player.id:
                raise InvalidSessionError("The selected session is unavailable for this player.")

        uploaded = datetime.now(timezone.utc)
        db.add(Recording(video_id=video_id, player_id=player.id, session_id=session.id,
                         video_sha256=fingerprint, original_filename=filename,
                         processing_json=json.dumps(processing), uploaded_at=uploaded))
        for analysis in analyses:
            outcome = analysis["shot_outcome"]["prediction"]
            db.add(Shot(session_id=session.id, shot_id=analysis["shot_id"], video_id=video_id,
                        outcome=outcome, auto_outcome=outcome, outcome_source="auto",
                        analysis_json=json.dumps(analysis, allow_nan=False),
                        original_filename=filename, uploaded_at=uploaded))
        return session.id


def recording_details(player_name, video_id):
    ensure_recordings()
    with SessionLocal() as db:
        recording = db.scalar(select(Recording).join(Player).where(
            Player.name == player_name, Recording.video_id == video_id
        ))
        if recording:
            return {"video_id": video_id, "session_id": recording.session_id,
                    "processing": json.loads(recording.processing_json)}
        # Legacy recordings were represented by their individual shot records.
        session_id = db.scalar(select(Shot.session_id).join(PracticeSession).join(Player).where(
            Player.name == player_name, Shot.video_id == video_id
        ).limit(1))
        return {"video_id": video_id, "session_id": session_id, "processing": {}} if session_id is not None else None


def list_recordings(player_name):
    ensure_recordings()
    with SessionLocal() as db:
        current = db.execute(select(Recording, func.count(Shot.id)).join(Player).outerjoin(
            Shot, (Shot.session_id == Recording.session_id) & (Shot.video_id == Recording.video_id)
        ).where(Player.name == player_name).group_by(Recording.video_id)).all()
        legacy = db.execute(select(Shot.video_id, Shot.session_id, func.count(Shot.id),
                                   func.max(Shot.original_filename)).join(PracticeSession).join(Player).where(
            Player.name == player_name,
        ).group_by(Shot.video_id, Shot.session_id)).all()
    recordings = {row.video_id: {"video_id": row.video_id, "session_id": row.session_id,
                                 "shot_count": count, "name": row.original_filename}
                  for row, count in current}
    for video_id, session_id, count, filename in legacy:
        recordings.setdefault(video_id, {"video_id": video_id, "session_id": session_id,
                                         "shot_count": count, "name": filename})
    return sorted(recordings.values(), key=lambda row: (row["session_id"], row["video_id"]), reverse=True)
