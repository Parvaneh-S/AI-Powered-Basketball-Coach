
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
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

DATABASE_URL = f"sqlite:///{(DB_DIR / 'shotcoach.db').as_posix()}"

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
    outcome: Mapped[str] = mapped_column(
        String(20), default="unknown"
    )
    analysis_json: Mapped[str] = mapped_column(Text)

    session: Mapped["PracticeSession"] = relationship(
        back_populates="shots"
    )


def create_tables():
    Base.metadata.create_all(engine)
    print(f"Database initialized: {DB_DIR / 'shotcoach.db'}")


if __name__ == "__main__":
    create_tables()
