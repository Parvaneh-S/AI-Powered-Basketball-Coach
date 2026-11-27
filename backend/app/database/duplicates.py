
import hashlib
from pathlib import Path

from sqlalchemy import select

from backend.app.database.models import (
    Player,
    PracticeSession,
    Recording,
    SessionLocal,
    Shot,
)


class DuplicateVideoError(Exception):
    """Raised when a player uploads a video already analysed."""

    def __init__(self, existing):
        self.existing = existing

        name = existing.get("original_filename")
        name_text = f" ({name})" if name else ""

        super().__init__(
            "This video was already analysed for this player "
            f"as {existing['video_id']}{name_text}."
        )


def file_sha256(path):
    """Fingerprint a file's exact contents."""

    digest = hashlib.sha256()

    with Path(path).open("rb") as file:
        while chunk := file.read(1024 * 1024):
            digest.update(chunk)

    return digest.hexdigest()


def find_duplicate_in_session(db, player_name, fingerprint):
    recording = db.scalar(select(Recording).join(Player).where(
        Player.name == player_name, Recording.video_sha256 == fingerprint
    ))
    if recording:
        return {"video_id": recording.video_id, "session_id": recording.session_id,
                "original_filename": recording.original_filename}
    shot = db.scalar(select(Shot).join(PracticeSession).join(Player).where(
        Player.name == player_name, Shot.video_sha256 == fingerprint
    ).limit(1))
    if shot:
        return {"video_id": shot.video_id, "shot_id": shot.shot_id, "session_id": shot.session_id,
                "original_filename": shot.original_filename}
    return None


def find_duplicate(player_name, video_sha256):
    """Find an existing owned recording, including records from before the recording table."""
    from backend.app.database.recordings import ensure_recordings

    ensure_recordings()
    with SessionLocal() as db:
        return find_duplicate_in_session(db, player_name, video_sha256)
