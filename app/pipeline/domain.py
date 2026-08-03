from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def new_id() -> str:
    return str(uuid4())


class ContentTheme(str, Enum):
    motivational = "motivational"
    comedy = "comedy"
    contrast = "contrast"


class ProjectStatus(str, Enum):
    draft = "draft"
    running = "running"
    script_approved = "script_approved"
    review_required = "review_required"
    failed = "failed"


class PipelineStage(str, Enum):
    draft = "draft"
    briefing = "briefing"
    script_generating = "script_generating"
    script_scoring = "script_scoring"
    script_revising = "script_revising"
    script_approved = "script_approved"
    review_required = "review_required"
    failed = "failed"


class ContentProject(BaseModel):
    project_id: str = Field(default_factory=new_id)
    title: str = Field(min_length=1, max_length=200)
    topic: str = Field(min_length=1, max_length=500)
    source_content: str = Field(default="", max_length=20000)
    theme: ContentTheme
    target_audience: str = Field(default="普通中文短视频用户", max_length=500)
    target_duration_seconds: int = Field(default=55, ge=30, le=90)
    must_include: list[str] = Field(default_factory=list)
    must_avoid: list[str] = Field(default_factory=list)
    status: ProjectStatus = ProjectStatus.draft
    created_at: str = Field(default_factory=utc_now)
    updated_at: str = Field(default_factory=utc_now)


class ContentBrief(BaseModel):
    topic: str
    theme: ContentTheme
    audience: str
    core_message: str
    angle: str
    facts: list[str] = Field(default_factory=list)
    must_include: list[str] = Field(default_factory=list)
    must_avoid: list[str] = Field(default_factory=list)
    target_duration_seconds: int = Field(ge=30, le=90)
    emotion_curve: list[str] = Field(min_length=2)
    call_to_action: str = ""
    fact_check_required: list[str] = Field(default_factory=list)


class ScriptScene(BaseModel):
    scene_no: int = Field(ge=1)
    start_seconds: float = Field(ge=0)
    end_seconds: float = Field(gt=0)
    beat_type: str = Field(min_length=1, max_length=64)
    narration: str = Field(min_length=1)
    visual_intent: str = Field(min_length=1)
    material_queries: list[str] = Field(default_factory=list)
    subtitle_emphasis: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_timeline(self):
        if self.end_seconds <= self.start_seconds:
            raise ValueError("scene end_seconds must be greater than start_seconds")
        return self


class StructuredScript(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    hook: str = Field(min_length=1)
    estimated_duration_seconds: int = Field(ge=20, le=120)
    scenes: list[ScriptScene] = Field(min_length=1)

    @property
    def narration(self) -> str:
        return "\n".join(scene.narration.strip() for scene in self.scenes).strip()

    @model_validator(mode="after")
    def validate_scene_order(self):
        ordered = sorted(self.scenes, key=lambda scene: scene.scene_no)
        if [scene.scene_no for scene in ordered] != list(range(1, len(ordered) + 1)):
            raise ValueError("scene_no must be continuous and start at 1")
        for previous, current in zip(ordered, ordered[1:]):
            if current.start_seconds < previous.end_seconds:
                raise ValueError("script scenes must not overlap")
        return self


class ScoreDimension(BaseModel):
    name: str
    score: float = Field(ge=0, le=100)
    weight: float = Field(gt=0, le=1)
    evidence: list[str] = Field(default_factory=list)
    action: str = ""
    confidence: float = Field(default=0.8, ge=0, le=1)


class Scorecard(BaseModel):
    scorecard_id: str = Field(default_factory=new_id)
    overall_score: float = Field(ge=0, le=100)
    passed: bool = False
    dimensions: list[ScoreDimension]
    summary: str = ""
    evaluator: str = "text-llm"
    evaluator_version: str = "script-v1"
    created_at: str = Field(default_factory=utc_now)


class RevisionAction(BaseModel):
    revision_id: str = Field(default_factory=new_id)
    reason: str
    target_dimensions: list[str]
    instructions: list[str]
    created_at: str = Field(default_factory=utc_now)


class ScriptCandidate(BaseModel):
    candidate_id: str = Field(default_factory=new_id)
    run_id: str
    version: int = Field(ge=1)
    parent_candidate_id: str | None = None
    script: StructuredScript
    scorecard: Scorecard
    revision: RevisionAction | None = None
    created_at: str = Field(default_factory=utc_now)


class PipelinePolicy(BaseModel):
    script_threshold: float = Field(default=80, ge=0, le=100)
    critical_dimension_threshold: float = Field(default=70, ge=0, le=100)
    critical_dimensions: list[str] = Field(
        default_factory=lambda: ["hook", "theme_fit", "narrative_structure"]
    )
    max_revisions: int = Field(default=2, ge=0, le=5)
    minimum_improvement: float = Field(default=3, ge=0, le=100)


class PipelineRun(BaseModel):
    run_id: str = Field(default_factory=new_id)
    project_id: str
    status: ProjectStatus = ProjectStatus.draft
    current_stage: PipelineStage = PipelineStage.draft
    policy: PipelinePolicy = Field(default_factory=PipelinePolicy)
    brief: ContentBrief | None = None
    selected_candidate_id: str | None = None
    error: str = ""
    created_at: str = Field(default_factory=utc_now)
    updated_at: str = Field(default_factory=utc_now)


class PipelineEvent(BaseModel):
    event_id: str = Field(default_factory=new_id)
    project_id: str
    run_id: str
    candidate_id: str | None = None
    stage: PipelineStage
    event_type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=utc_now)


class ProjectSnapshot(BaseModel):
    project: ContentProject
    runs: list[PipelineRun] = Field(default_factory=list)
    candidates: list[ScriptCandidate] = Field(default_factory=list)
    events: list[PipelineEvent] = Field(default_factory=list)
