
import hashlib
from pathlib import Path

from sqlalchemy import select

from backend.app.database.models import (
    Player,
    PracticeSession,
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


def find_duplicate(player_name, video_sha256):
    """
    Return the player's existing shot with this video
    fingerprint, or None if the video is new for them.
    """

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
            .where(
                Player.name == player_name,
                Shot.video_sha256 == video_sha256,
            )
            .limit(1)
        )

        shot = db.scalar(statement)

        if shot is None:
            return None

        return {
            "video_id": shot.video_id,
            "shot_id": shot.shot_id,
            "original_filename": shot.original_filename,
        }
