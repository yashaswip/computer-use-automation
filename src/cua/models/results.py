from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from cua.models.artifact import RunStatus


class StepTrace(BaseModel):
    step_id: str
    intent: str
    action: str
    observed: str
    ok: bool
    locator_used: str | None = None
    error: str | None = None


class RunResult(BaseModel):
    status: RunStatus
    run_id: str
    mode: Literal["discover", "replay"]
    capability_id: str | None = None
    outputs: dict[str, Any] = Field(default_factory=dict)
    business_outcome: str | None = None
    business_message: str | None = None
    failed_step_id: str | None = None
    expected: str | None = None
    observed: str | None = None
    error: str | None = None
    traces: list[StepTrace] = Field(default_factory=list)
    evidence_dir: str | None = None
    intervention_id: str | None = None
    human_actions: list[dict[str, Any]] = Field(default_factory=list)
