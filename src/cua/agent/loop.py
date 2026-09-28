from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from cua.agent.compiler import RecordedAct, compile_artifact
from cua.agent.llm import LLMClient
from cua.config import Settings, load_policy
from cua.evidence.logger import EvidenceLogger
from cua.guardrails.policy import Guardrails, PolicyDenied
from cua.guardrails.redact import redact_text
from cua.hitl.control import LiveSession
from cua.hitl.operator_app import bind as bind_operator
from cua.hitl.operator_app import read_decision
from cua.models.artifact import CapabilityArtifact, LocatorCandidate
from cua.models.results import RunResult, StepTrace
from cua.surfaces.playwright_surface import PlaywrightSurface


class DiscoveryRunner:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or Settings()
        self.policy = load_policy(self.settings.policy_path)
        self.guard = Guardrails(self.policy)
        self.llm = LLMClient(self.settings)

    async def run(self, goal: str, url: str | None = None) -> tuple[CapabilityArtifact, RunResult]:
        run_id = f"disc-{uuid.uuid4().hex[:10]}"
        evidence = EvidenceLogger(self.settings.evidence_dir, run_id)
        url = url or self.settings.target_base_url
        self.guard.check_url(url)
        surface, _ = await PlaywrightSurface.launch(headless=self.settings.headless)
        await surface.start_trace(Path(self.settings.evidence_dir) / run_id / "trace.zip")
        session = LiveSession(surface, run_id)
        bind_operator(session)
        outputs: dict[str, Any] = {}
        acts: list[RecordedAct] = []
        traces: list[StepTrace] = []
        final_text = ""
        try:
            await surface.goto(url)
            evidence.event("start", goal=redact_text(goal), url=url)
            for step_i in range(1, self.policy.max_steps + 1):
                session.assert_automation()
                shot = evidence.screenshot_path(f"step-{step_i:02d}.png")
                obs = await surface.observe(screenshot_to=shot)
                self.guard.check_url(obs.url)
                remaining = self.policy.max_steps - step_i
                decision = self.llm.decide(goal, obs, remaining, outputs)
                evidence.event("decision", step=step_i, decision=_safe_decision(decision.as_record()), url=obs.url)
                action = decision.action
                if action == "done":
                    final_text = obs.visible_text
                    outputs.update(decision.outputs or {})
                    traces.append(StepTrace(step_id=f"s{step_i:02d}", intent="done", action="done", observed=obs.compact()[:400], ok=True))
                    break
                if action == "fail":
                    result = _fail(run_id, "discover", decision.reason or "agent failed", evidence, traces)
                    evidence.write_result(result)
                    raise RuntimeError(result.error)
                if action == "escalate":
                    iv = session.escalate(
                        reason=str(decision.reason or "agent escalate"),
                        observed=obs.compact()[:800],
                        step_id=f"s{step_i:02d}",
                        goal_redacted=redact_text(goal),
                        screenshot_path=str(shot),
                    )
                    evidence.event("escalate", intervention=iv.model_dump())
                    decision_kind = await session.wait_until_automation(read_decision, timeout_s=300)
                    if decision_kind == "abort":
                        result = RunResult(
                            status="aborted",
                            run_id=run_id,
                            mode="discover",
                            error="operator aborted",
                            traces=traces,
                            evidence_dir=str(evidence.dir),
                            intervention_id=iv.id,
                        )
                        evidence.write_result(result)
                        return _empty_artifact(run_id, goal, url), result
                    continue
                locator = None
                used = None
                typed = None
                try:
                    self.guard.check_action(action)  # type: ignore[arg-type]
                    if action == "navigate":
                        dest = str(decision.value or "")
                        self.guard.check_url(dest)
                        await surface.goto(dest)
                        used = f"navigate {dest}"
                    elif action == "press":
                        used = await surface.press(str(decision.value or "Enter"))
                    elif action in {"click", "type", "select", "extract"}:
                        locator = LocatorCandidate(
                            kind="role_name",
                            role=str(decision.role or "button"),
                            name=decision.name,
                            exact=False,
                            nth=int(decision.nth or 0),
                            frame=decision.frame or "main",
                        )
                        if action == "click":
                            used = await surface.click(locator)
                        elif action == "type":
                            typed = str(decision.value or "")
                            used = await surface.type_text(locator, typed)
                        elif action == "select":
                            typed = str(decision.value or "")
                            used = await surface.select(locator, typed)
                        elif action == "extract":
                            text = await surface.extract(locator)
                            key = str(decision.extract_as or "value")
                            outputs[key] = text
                            used = f"extract {key}"
                    else:
                        raise PolicyDenied(f"unknown action {action}")
                except Exception as e:
                    evidence.event("act_error", step=step_i, error=str(e))
                    traces.append(
                        StepTrace(
                            step_id=f"s{step_i:02d}",
                            intent=str(decision.thought or ""),
                            action=action,
                            observed=obs.compact()[:400],
                            ok=False,
                            error=str(e),
                        )
                    )
                    iv = session.escalate(
                        reason=f"discovery act failed: {e}",
                        observed=obs.compact()[:800],
                        step_id=f"s{step_i:02d}",
                        screenshot_path=str(shot),
                        goal_redacted=redact_text(goal),
                    )
                    kind = await session.wait_until_automation(read_decision, timeout_s=180)
                    if kind == "abort":
                        result = RunResult(
                            status="escalated",
                            run_id=run_id,
                            mode="discover",
                            error=str(e),
                            traces=traces,
                            evidence_dir=str(evidence.dir),
                            intervention_id=iv.id,
                        )
                        evidence.write_result(result)
                        raise
                    continue
                acts.append(RecordedAct(decision.as_record(), used, typed))
                traces.append(
                    StepTrace(
                        step_id=f"s{step_i:02d}",
                        intent=str(decision.thought or ""),
                        action=action,
                        observed=redact_text(obs.compact()[:400]),
                        ok=True,
                        locator_used=used,
                    )
                )
            else:
                result = _fail(run_id, "discover", "max steps reached", evidence, traces)
                evidence.write_result(result)
                raise RuntimeError(result.error)

            artifact = compile_artifact(
                run_id=run_id,
                goal=goal,
                model=self.settings.openai_model,
                entry_url=url,
                acts=acts,
                outputs=outputs,
                final_text=final_text,
            )
            result = RunResult(
                status="success",
                run_id=run_id,
                mode="discover",
                capability_id=artifact.id,
                outputs=outputs,
                traces=traces,
                evidence_dir=str(evidence.dir),
            )
            evidence.write_result(result)
            Path(evidence.dir, "artifact.json").write_text(artifact.model_dump_json(indent=2))
            return artifact, result
        finally:
            await surface.close()


def _safe_decision(decision: dict) -> dict:
    d = dict(decision)
    if str(d.get("role") or "").lower() == "password" or "password" in str(d.get("thought") or "").lower():
        d["value"] = "[REDACTED]"
    return d


def _fail(run_id, mode, error, evidence, traces) -> RunResult:
    return RunResult(
        status="failed",
        run_id=run_id,
        mode=mode,
        error=error,
        traces=traces,
        evidence_dir=str(evidence.dir),
    )


def _empty_artifact(run_id: str, goal: str, url: str) -> CapabilityArtifact:
    return compile_artifact(run_id=run_id, goal=goal, model="none", entry_url=url, acts=[], outputs={})
