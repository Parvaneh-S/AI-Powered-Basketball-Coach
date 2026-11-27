
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    inspect,
    text,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
    sessionmaker,
)


ROOT = Path(__file__).resolve().parents[3]
DB_DIR = ROOT / "data"
DB_DIR.mkdir(parents=True, exist_ok=True)

# Each machine keeps its own live database (not tracked by git).
# The seed database (tracked by git) holds the shared demo shots.
SEED_DB_PATH = DB_DIR / "seed_shotcoach.db"

DB_PATH = Path(
    os.getenv("SHOTCOACH_DB_PATH", DB_DIR / "shotcoach.db")
)

# On first run, start the live database from the demo shots.
if not DB_PATH.exists() and SEED_DB_PATH.is_file():
    shutil.copy2(SEED_DB_PATH, DB_PATH)

DATABASE_URL = f"sqlite:///{DB_PATH.resolve().as_posix()}"

engine = create_engine(DATABASE_URL)

SessionLocal = sessionmaker(bind=engine)


class Base(DeclarativeBase):
    pass


class Player(Base):
    __tablename__ = "players"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True
    )
    name: Mapped[str] = mapped_column(String(100))

    sessions: Mapped[list["PracticeSession"]] = relationship(
        back_populates="player"
    )


class PracticeSession(Base):
    __tablename__ = "practice_sessions"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True
    )
    player_id: Mapped[int] = mapped_column(
        ForeignKey("players.id")
    )
    name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
    )

    player: Mapped["Player"] = relationship(
        back_populates="sessions"
    )
    shots: Mapped[list["Shot"]] = relationship(
        back_populates="session"
    )


class Recording(Base):
    __tablename__ = "recordings"
    __table_args__ = (UniqueConstraint("player_id", "video_sha256"),)

    video_id: Mapped[str] = mapped_column(String(150), primary_key=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"))
    session_id: Mapped[int] = mapped_column(ForeignKey("practice_sessions.id"), index=True)
    video_sha256: Mapped[str] = mapped_column(String(64))
    original_filename: Mapped[str] = mapped_column(String(255))
    processing_json: Mapped[str] = mapped_column(Text)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime)


class Shot(Base):
    __tablename__ = "shots"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True
    )
    session_id: Mapped[int] = mapped_column(
        ForeignKey("practice_sessions.id")
    )
    shot_id: Mapped[str] = mapped_column(
        String(150), unique=True
    )
    video_id: Mapped[str] = mapped_column(String(150))
    # The outcome used everywhere (history, comparison, agent).
    outcome: Mapped[str] = mapped_column(
        String(20), default="unknown"
    )
    # "auto" when it comes from the detector,
    # "manual" when a user set it.
    outcome_source: Mapped[str] = mapped_column(
        String(20), default="auto"
    )
    # The detector's own result, kept so a manual label can be
    # reset and the detector's accuracy can be measured later.
    auto_outcome: Mapped[str] = mapped_column(
        String(20), default="unknown"
    )
    analysis_json: Mapped[str] = mapped_column(Text)

    # Fingerprint of the source video file, used to detect
    # the same video being uploaded twice. Empty for shots
    # whose original video is not available.
    video_sha256: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True
    )
    original_filename: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    uploaded_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )

    session: Mapped["PracticeSession"] = relationship(
        back_populates="shots"
    )


def create_tables():
    Base.metadata.create_all(engine)
    print(f"Database initialized: {DB_PATH}")


def ensure_shot_columns():
    """
    Add columns introduced after a database was created.
    Existing outcomes count as automatic.
    """

    if "shots" not in inspect(engine).get_table_names():
        return

    existing = {
        column["name"]
        for column in inspect(engine).get_columns("shots")
    }

    with engine.begin() as connection:
        if "outcome_source" not in existing:
            connection.execute(text(
                "ALTER TABLE shots ADD COLUMN "
                "outcome_source VARCHAR(20) NOT NULL "
                "DEFAULT 'auto'"
            ))

        if "auto_outcome" not in existing:
            connection.execute(text(
                "ALTER TABLE shots ADD COLUMN "
                "auto_outcome VARCHAR(20)"
            ))
            connection.execute(text(
                "UPDATE shots SET auto_outcome = outcome"
            ))

        new_optional_columns = {
            "video_sha256": "VARCHAR(64)",
            "original_filename": "VARCHAR(255)",
            "uploaded_at": "DATETIME",
        }

        for name, column_type in new_optional_columns.items():
            if name not in existing:
                connection.execute(text(
                    f"ALTER TABLE shots ADD COLUMN "
                    f"{name} {column_type}"
                ))

        connection.execute(text(
            "CREATE INDEX IF NOT EXISTS "
            "ix_shots_video_sha256 ON shots (video_sha256)"
        ))


ensure_shot_columns()


def ensure_session_name():
    with engine.begin() as connection:
        connection.exec_driver_sql("BEGIN IMMEDIATE")
        schema = inspect(connection)
        if schema.has_table("practice_sessions") and not any(
            column["name"] == "name" for column in schema.get_columns("practice_sessions")
        ):
            connection.execute(text("ALTER TABLE practice_sessions ADD COLUMN name VARCHAR(100)"))


ensure_session_name()


if __name__ == "__main__":
    create_tables()
