"""P2-11 Agent prompt governance schemas — PromptVersion, PromptFeedback."""

from __future__ import annotations

from pydantic import Field

from .common import SchemaModel


class PromptVersionCreate(SchemaModel):
    """Request body for creating a new prompt version."""

    prompt_kind: str | None = "llm"
    prompt_source: str | None = None
    prompt_template: dict = Field(default_factory=dict)
    status: str | None = "draft"
    enabled: bool | None = True
    model_routing: dict | None = None
    change_note: str | None = None
    created_by: str | None = None
    request_id: str | None = None


class PromptVersionActivate(SchemaModel):
    """Request body for activating a prompt version."""

    version: str
    reason: str | None = None


class PromptFeedbackCreate(SchemaModel):
    """Request body for submitting prompt feedback."""

    agent_id: str
    agent_output_id: str | None = None
    prompt_version_id: str | None = None
    run_id: str | None = None
    rating: int | None = Field(default=None, ge=1, le=5)
    category: str | None = "prompt_quality"
    comment: str | None = None
    suggested_changes: dict | None = None
    submitted_by: str | None = None
    request_id: str | None = None
