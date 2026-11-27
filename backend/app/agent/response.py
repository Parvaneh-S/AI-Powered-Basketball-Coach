"""Typed coaching decisions and the player-facing response contract."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Intent = Literal["general", "shot", "explain_miss", "power", "practice", "visual",
                  "compare", "progress", "reassess", "pain", "clarify", "strengths"]
VisualTag = Literal["arm_straightens", "arm_bends", "knee_straightens", "knee_bends", "unclear"]
DecisionType = Literal["continue", "modify", "discontinue", "advance"]

CLARIFICATIONS = {
    "shot": "Which shot would you like to look at?",
    "pair": "Which two shots would you like to compare?",
    "feedback": "What felt different when you tried the cue?",
    "movement": "Which part would you like to see: setup, release, or finish?",
    "practice": "Have you had a chance to try the last practice set?",
}


class NumericReference(BaseModel):
    """The model identifies a fact; only the server supplies its numeric value."""
    model_config = ConfigDict(extra="forbid")
    evidence_id: str = Field(min_length=1, max_length=240)
    field: str = Field(pattern=r"^[a-z_][a-z_0-9]*(?:\.[a-z_0-9]+)*$", max_length=160)


class PracticeDose(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sets: int = Field(ge=1, le=3)
    repetitions: int = Field(ge=1, le=10)
    duration_seconds: int = Field(ge=1, le=600)


class PracticeProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    drill_id: str = Field(max_length=80)
    topic: str = Field(max_length=80)
    instructions: str = Field(min_length=1, max_length=800)
    evaluation: str | None = Field(default=None, max_length=400)
    dose: PracticeDose | None = None


class ResourceChoice(BaseModel):
    # A further offered resource and why it matters for this player (no docstring: it would enter the schema).
    model_config = ConfigDict(extra="forbid")
    id: str = Field(max_length=80)
    note: str | None = Field(default=None, max_length=400)


class CoachAnswer(BaseModel):
    """One conversational reply with optional verified references and actions."""
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=3000)
    evidence_ids: list[str] = Field(default_factory=list, max_length=12)
    facts: list[NumericReference] = Field(default_factory=list, max_length=16)
    frame_ids: list[str] = Field(default_factory=list, max_length=4)
    visual: VisualTag | None = None
    knowledge_ids: list[str] = Field(default_factory=list, max_length=4)
    instructional_resource_id: str | None = Field(default=None, max_length=80)
    # Why the chosen resource matters for this player, what to watch and how to use it.
    resource_note: str | None = Field(default=None, max_length=400)
    # Further offered resources when more than one genuinely helps.
    more_resources: list[ResourceChoice] = Field(default_factory=list, max_length=2)
    practice: PracticeProposal | None = None
    adaptation: DecisionType | None = None


class Decision(BaseModel):
    """Internal fallback selection and validated practice persistence metadata."""

    model_config = ConfigDict(extra="forbid")

    intent: Intent
    observation_ids: list[str] = Field(default_factory=list, max_length=12)
    frame_ids: list[str] = Field(default_factory=list, max_length=4)
    knowledge_id: str | None = None
    clarification: Literal["shot", "pair", "feedback", "movement", "practice"] | None = None
    adaptation: DecisionType | None = None
    visual: VisualTag | None = None
    recognize_strength: bool = False


class Observation(BaseModel):
    text: str
    evidence_ids: list[str]
    video_reference_ids: list[str] = Field(default_factory=list)
    technical: dict | None = None
    visual_focus: str | None = None


class Practice(BaseModel):
    title: str
    instructions: str
    evaluation: str
    drill_id: str | None = None
    dose: PracticeDose | None = None
    reason: str | None = None
    setup: str | None = None
    focus: str | None = None
    success_criteria: str | None = None
    easier_variation: str | None = None
    progression: str | None = None
    reconsider: str | None = None
    assumptions: list[str] = Field(default_factory=list)
    source_info: dict | None = None


class InstructionalResource(BaseModel):
    id: str
    kind: Literal["video", "article"]
    title: str
    organization: str
    creator: str | None = None
    url: str
    section: str | None = None
    verified_on: str
    watch_for: str
    relevance: str
    exercise: str | None = None
    skill_levels: list[str] = Field(default_factory=list)
    thumbnail_url: str | None = None
    embed_url: str | None = None


class CoachingResponse(BaseModel):
    response_type: Intent
    message: str
    show_details: bool = False
    observations: list[Observation] = Field(default_factory=list)
    strengths: list[Observation] = Field(default_factory=list)
    video_references: list[dict] = Field(default_factory=list)
    focus: str | None = None
    cue: str | None = None
    explanation: str | None = None
    guidance_basis: Literal["general", "personal_pattern"] | None = None
    guidance_note: str | None = None
    practice: Practice | None = None
    uncertainty: str | None = None
    knowledge_references: list[dict] = Field(default_factory=list)
    instructional_resource: InstructionalResource | None = None
    additional_resources: list[InstructionalResource] = Field(default_factory=list)
    clarification: str | None = None
    previous_focus: dict | None = None
    progress: dict | None = None
    session_summary: dict | None = None
    memory_update: dict | None = None
    # Machine-readable diagnostics; deliberately omitted from response_text and UI.
    provenance: dict | None = None
    next_step: str | None = None
    # Retain original evidence even when the narrative omits a visible observation.
    authored_evidence: dict | None = None
