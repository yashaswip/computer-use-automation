"""Compile a successful discovery trace into a reviewable capability artifact."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from cua.guardrails.redact import redact_text
from cua.models.artifact import (
    BusinessOutcomeDetector,
    CapabilityArtifact,
    Checkpoint,
    EntryPoint,
    ExtractSpec,
    LocatorCandidate,
    OutputDef,
    ParamDef,
    Provenance,
    RecoverableDetector,
    Signal,
    Step,
    Target,
    ValueBinding,
    VariantRef,
)

_ID_LIKE = re.compile(r"^\d{4,}$")


def _slug(title: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return s or "capability"


def _candidate(decision: dict[str, Any]) -> LocatorCandidate:
    return LocatorCandidate(
        kind="role_name",
        role=decision.get("role") or "button",
        name=decision.get("name") or None,
        exact=False,
        nth=int(decision.get("nth") or 0),
        frame=decision.get("frame") or None,
    )


def _parameterize(value: str | None, params: dict[str, ParamDef]) -> str | None:
    if not value:
        return value
    for param in params.values():
        example = param.example or ""
        if len(example) >= 4 and example in value:
            value = value.replace(example, "{{" + param.name + "}}")
    return value


def _parameterize_locator(loc: LocatorCandidate, params: dict[str, ParamDef]) -> LocatorCandidate:
    return loc.model_copy(
        update={
            "name": _parameterize(loc.name, params),
            "label": _parameterize(loc.label, params),
            "text": _parameterize(loc.text, params),
            "placeholder": _parameterize(loc.placeholder, params),
            "css": _parameterize(loc.css, params),
        }
    )


def _checkpoint_marker(final_text: str) -> str:
    blob = final_text or ""
    for marker in ("Sub-Account Opened", "Transaction accepted", "Member Inquiry"):
        if marker.lower() in blob.lower():
            return marker
    return "Member Inquiry"


def _fallbacks(primary: LocatorCandidate) -> list[LocatorCandidate]:
    out: list[LocatorCandidate] = []
    if primary.name:
        out.append(
            LocatorCandidate(
                kind="text",
                text=primary.name,
                exact=False,
                frame=primary.frame,
            )
        )
        out.append(
            LocatorCandidate(
                kind="label",
                label=primary.name,
                exact=False,
                frame=primary.frame,
            )
        )
    return out


class RecordedAct:
    def __init__(
        self,
        decision: dict[str, Any],
        locator_used: str | None,
        typed_value: str | None,
    ):
        self.decision = decision
        self.locator_used = locator_used
        self.typed_value = typed_value


def compile_artifact(
    *,
    run_id: str,
    goal: str,
    model: str,
    entry_url: str,
    acts: list[RecordedAct],
    outputs: dict[str, Any],
    title: str | None = None,
    final_text: str = "",
) -> CapabilityArtifact:
    params: dict[str, ParamDef] = {}
    steps: list[Step] = []
    output_defs = [
        OutputDef(
            name=k,
            description=f"Extracted {k}",
            sensitive=any(token in k.lower() for token in ("account", "ssn", "tax")),
        )
        for k in outputs.keys()
    ]

    for i, act in enumerate(acts, start=1):
        action = act.decision.get("action")
        if action in {"done", "fail", "escalate"}:
            continue
        sid = f"s{i:02d}"
        intent = str(act.decision.get("thought") or action)
        target = None
        if action in {"click", "type", "select", "extract"}:
            primary = _parameterize_locator(_candidate(act.decision), params)
            target = Target(
                description=primary.name or primary.role or action,
                primary=primary,
                fallbacks=_fallbacks(primary),
            )
        value = None
        risk = "safe"
        if action in {"type", "select"} and act.typed_value is not None:
            raw = act.typed_value
            if act.decision.get("name", "").lower() in {"password"} or "password" in intent.lower():
                value = ValueBinding(source="secret_ref", secret_ref="session.password", redact=True)
            elif _ID_LIKE.match(raw) or act.decision.get("name", "").lower() in {
                "member number",
                "operator id",
            }:
                pname = "member_id" if "member" in (act.decision.get("name") or "").lower() else _param_name(
                    act.decision.get("name") or "input"
                )
                if "operator" in (act.decision.get("name") or "").lower():
                    pname = "operator_id"
                    value = ValueBinding(source="literal", literal=raw)
                else:
                    params[pname] = ParamDef(
                        name=pname,
                        description=act.decision.get("name") or pname,
                        example=raw,
                    )
                    value = ValueBinding(source="parameter", parameter=pname)
            else:
                if action == "select":
                    pname = "product"
                    params[pname] = ParamDef(name=pname, description="Product type", example=raw)
                    value = ValueBinding(source="parameter", parameter=pname)
                elif (act.decision.get("name") or "").lower() == "nickname":
                    pname = "nickname"
                    params[pname] = ParamDef(name=pname, required=False, description="Account nickname", example=raw)
                    value = ValueBinding(source="parameter", parameter=pname)
                else:
                    value = ValueBinding(source="literal", literal=raw)
        extract = None
        if action == "extract" and act.decision.get("extract_as"):
            extract = ExtractSpec(output=str(act.decision["extract_as"]))
        if "submit" in intent.lower() or action == "click" and (act.decision.get("name") or "").lower() in {
            "submit"
        }:
            risk = "irreversible"
        steps.append(
            Step(
                id=sid,
                intent=intent,
                action=action,
                target=target,
                value=value,
                extract=extract,
                risk=risk,
            )
        )

    title = title or _title_from_goal(goal)
    return CapabilityArtifact(
        id=run_id,
        slug=_slug(title),
        title=title,
        description=goal,
        variant=VariantRef(vendor_product="fieldbook", variant_id="base"),
        entry=EntryPoint(kind="web", url=entry_url, app_id="fieldbook-6.2"),
        parameters=list(params.values()),
        outputs=output_defs,
        steps=steps,
        checkpoint=Checkpoint(
            description="Final screen shows the heading observed at the end of discovery",
            all_of=[Signal(kind="text_present", text=_checkpoint_marker(final_text))],
        ),
        business_outcomes=[
            BusinessOutcomeDetector(
                code="MEMBER_NOT_FOUND",
                description="Search returned no matching member",
                all_of=[Signal(kind="text_present", text="No matching member record")],
            ),
            BusinessOutcomeDetector(
                code="PERMISSION_DENIED",
                description="Operator cannot view this record",
                all_of=[Signal(kind="text_present", text="Permission denied")],
            ),
            BusinessOutcomeDetector(
                code="SESSION_EXPIRED",
                description="Host signed the operator off",
                all_of=[Signal(kind="text_present", text="Session expired")],
            ),
        ],
        recoverables=[
            RecoverableDetector(
                code="MAINTENANCE_NOTICE",
                description="Dismiss scheduled-maintenance interstitial",
                all_of=[Signal(kind="text_present", text="Scheduled maintenance notice")],
                action="click",
                target=Target(
                    description="Acknowledge notice",
                    primary=LocatorCandidate(
                        kind="role_name",
                        role="button",
                        name="Acknowledge",
                        exact=False,
                        frame="main",
                    ),
                ),
            )
        ],
        provenance=Provenance(
            discovery_run_id=run_id,
            model=model,
            created_at=datetime.now(timezone.utc).isoformat(),
            goal_redacted=redact_text(goal),
        ),
    )


def _param_name(label: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")
    return s or "value"


def _title_from_goal(goal: str) -> str:
    g = goal.lower()
    if "balance" in g:
        return "Lookup member savings balance"
    if "sub-account" in g or "sub account" in g:
        return "Open member sub-account"
    return goal[:60]
