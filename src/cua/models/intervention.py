from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

ControlOwner = Literal["automation", "human", "closed"]


class InterventionRequest(BaseModel):
    id: str
    run_id: str
    reason: str
    capability_id: str | None = None
    goal_redacted: str | None = None
    step_id: str | None = None
    observed: str
    screenshot_path: str | None = None
    created_at: str
    status: Literal["open", "resumed", "aborted"] = "open"


class HumanAction(BaseModel):
    kind: str
    detail: str
    at: str


class ControlState(BaseModel):
    owner: ControlOwner = "automation"
    intervention: InterventionRequest | None = None
    human_actions: list[HumanAction] = Field(default_factory=list)
