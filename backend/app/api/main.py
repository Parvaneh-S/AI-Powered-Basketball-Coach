from typing import Literal

from backend.app.database.shot_history import (
    get_player_history,
)
from backend.app.database.outcome_labels import (
    apply_outcome_label,
    set_outcome_label,
)
import tempfile
from pydantic import BaseModel, Field
from backend.app.agent.coaching_agent import ask_coach
from fastapi import File, Form, UploadFile
from starlette.concurrency import run_in_threadpool

from backend.app.pipeline.video_pipeline import (
    process_uploaded_video,
)
from backend.app.database.duplicates import (
    DuplicateVideoError,
)
from backend.app.database.sessions import (
    InvalidSessionError,
    list_player_sessions,
    validate_session,
)
from backend.app.pipeline.multi_shot_pipeline import (
    NoShotsFoundError,
    process_multi_shot_video,
)
import threading
from uuid import uuid4
from backend.app.ml.form_profile import (
    build_form_profile,
)
from backend.app.pipeline.video_input import (
    SUPPORTED_EXTENSIONS,
    UnsupportedVideoError,
)

import json
import re
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException

# Load environment variables
load_dotenv()

# Project root
ROOT = Path(__file__).resolve().parents[3]
OUTPUTS_DIR = ROOT / "outputs"

app = FastAPI(
    title="AI Basketball ShotCoach API",
    description="Backend API for basketball shot analysis and AI coaching",
    version="0.1.0",
)


@app.get("/")
def home():
    return {
        "message": "AI Basketball ShotCoach API is running",
        "status": "ok",
    }


@app.get("/api/health")
def health_check():
    return {
        "status": "healthy",
        "service": "basketball-shotcoach",
    }


@app.get("/api/shots/{video_id}")
def get_shot_analysis(video_id: str):

    # Restrict IDs to expected filename characters.
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", video_id):
        raise HTTPException(
            status_code=400,
            detail="Invalid video ID",
        )

    analysis_path = (
        OUTPUTS_DIR / video_id / "shot_analysis.json"
    )

    if not analysis_path.is_file():
        raise HTTPException(
            status_code=404,
            detail=f"Shot analysis not found for {video_id}",
        )

    try:
        with analysis_path.open("r", encoding="utf-8") as f:
            analysis = json.load(f)

    except (OSError, json.JSONDecodeError):
        raise HTTPException(
            status_code=500,
            detail="Unable to read shot analysis",
        )

    # Include any manual outcome label from the database.
    return apply_outcome_label(analysis)


class OutcomeUpdate(BaseModel):
    # "auto" resets to the detector's result.
    outcome: Literal["made", "missed", "auto"]


@app.patch("/api/shots/{shot_id}/outcome")
def update_shot_outcome(shot_id: str, update: OutcomeUpdate):
    """
    Set a shot's outcome manually, or reset it to the
    automatic detector result.
    """

    if not re.fullmatch(r"[A-Za-z0-9_-]{1,150}", shot_id):
        raise HTTPException(
            status_code=400,
            detail="Invalid shot ID",
        )

    try:
        return set_outcome_label(shot_id, update.outcome)

    except LookupError:
        raise HTTPException(
            status_code=404,
            detail=f"Shot not found: {shot_id}",
        )

MAX_UPLOAD_SIZE = 1024 * 1024 * 1024  # 1 GB, for multi-shot videos


# Only one video is analysed at a time. Two analyses at once
# slow each other down, and the same video could be saved twice
# (the duplicate check only sees finished videos).
_analysis_busy = False
_analysis_busy_lock = threading.Lock()


def claim_analysis_slot():
    """Reserve the analysis slot or refuse the upload."""

    global _analysis_busy

    with _analysis_busy_lock:
        if _analysis_busy:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Another video is still being analysed. "
                    "Please wait until it has finished."
                ),
            )

        _analysis_busy = True


def release_analysis_slot():
    global _analysis_busy

    with _analysis_busy_lock:
        _analysis_busy = False


@app.post("/api/shots/upload")
async def upload_shot(
    file: UploadFile = File(...),
    player_name: str = Form(...),
    shooting_arm: str = Form("right"),
    session_id: int | None = Form(None),
):
    """
    Upload one free-throw video, run the complete
    analysis pipeline, and save the result to SQLite.
    Without session_id the shot starts a new practice
    session; with it, the shot joins that session.
    """

    if not player_name.strip():
        raise HTTPException(
            status_code=400,
            detail="Player name cannot be empty.",
        )

    if shooting_arm not in ("left", "right"):
        raise HTTPException(
            status_code=400,
            detail="Shooting arm must be left or right.",
        )

    suffix = (
        Path(file.filename).suffix.lower()
        if file.filename
        else ""
    )

    if suffix not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail="Only MP4 and MOV videos are supported.",
        )

    claim_analysis_slot()

    temporary_path = None

    try:
        # Store the upload temporarily while processing.
        with tempfile.NamedTemporaryFile(
            suffix=suffix,
            prefix="shotcoach_",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            total_size = 0

            while chunk := await file.read(1024 * 1024):
                total_size += len(chunk)

                if total_size > MAX_UPLOAD_SIZE:
                    raise HTTPException(
                        status_code=413,
                        detail="Video exceeds the 1 GB limit.",
                    )

                temporary_file.write(chunk)

        if total_size == 0:
            raise HTTPException(
                status_code=400,
                detail="Uploaded video is empty.",
            )

        # Run the existing nine-stage video pipeline.
        result = await run_in_threadpool(
            process_uploaded_video,
            str(temporary_path),
            player_name.strip(),
            shooting_arm,
            Path(file.filename).name,
            session_id,
        )

        return result

    except HTTPException:
        raise

    except (InvalidSessionError, UnsupportedVideoError) as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    except DuplicateVideoError as exc:
        raise HTTPException(
            status_code=409,
            detail=str(exc),
        ) from exc

    except Exception as exc:
        # Record the error in the server terminal.
        import logging
        logging.exception("Video processing failed")

        raise HTTPException(
            status_code=500,
            detail=(
                "Video processing failed. "
                "Check the server logs for details."
            ),
        ) from exc

    finally:
        # Clean up the temporary API upload.
        await file.close()

        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)

        release_analysis_slot()



# -------------------------------------------------------
# Multi-shot videos
# -------------------------------------------------------
#
# Analysing many shots takes minutes, longer than a browser
# request should wait. The upload starts a background job and
# returns its ID at once; the app then asks for its progress.
# Jobs are kept in memory, so they are lost if the server
# restarts. The job holds the analysis slot (see
# claim_analysis_slot) until it has finished.

jobs = {}
jobs_lock = threading.Lock()


def update_job(job_id, **fields):
    with jobs_lock:
        jobs[job_id].update(fields)


def run_multi_shot_job(job_id, video_path, player_name,
                       shooting_arm, original_filename, session_id):

    def progress(stage, done=0, total=0):
        update_job(job_id, stage=stage, done=done, total=total)

    try:
        update_job(job_id, status="running")

        summary = process_multi_shot_video(
            video_path,
            player_name,
            shooting_arm,
            original_filename,
            session_id,
            progress=progress,
        )

        update_job(job_id, status="completed", result=summary)

    except (InvalidSessionError, UnsupportedVideoError,
            DuplicateVideoError, NoShotsFoundError) as exc:
        update_job(job_id, status="failed", error=str(exc))

    except Exception:
        import logging
        logging.exception("Multi-shot processing failed")

        update_job(
            job_id,
            status="failed",
            error=(
                "Video processing failed. "
                "Check the server logs for details."
            ),
        )

    finally:
        Path(video_path).unlink(missing_ok=True)
        release_analysis_slot()


@app.post("/api/shots/upload-multi")
async def upload_multi_shot(
    file: UploadFile = File(...),
    player_name: str = Form(...),
    shooting_arm: str = Form("right"),
    session_id: int | None = Form(None),
):
    """
    Upload a video with several free throws. Every shot is
    found, cut and analysed in the background, and saved in
    one practice session. Returns a job ID; follow the
    progress with GET /api/jobs/{job_id}.
    """

    if not player_name.strip():
        raise HTTPException(
            status_code=400,
            detail="Player name cannot be empty.",
        )

    if shooting_arm not in ("left", "right"):
        raise HTTPException(
            status_code=400,
            detail="Shooting arm must be left or right.",
        )

    suffix = (
        Path(file.filename).suffix.lower()
        if file.filename
        else ""
    )

    if suffix not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail="Only MP4 and MOV videos are supported.",
        )

    # Check the session now, so a wrong choice is reported
    # before the upload is processed.
    try:
        validate_session(player_name.strip(), session_id)
    except InvalidSessionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Held by the background job until it finishes; released
    # here only if the job is never started.
    claim_analysis_slot()
    job_started = False

    temporary_path = None

    try:
        with tempfile.NamedTemporaryFile(
            suffix=suffix,
            prefix="shotcoach_multi_",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            total_size = 0

            while chunk := await file.read(1024 * 1024):
                total_size += len(chunk)

                if total_size > MAX_UPLOAD_SIZE:
                    raise HTTPException(
                        status_code=413,
                        detail="Video exceeds the 1 GB limit.",
                    )

                temporary_file.write(chunk)

        if total_size == 0:
            raise HTTPException(
                status_code=400,
                detail="Uploaded video is empty.",
            )

        job_id = f"job_{uuid4().hex[:12]}"

        with jobs_lock:
            jobs[job_id] = {
                "job_id": job_id,
                "status": "queued",
                "stage": "Starting",
                "done": 0,
                "total": 0,
                "player_name": player_name.strip(),
                "original_filename": Path(file.filename).name,
            }

        # The background job deletes the temporary file and
        # releases the analysis slot when done.
        start_job_thread(
            job_id,
            str(temporary_path),
            player_name.strip(),
            shooting_arm,
            Path(file.filename).name,
            session_id,
        )
        job_started = True

    finally:
        await file.close()

        if not job_started:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
            release_analysis_slot()

    return {"job_id": job_id}


def start_job_thread(*args):
    threading.Thread(
        target=run_multi_shot_job,
        args=args,
        daemon=True,
    ).start()


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    """Progress and, when finished, the result of a job."""

    with jobs_lock:
        job = jobs.get(job_id)

        if job is None:
            raise HTTPException(
                status_code=404,
                detail=(
                    "Job not found. It may have been lost "
                    "if the server restarted."
                ),
            )

        return dict(job)


class CoachingRequest(BaseModel):
    player_name: str = Field(min_length=1)
    question: str = Field(min_length=1)


@app.post("/api/coach/ask")
async def ask_coaching_agent(request: CoachingRequest):
    """
    Ask the Gemini agent a question about a player's
    shots, measurements, history, or shooting technique.
    """

    player_name = request.player_name.strip()
    question = request.question.strip()

    if not player_name or not question:
        raise HTTPException(
            status_code=400,
            detail="Player name and question cannot be empty.",
        )

    try:
        answer = await run_in_threadpool(
            ask_coach,
            player_name,
            question,
        )

        return {
            "player_name": player_name,
            "question": question,
            "answer": answer,
        }

    except Exception as exc:
        import logging
        logging.exception("Gemini coaching request failed")

        raise HTTPException(
            status_code=500,
            detail="Unable to generate coaching feedback.",
        ) from exc





@app.get("/api/players/{player_name}/sessions")
async def get_player_sessions(player_name: str):
    """
    Return the player's practice sessions, newest first,
    with their date and number of shots.
    """

    if not player_name.strip():
        raise HTTPException(
            status_code=400,
            detail="Player name cannot be empty.",
        )

    return await run_in_threadpool(
        list_player_sessions,
        player_name.strip(),
    )


@app.get("/api/players/{player_name}/form-profile")
async def get_form_profile(player_name: str):
    """
    Return the player's personal form profile: how their
    form differs between made and missed shots.
    """

    if not player_name.strip():
        raise HTTPException(
            status_code=400,
            detail="Player name cannot be empty.",
        )

    return await run_in_threadpool(
        build_form_profile,
        player_name.strip(),
    )


@app.get("/api/players/{player_name}/shots")
async def get_player_shots(player_name: str):
    """
    Return all saved shots for the specified player.
    """

    if not player_name.strip():
        raise HTTPException(
            status_code=400,
            detail="Player name cannot be empty.",
        )

    try:
        history = await run_in_threadpool(
            get_player_history,
            player_name.strip(),
        )

        return history

    except Exception as exc:
        import logging
        logging.exception("Failed to retrieve player history")

        raise HTTPException(
            status_code=500,
            detail="Unable to retrieve player history.",
        ) from exc


    except Exception as exc:
        import logging
        logging.exception("Failed to retrieve player history")

        raise HTTPException(
            status_code=500,
            detail="Unable to retrieve player history.",
        ) from exc
