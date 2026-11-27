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
from backend.app.agent.retrieval import CoachingTools
from backend.app.agent.video import video_source
from backend.app.database.recordings import list_recordings, recording_details
from backend.app.api.coaching import router as coaching_router
from fastapi import File, Form, UploadFile
from starlette.concurrency import run_in_threadpool

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
    WrongUploadModeError,
)

import json
import re
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request

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


app.include_router(coaching_router)


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
@app.post("/api/recordings/upload", name="upload_recording")
async def upload_shot(
    request: Request,
    file: UploadFile = File(...),
    player_name: str = Form(...),
    shooting_arm: str = Form("right"),
    session_id: int | None = Form(None),
    session_name: str | None = Form(None, max_length=100),
    background: bool = Form(False),
):
    """
    Analyze an upload and save its results to a practice session.
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
    job_started = False

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
        from backend.app.pipeline.video_pipeline import process_single_shot_video, process_uploaded_video

        upload_args = (str(temporary_path), player_name.strip(), shooting_arm, Path(file.filename).name, session_id)
        name = (session_name or "").strip() or None
        if request.scope["route"].name == "upload_recording":
            if background:
                validate_session(player_name.strip(), session_id)
                job_id = queue_analysis_job(
                    upload_args, name, "recording", start_recording_job_thread,
                )
                job_started = True
                return {"job_id": job_id}
            return await run_in_threadpool(process_uploaded_video, *upload_args, name)
        return await run_in_threadpool(process_single_shot_video, *upload_args, session_name=name)

    except HTTPException:
        raise

    except (InvalidSessionError, UnsupportedVideoError, WrongUploadModeError) as exc:
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
        try:
            await file.close()
        finally:
            if not job_started:
                finish_analysis_upload(temporary_path)



# -------------------------------------------------------
# Background analysis
# -------------------------------------------------------
#
# Analysing a practice recording can outlast a browser
# request. The upload starts a background job and
# returns its ID at once; the app then asks for its progress.
# Jobs are kept in memory, so they are lost if the server
# restarts. The job holds the analysis slot (see
# claim_analysis_slot) until it has finished.

jobs = {}
jobs_lock = threading.Lock()


def update_job(job_id, **fields):
    with jobs_lock:
        jobs[job_id].update(fields)


def finish_analysis_upload(video_path):
    try:
        if video_path is not None:
            Path(video_path).unlink(missing_ok=True)
    finally:
        release_analysis_slot()


def queue_analysis_job(upload_args, session_name, mode, start):
    _, player_name, _, filename, _ = upload_args
    job_id = f"job_{uuid4().hex[:12]}"
    with jobs_lock:
        jobs[job_id] = {
            "job_id": job_id,
            "mode": mode,
            "status": "queued",
            "stage": "Starting analysis",
            "done": 0,
            "total": 0,
            "player_name": player_name,
            "original_filename": filename,
        }
    try:
        start(job_id, *upload_args, session_name)
    except Exception:
        with jobs_lock:
            jobs.pop(job_id, None)
        raise
    return job_id


def run_multi_shot_job(job_id, video_path, player_name,
                       shooting_arm, original_filename, session_id, session_name=None):
    run_analysis_job(process_multi_shot_video, job_id, video_path, player_name,
                     shooting_arm, original_filename, session_id, session_name)


def run_recording_job(job_id, video_path, player_name, shooting_arm, original_filename,
                      session_id, session_name):
    from backend.app.pipeline.video_pipeline import process_uploaded_video

    run_analysis_job(process_uploaded_video, job_id, video_path, player_name,
                     shooting_arm, original_filename, session_id, session_name)


def run_analysis_job(analyze, job_id, video_path, player_name, shooting_arm,
                     original_filename, session_id, session_name):
    stage = "Starting analysis"

    def progress(current_stage, done=0, total=0):
        nonlocal stage
        stage = current_stage
        update_job(job_id, stage=stage, done=done, total=total)

    try:
        update_job(job_id, status="running")

        session_options = {"session_name": session_name} if session_name else {}
        summary = analyze(
            video_path,
            player_name,
            shooting_arm,
            original_filename,
            session_id,
            progress=progress,
            **session_options,
        )

        update_job(job_id, status="completed", result=summary)

    except (InvalidSessionError, UnsupportedVideoError,
            DuplicateVideoError, NoShotsFoundError, WrongUploadModeError) as exc:
        update_job(job_id, status="failed", error=str(exc))

    except Exception:
        import logging
        logging.exception("Video processing failed during %s", stage)

        update_job(
            job_id,
            status="failed",
            error=(
                f"Video processing failed during “{stage}”. "
                "Check the backend logs for details."
            ),
        )

    finally:
        finish_analysis_upload(video_path)


@app.post("/api/shots/upload-multi")
async def upload_multi_shot(
    file: UploadFile = File(...),
    player_name: str = Form(...),
    shooting_arm: str = Form("right"),
    session_id: int | None = Form(None),
    session_name: str | None = Form(None, max_length=100),
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

        upload_args = (str(temporary_path), player_name.strip(), shooting_arm, Path(file.filename).name, session_id)
        name = (session_name or "").strip() or None
        job_id = queue_analysis_job(upload_args, name, "multi", start_job_thread)
        job_started = True

    finally:
        try:
            await file.close()
        finally:
            if not job_started:
                finish_analysis_upload(temporary_path)

    return {"job_id": job_id}


def start_job_thread(*args):
    threading.Thread(
        target=run_multi_shot_job,
        args=args,
        daemon=True,
    ).start()


def start_recording_job_thread(*args):
    threading.Thread(target=run_recording_job, args=args, daemon=True).start()


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


@app.get("/api/players/{player_name}/recordings")
def get_player_recordings(player_name: str):
    return list_recordings(player_name.strip())


@app.get("/api/players/{player_name}/recordings/{video_id}")
def get_recording(player_name: str, video_id: str):
    player = player_name.strip()
    recording = recording_details(player, video_id)
    if not recording:
        raise HTTPException(status_code=404, detail="Recording unavailable.")
    tools = CoachingTools(player, video_id, session_id=recording["session_id"])
    attempts = []
    for shot in tools.session_shots:
        if shot.video_id != video_id:
            continue
        analysis = dict(shot.analysis)
        analysis.update(shot_id=shot.shot_id, shot_number=shot.shot_number)
        analysis["shot_outcome"] = {**analysis.get("shot_outcome", {}), "final_outcome": shot.outcome,
                                    "outcome_source": shot.outcome_source}
        attempts.append(analysis)
    return {**recording, "attempts": attempts, "summary": tools.session_summary(),
            "video_available": video_source(video_id) is not None}


@app.get("/api/players/{player_name}/recordings/{video_id}/video")
def get_recording_video(player_name: str, video_id: str):
    from fastapi.responses import FileResponse

    recording = recording_details(player_name.strip(), video_id)
    source = video_source(video_id) if recording else None
    if not source:
        raise HTTPException(status_code=404, detail="Video unavailable.")
    return FileResponse(source[1], media_type="video/mp4", headers={"Cache-Control": "private, no-store"})


@app.get("/api/players/{player_name}/sessions/{session_id}/summary")
def get_session_summary(player_name: str, session_id: int):
    summary = CoachingTools(player_name.strip(), session_id=session_id).session_summary()
    if summary["status"] != "available":
        raise HTTPException(status_code=404, detail="Session unavailable.")
    return summary


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
