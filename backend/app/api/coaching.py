"""HTTP endpoints for coaching, player-entered practice records and owned media."""

from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from typing_extensions import Annotated

from backend.app.agent.coaching_agent import coach, response_text
from backend.app.agent.memory import active_focus, read_memory, reset_memory, save_memory, update_report
from backend.app.agent.progress import assess_progress
from backend.app.agent.retrieval import CoachingTools
from backend.app.agent.video import FOCUSES, video_source

router = APIRouter(prefix="/api/coach")
PlayerName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
ShotIdentifier = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,150}$")]


class Turn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=4000)


class CoachingRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    player_name: PlayerName
    question: str = Field(min_length=1, max_length=2000)
    selected_shot_id: ShotIdentifier | None = None
    session_id: int | None = Field(default=None, gt=0)
    comparison_shot_ids: tuple[ShotIdentifier, ShotIdentifier] | None = None
    history: list[Turn] = Field(default_factory=list, max_length=10)
    multimodal: bool = True


class PlayerContextUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    goal: str | None = Field(default=None, max_length=500)
    experience: str | None = Field(default=None, max_length=120)
    focus_id: str | None = Field(default=None, max_length=64)
    report_kind: Literal["completed", "difficulty", "helped", "did_not_help"] | None = None
    report: str = Field(default="", max_length=800)


@router.post("/ask")
def ask_coaching_agent(request: CoachingRequest):
    result = coach(
        request.player_name, request.question, selected=request.selected_shot_id,
        comparison=request.comparison_shot_ids or (), session_id=request.session_id,
        history=[turn.model_dump() for turn in request.history], multimodal=request.multimodal,
    )
    return {"player_name": request.player_name, "question": request.question, "answer": response_text(result),
            "coaching": result.model_dump(mode="json")}


@router.get("/memory")
def get_coaching_memory(player_name: PlayerName):
    _, memory = read_memory(player_name)
    focus = active_focus(memory)
    progress = assess_progress(CoachingTools(player_name).shots, focus, memory["reports"]) if focus else None
    return {**memory, "focus": focus, "progress": progress}


@router.patch("/memory")
def update_coaching_memory(player_name: PlayerName, request: PlayerContextUpdate):
    revision, memory = read_memory(player_name)
    updated = dict(memory)
    for field in ("goal", "experience"):
        value = getattr(request, field)
        if value is not None:
            updated[field] = value
    if request.report_kind:
        focus = active_focus(memory)
        if not focus or request.focus_id != focus["id"]:
            raise HTTPException(status_code=409, detail="Practice focus changed. Refresh and try again.")
        updated["reports"] = update_report(memory["reports"], focus["id"], request.report_kind, request.report)
    if updated != memory and not save_memory(player_name, revision, updated):
        raise HTTPException(status_code=409, detail="Coaching context changed. Refresh and try again.")
    return {"status": "saved"}


@router.delete("/memory", status_code=204)
def delete_coaching_memory(player_name: PlayerName):
    reset_memory(player_name)
    return Response(status_code=204)


@router.get("/frame")
def get_coaching_frame(player_name: PlayerName, shot_id: ShotIdentifier, reference_id: str = Query(max_length=230)):
    parts = reference_id.split(":")
    if len(parts) not in (4, 6) or parts[0] != "frame" or parts[1] != shot_id:
        raise HTTPException(status_code=404, detail="Frame unavailable.")
    options = {}
    if len(parts) == 6:
        if parts[4] not in FOCUSES or not parts[4]:
            raise HTTPException(status_code=404, detail="Frame unavailable.")
        options = {"focus": parts[4], "from_phase": parts[5]}
    for ref, jpg in CoachingTools(player_name).video_frames(shot_id, (parts[2],), **options):
        if ref.id == reference_id:
            return Response(jpg, media_type="image/jpeg", headers={"Cache-Control": "private, no-store"})
    raise HTTPException(status_code=404, detail="Frame unavailable.")


@router.get("/video")
def get_coaching_video(player_name: PlayerName, shot_id: ShotIdentifier):
    shot = CoachingTools(player_name).resolve(shot_id)
    source = video_source(shot.video_id) if shot else None
    if not source:
        raise HTTPException(status_code=404, detail="Video unavailable.")
    return FileResponse(source[1], media_type="video/mp4", headers={"Cache-Control": "private, no-store"})
