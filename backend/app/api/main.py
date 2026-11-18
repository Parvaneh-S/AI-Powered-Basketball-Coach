import tempfile
from pydantic import BaseModel, Field
from backend.app.agent.coaching_agent import ask_coach
from fastapi import File, Form, UploadFile
from starlette.concurrency import run_in_threadpool

from backend.app.pipeline.video_pipeline import (
    process_uploaded_video,
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

        return analysis

    except (OSError, json.JSONDecodeError):
        raise HTTPException(
            status_code=500,
            detail="Unable to read shot analysis",
        )

MAX_UPLOAD_SIZE = 100 * 1024 * 1024  # 100 MB


@app.post("/api/shots/upload")
async def upload_shot(
    file: UploadFile = File(...),
    player_name: str = Form(...),
    shooting_arm: str = Form("right"),
):
    """
    Upload one free-throw video, run the complete
    analysis pipeline, and save the result to SQLite.
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

    if not file.filename or (
        Path(file.filename).suffix.lower() != ".mp4"
    ):
        raise HTTPException(
            status_code=400,
            detail="Only MP4 videos are supported.",
        )

    temporary_path = None

    try:
        # Store the upload temporarily while processing.
        with tempfile.NamedTemporaryFile(
            suffix=".mp4",
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
                        detail="Video exceeds the 100 MB limit.",
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
        )

        return result

    except HTTPException:
        raise

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
