from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable

from cua.hitl.handoff import publish
from cua.hitl.handoff import record_human as write_human_action
from cua.models.intervention import ControlState, HumanAction, InterventionRequest
from cua.surfaces.base import SurfaceDriver


class ControlError(RuntimeError):
    pass


class LiveSession:
    """Owns the live surface and who may drive it.

    Automation and a human never act concurrently. Escalation keeps the same
    SurfaceDriver (same browser/page) and flips the owner to 'human' until
    resume or abort.
    """

    def __init__(self, surface: SurfaceDriver, run_id: str):
        self.surface = surface
        self.run_id = run_id
        self.state = ControlState()
        self._waiters: list[Callable[[], None]] = []

    @property
    def owner(self) -> str:
        return self.state.owner

    def assert_automation(self) -> None:
        if self.state.owner != "automation":
            raise ControlError(f"automation is not in control (owner={self.state.owner})")

    def escalate(
        self,
        *,
        reason: str,
        observed: str,
        step_id: str | None = None,
        capability_id: str | None = None,
        goal_redacted: str | None = None,
        screenshot_path: str | None = None,
    ) -> InterventionRequest:
        req = InterventionRequest(
            id=f"iv-{self.run_id}",
            run_id=self.run_id,
            reason=reason,
            capability_id=capability_id,
            goal_redacted=goal_redacted,
            step_id=step_id,
            observed=observed,
            screenshot_path=screenshot_path,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        self.state.owner = "human"
        self.state.intervention = req
        publish(req)
        return req

    def record_human(self, kind: str, detail: str) -> None:
        self.state.human_actions.append(
            HumanAction(kind=kind, detail=detail, at=datetime.now(timezone.utc).isoformat())
        )
        write_human_action(kind, detail)

    def resume(self) -> None:
        if self.state.intervention:
            self.state.intervention.status = "resumed"
            publish(self.state.intervention)
        self.state.owner = "automation"

    def abort(self) -> None:
        if self.state.intervention:
            self.state.intervention.status = "aborted"
            publish(self.state.intervention)
        self.state.owner = "closed"

    async def wait_until_automation(self, poll_fn, timeout_s: float = 300.0) -> str:
        """poll_fn should return 'resume' | 'abort' | None."""
        import asyncio
        import time

        deadline = time.time() + timeout_s
        while time.time() < deadline:
            if self.state.owner == "automation":
                return "resume"
            if self.state.owner == "closed":
                return "abort"
            decision = poll_fn()
            if decision == "resume":
                self.resume()
                return "resume"
            if decision == "abort":
                self.abort()
                return "abort"
            await asyncio.sleep(0.4)
        raise TimeoutError("human intervention timed out")
