from __future__ import annotations

import uuid
from typing import Any

from cua.config import Settings, load_policy
from cua.evidence.logger import EvidenceLogger
from cua.guardrails.policy import Guardrails
from cua.hitl.control import LiveSession
from cua.hitl.handoff import reset as reset_handoff
from cua.hitl.operator_app import bind as bind_operator
from cua.hitl.operator_app import read_decision
from cua.models.artifact import CapabilityArtifact, Signal, Step, bind_locator
from cua.models.observation import Observation
from cua.models.results import RunResult, StepTrace
from cua.surfaces.base import SurfaceDriver
from cua.surfaces.playwright_surface import PlaywrightSurface


class ReplayExecutor:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or Settings()
        self.policy = load_policy(self.settings.policy_path)
        self.guard = Guardrails(self.policy)

    async def run(
        self,
        artifact: CapabilityArtifact,
        params: dict[str, Any],
        *,
        surface: SurfaceDriver | None = None,
        require_confirm_irreversible: bool = True,
        hitl_timeout_s: float = 180.0,
        variant_id: str | None = None,
        entry_url: str | None = None,
    ) -> RunResult:
        run_id = f"rep-{uuid.uuid4().hex[:10]}"
        evidence = EvidenceLogger(self.settings.evidence_dir, run_id)
        reset_handoff()
        art = artifact.apply_variant(variant_id)
        if entry_url:
            art.entry.url = entry_url
        close_surface = False
        if surface is None:
            surface, _ = await PlaywrightSurface.launch(headless=self.settings.headless)
            close_surface = True
            await surface.start_trace(evidence.dir / "trace.zip")
        session = LiveSession(surface, run_id)
        bind_operator(session)
        traces: list[StepTrace] = []
        outputs: dict[str, Any] = {}
        recover_counts: dict[str, int] = {}
        try:
            entry = art.entry.url or self.settings.target_base_url
            self.guard.check_url(entry)
            await surface.goto(entry)
            evidence.event(
                "replay_start",
                capability=art.slug,
                variant=art.variant.variant_id,
                tenant=art.variant.tenant_id,
                params=_public_params(params, art),
            )

            for step in art.steps:
                session.assert_automation()
                obs = await surface.observe()
                self.guard.check_url(obs.url)

                outcome = self._match_business(art, obs)
                if outcome:
                    return await self._business(run_id, art, outcome, obs, traces, evidence, surface, session)

                recovered = await self._recover(art, surface, obs, recover_counts, evidence, params)
                if recovered:
                    obs = await surface.observe()

                outcome = self._match_business(art, obs)
                if outcome:
                    return await self._business(run_id, art, outcome, obs, traces, evidence, surface, session)

                if self.guard.is_irreversible(step) and require_confirm_irreversible:
                    shot = evidence.screenshot_path("irreversible.png")
                    await surface.screenshot(shot)
                    iv = session.escalate(
                        reason=f"irreversible step '{step.intent}' requires operator confirmation",
                        observed=obs.compact()[:800],
                        step_id=step.id,
                        capability_id=art.id,
                        screenshot_path=str(shot),
                    )
                    evidence.event("confirm_irreversible", step=step.id, intervention=iv.id)
                    kind = await session.wait_until_automation(read_decision, timeout_s=hitl_timeout_s)
                    if kind == "abort":
                        result = RunResult(
                            status="aborted",
                            run_id=run_id,
                            mode="replay",
                            capability_id=art.id,
                            failed_step_id=step.id,
                            error="operator declined irreversible action",
                            traces=traces,
                            evidence_dir=str(evidence.dir),
                            intervention_id=iv.id,
                            human_actions=_human_actions(session),
                        )
                        evidence.write_result(result)
                        return result

                try:
                    used = await self._act(surface, step, params, outputs)
                except Exception as e:
                    shot = evidence.screenshot_path(f"fail-{step.id}.png")
                    await surface.screenshot(shot)
                    obs_fail = await surface.observe()
                    outcome = self._match_business(art, obs_fail)
                    if outcome:
                        return await self._business(
                            run_id, art, outcome, obs_fail, traces, evidence, surface, session
                        )
                    traces.append(
                        StepTrace(
                            step_id=step.id,
                            intent=step.intent,
                            action=step.action,
                            observed=obs_fail.compact()[:500],
                            ok=False,
                            error=str(e),
                        )
                    )
                    if step.on_failure == "escalate":
                        iv = session.escalate(
                            reason=str(e),
                            observed=obs_fail.compact()[:800],
                            step_id=step.id,
                            capability_id=art.id,
                            screenshot_path=str(shot),
                        )
                        kind = await session.wait_until_automation(read_decision, timeout_s=hitl_timeout_s)
                        if kind == "resume":
                            continue
                        result = RunResult(
                            status="escalated",
                            run_id=run_id,
                            mode="replay",
                            capability_id=art.id,
                            failed_step_id=step.id,
                            expected=step.intent,
                            observed=obs_fail.compact()[:500],
                            error=str(e),
                            traces=traces,
                            evidence_dir=str(evidence.dir),
                            intervention_id=iv.id,
                            human_actions=_human_actions(session),
                        )
                        evidence.write_result(result)
                        return result
                    result = RunResult(
                        status="failed",
                        run_id=run_id,
                        mode="replay",
                        capability_id=art.id,
                        failed_step_id=step.id,
                        expected=f"{step.action} {step.intent}",
                        observed=obs_fail.compact()[:500],
                        error=str(e),
                        traces=traces,
                        evidence_dir=str(evidence.dir),
                    )
                    evidence.write_result(result)
                    return result

                traces.append(
                    StepTrace(
                        step_id=step.id,
                        intent=step.intent,
                        action=step.action,
                        observed=obs.compact()[:400],
                        ok=True,
                        locator_used=used,
                    )
                )
                evidence.event("step_ok", step=step.id, locator=used)

            obs = await surface.observe(screenshot_to=evidence.screenshot_path("final.png"))
            outcome = self._match_business(art, obs)
            if outcome:
                return await self._business(run_id, art, outcome, obs, traces, evidence, surface, session)
            if not self._signals_ok(art.checkpoint.all_of, obs):
                result = RunResult(
                    status="failed",
                    run_id=run_id,
                    mode="replay",
                    capability_id=art.id,
                    expected=art.checkpoint.description,
                    observed=obs.compact()[:500],
                    error="checkpoint not met",
                    traces=traces,
                    evidence_dir=str(evidence.dir),
                )
                evidence.write_result(result)
                return result
            result = RunResult(
                status="success",
                run_id=run_id,
                mode="replay",
                capability_id=art.id,
                outputs=outputs,
                traces=traces,
                evidence_dir=str(evidence.dir),
            )
            evidence.write_result(result)
            return result
        finally:
            if close_surface:
                await surface.close()

    async def _act(self, surface: SurfaceDriver, step: Step, params: dict[str, Any], outputs: dict[str, Any]) -> str:
        self.guard.check_action(step.action)
        if step.action == "navigate":
            url = step.value.resolve(params) if step.value else ""
            self.guard.check_url(url)
            await surface.goto(url)
            return f"navigate {url}"
        if step.action == "press":
            key = step.value.resolve(params) if step.value else "Enter"
            return await surface.press(key)
        if step.action == "wait":
            await surface.wait_ms(step.wait.settle_ms)
            return "wait"
        if step.action in {"click", "type", "select", "extract", "dismiss"}:
            return await self._with_fallbacks(surface, step, params, outputs)
        raise ValueError(f"unsupported action {step.action}")

    async def _with_fallbacks(
        self,
        surface: SurfaceDriver,
        step: Step,
        params: dict[str, Any],
        outputs: dict[str, Any],
    ) -> str:
        if not step.target:
            raise LookupError(f"step {step.id} missing target")
        last: Exception | None = None
        value = ""
        if step.value:
            if step.value.source == "secret_ref":
                import os

                value = os.environ.get("FIELDBOOK_PASSWORD", "fieldbook")
            else:
                value = step.value.resolve(params)
        for cand in [step.target.primary, *step.target.fallbacks]:
            cand = bind_locator(cand, params)
            try:
                if step.action in {"click", "dismiss"}:
                    return await surface.click(cand)
                if step.action == "type":
                    return await surface.type_text(cand, value)
                if step.action == "select":
                    return await surface.select(cand, value)
                if step.action == "extract":
                    text = await surface.extract(cand)
                    if step.extract:
                        outputs[step.extract.output] = text
                    return f"extract {step.extract.output if step.extract else 'value'}"
            except Exception as e:
                last = e
                continue
        raise last or LookupError(f"no locator worked for {step.id}")

    def _match_business(self, art: CapabilityArtifact, obs: Observation) -> str | None:
        for det in art.business_outcomes:
            if self._signals_ok(det.all_of, obs):
                return det.code
        return None

    def _signals_ok(self, signals: list[Signal], obs: Observation) -> bool:
        for sig in signals:
            if sig.kind == "text_present":
                blob = " ".join(
                    [
                        obs.visible_text,
                        obs.title,
                        " ".join(obs.alerts),
                        obs.aria_yaml,
                    ]
                ).lower()
                if (sig.text or "").lower() not in blob.lower():
                    return False
            elif sig.kind == "url_contains":
                if sig.url_fragment and sig.url_fragment not in obs.url:
                    return False
            elif sig.kind == "role_name_present":
                ok = any(
                    n.role == (sig.role or n.role)
                    and (not sig.name or sig.name.lower() in n.name.lower())
                    for n in obs.a11y
                )
                if not ok:
                    return False
        return True

    async def _recover(self, art, surface, obs, counts, evidence, params) -> bool:
        for det in art.recoverables:
            if not self._signals_ok(det.all_of, obs):
                continue
            used = counts.get(det.code, 0)
            if used >= det.max_times:
                continue
            counts[det.code] = used + 1
            evidence.event("recoverable", code=det.code)
            if det.target and det.action == "click":
                candidates = [det.target.primary, *det.target.fallbacks]
                for cand in candidates:
                    try:
                        await surface.click(bind_locator(cand, params))
                        return True
                    except Exception:
                        continue
        return False

    async def _business(self, run_id, art, code, obs, traces, evidence, surface, session) -> RunResult:
        det = next(d for d in art.business_outcomes if d.code == code)
        shot = evidence.screenshot_path(f"outcome-{code}.png")
        try:
            await surface.screenshot(shot)
        except Exception:
            shot = None
        result = RunResult(
            status="business_outcome",
            run_id=run_id,
            mode="replay",
            capability_id=art.id,
            business_outcome=code,
            business_message=det.description,
            observed=obs.compact()[:500],
            traces=traces,
            evidence_dir=str(evidence.dir),
            human_actions=_human_actions(session),
        )
        evidence.event("business_outcome", code=code, screenshot=str(shot) if shot else None)
        evidence.write_result(result)
        return result


def _human_actions(session: LiveSession) -> list[dict[str, Any]]:
    from cua.hitl.handoff import read_humans

    merged: list[dict[str, Any]] = [a.model_dump() for a in session.state.human_actions]
    seen = {(a["kind"], a["detail"]) for a in merged}
    for item in read_humans():
        key = (item.get("kind"), item.get("detail"))
        if key not in seen:
            merged.append(item)
    return merged


def _public_params(params: dict[str, Any], art: CapabilityArtifact) -> dict[str, Any]:
    sensitive = {p.name for p in art.parameters if p.sensitive}
    return {k: ("[REDACTED]" if k in sensitive else v) for k, v in params.items()}
