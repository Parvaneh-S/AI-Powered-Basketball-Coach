
from sqlalchemy import select

from backend.app.database.models import (
    SessionLocal,
    Shot,
)


MANUAL_OUTCOMES = ("made", "missed")


def _label(shot):
    return {
        "shot_id": shot.shot_id,
        "final_outcome": shot.outcome,
        "outcome_source": shot.outcome_source,
        "automatic_prediction": shot.auto_outcome,
    }


def get_outcome_label(shot_id):
    """
    Return the stored outcome label for a shot,
    or None if the shot is not in the database.
    """

    with SessionLocal() as db:
        shot = db.scalar(
            select(Shot).where(Shot.shot_id == shot_id)
        )

        return _label(shot) if shot is not None else None


def set_outcome_label(shot_id, outcome):
    """
    Set a manual outcome ("made" or "missed"),
    or pass "auto" to go back to the detector's result.

    Raises LookupError if the shot does not exist and
    ValueError for any other outcome value.
    """

    if outcome not in MANUAL_OUTCOMES + ("auto",):
        raise ValueError(
            "Outcome must be 'made', 'missed' or 'auto'."
        )

    with SessionLocal.begin() as db:
        shot = db.scalar(
            select(Shot).where(Shot.shot_id == shot_id)
        )

        if shot is None:
            raise LookupError(f"Shot not found: {shot_id}")

        if outcome == "auto":
            shot.outcome = shot.auto_outcome or "unknown"
            shot.outcome_source = "auto"
        else:
            shot.outcome = outcome
            shot.outcome_source = "manual"

        return _label(shot)


def apply_outcome_label(analysis):
    """
    Add the stored label to a shot analysis so every reader
    (UI, API, agent) sees the same final outcome.
    The detector's "prediction" field is left unchanged.
    """

    label = get_outcome_label(analysis.get("shot_id"))

    if label is None:
        return analysis

    shot_outcome = analysis.setdefault("shot_outcome", {})
    shot_outcome["final_outcome"] = label["final_outcome"]
    shot_outcome["outcome_source"] = label["outcome_source"]

    return analysis
