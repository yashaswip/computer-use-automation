"""Typed, versioned capability artifact — the production contract.

The discovery transcript is not the artifact. This schema is what a calling
agent invokes: parameters in, ordered surface-agnostic steps, outputs out,
plus detectors for business outcomes vs. recoverable vs. hard failure.

Locator strings may contain ``{{param}}`` placeholders. Replay binds them
per invocation so one recording serves every member, not the id used during
discovery. Tenant differences live in ``overlays``, not in a second recording.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field

_TEMPLATE = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")

SCHEMA_VERSION = "1.0"

ActionType = Literal[
    "navigate",
    "click",
    "type",
    "select",
    "press",
    "extract",
    "wait",
    "dismiss",
]
RiskClass = Literal["safe", "reversible", "irreversible"]
LocatorKind = Literal[
    "role_name",
    "label",
    "placeholder",
    "text",
    "test_id",
    "css",
    "xpath",
]
SurfaceKind = Literal["web", "desktop"]
ValueSource = Literal["literal", "parameter", "secret_ref"]
RunStatus = Literal[
    "success",
    "business_outcome",
    "failed",
    "escalated",
    "aborted",
]


class LocatorCandidate(BaseModel):
    """One way to find a control. Replay tries primary then fallbacks."""

    kind: LocatorKind
    role: str | None = None
    name: str | None = None
    exact: bool = True
    nth: int = 0
    label: str | None = None
    placeholder: str | None = None
    text: str | None = None
    test_id: str | None = None
    css: str | None = None
    xpath: str | None = None
    frame: str | None = Field(
        default=None,
        description="Named frame / window, if the control is not in the root surface.",
    )


def bind_locator(candidate: LocatorCandidate, params: dict[str, Any]) -> LocatorCandidate:
    """Substitute ``{{param}}`` in locator strings. Does not mutate the artifact."""

    def sub(value: str | None) -> str | None:
        if value is None or "{{" not in value:
            return value

        def repl(match: re.Match[str]) -> str:
            key = match.group(1)
            if key not in params:
                raise KeyError(f"locator template '{{{{{key}}}}}' has no input value")
            return str(params[key])

        return _TEMPLATE.sub(repl, value)

    return candidate.model_copy(
        update={
            "name": sub(candidate.name),
            "label": sub(candidate.label),
            "placeholder": sub(candidate.placeholder),
            "text": sub(candidate.text),
            "test_id": sub(candidate.test_id),
            "css": sub(candidate.css),
            "xpath": sub(candidate.xpath),
        }
    )


class Target(BaseModel):
    description: str
    primary: LocatorCandidate
    fallbacks: list[LocatorCandidate] = Field(default_factory=list)


class ValueBinding(BaseModel):
    source: ValueSource = "literal"
    literal: str | None = None
    parameter: str | None = None
    secret_ref: str | None = None
    redact: bool = False

    def resolve(self, params: dict[str, Any]) -> str:
        if self.source == "parameter":
            if not self.parameter:
                raise KeyError("parameter binding missing name")
            if self.parameter not in params:
                raise KeyError(f"missing required parameter '{self.parameter}'")
            return str(params[self.parameter])
        if self.source == "secret_ref":
            raise PermissionError("secrets are injected at runtime, never stored")
        return self.literal or ""


class ExtractSpec(BaseModel):
    output: str
    from_attribute: str | None = None


class WaitSpec(BaseModel):
    timeout_ms: int = 8000
    settle_ms: int = 150


class ParamDef(BaseModel):
    name: str
    type: Literal["string", "number", "enum"] = "string"
    required: bool = True
    description: str = ""
    enum: list[str] | None = None
    example: str | None = None
    sensitive: bool = False


class OutputDef(BaseModel):
    name: str
    type: Literal["string", "number"] = "string"
    description: str = ""
    sensitive: bool = False


class Signal(BaseModel):
    kind: Literal["text_present", "url_contains", "role_name_present"]
    text: str | None = None
    url_fragment: str | None = None
    role: str | None = None
    name: str | None = None
    frame: str | None = None


class BusinessOutcomeDetector(BaseModel):
    """Expected domain results — not crashes. Callers must handle these."""

    code: str
    description: str
    all_of: list[Signal]


class RecoverableDetector(BaseModel):
    """Known interstitials / transients the replay may clear without LLM."""

    code: str
    description: str
    all_of: list[Signal]
    action: ActionType = "click"
    target: Target | None = None
    max_times: int = 1


class Checkpoint(BaseModel):
    description: str
    all_of: list[Signal]


class Step(BaseModel):
    id: str
    intent: str
    action: ActionType
    target: Target | None = None
    value: ValueBinding | None = None
    extract: ExtractSpec | None = None
    wait: WaitSpec = Field(default_factory=WaitSpec)
    risk: RiskClass = "safe"
    on_failure: Literal["abort", "escalate", "map_business_outcome"] = "abort"
    notes: str | None = None


class VariantRef(BaseModel):
    """Seam for multi-tenant reuse: base vendor product + optional overlay."""

    vendor_product: str = "fieldbook"
    variant_id: str = "base"
    tenant_id: str | None = None
    app_version: str | None = None


class EntryPoint(BaseModel):
    kind: SurfaceKind = "web"
    url: str | None = None
    app_id: str | None = None


class Provenance(BaseModel):
    discovery_run_id: str
    model: str
    created_at: str
    goal_redacted: str


class OverlayPatch(BaseModel):
    """Per-tenant/version specialization without re-recording the whole flow.

    ``variant_id`` selects which institution build this patch applies to.
    Base replay ignores every patch whose variant is not ``base``.
    """

    variant_id: str = "base"
    tenant_id: str | None = None
    step_id: str | None = None
    recoverable_code: str | None = None
    outcome_code: str | None = None
    replace_target: Target | None = None
    entry_url: str | None = None
    extra_signals: list[Signal] = Field(default_factory=list)


class CapabilityArtifact(BaseModel):
    schema_version: str = SCHEMA_VERSION
    artifact_version: int = 1
    id: str
    slug: str
    title: str
    description: str
    variant: VariantRef = Field(default_factory=VariantRef)
    entry: EntryPoint
    parameters: list[ParamDef] = Field(default_factory=list)
    outputs: list[OutputDef] = Field(default_factory=list)
    steps: list[Step]
    checkpoint: Checkpoint
    business_outcomes: list[BusinessOutcomeDetector] = Field(default_factory=list)
    recoverables: list[RecoverableDetector] = Field(default_factory=list)
    overlays: list[OverlayPatch] = Field(default_factory=list)
    policy_id: str = "fieldbook-demo"
    provenance: Provenance | None = None

    def apply_variant(self, variant_id: str | None = None) -> CapabilityArtifact:
        """Return a copy specialized for one tenant build of this vendor product.

        ``None`` or ``base`` keeps the recorded locators. Any other id applies
        only the overlays tagged with that variant (branded labels, entry URL,
        translated outcome copy).
        """
        selected = variant_id or "base"
        copied = self.model_copy(deep=True)
        by_id = {s.id: s for s in copied.steps}
        for patch in self.overlays:
            if (patch.variant_id or "base") != selected:
                continue
            if patch.entry_url:
                copied.entry.url = patch.entry_url
            if patch.tenant_id:
                copied.variant.tenant_id = patch.tenant_id
            copied.variant.variant_id = selected
            if patch.step_id and patch.replace_target and patch.step_id in by_id:
                by_id[patch.step_id].target = patch.replace_target
            if patch.recoverable_code and patch.replace_target:
                for rec in copied.recoverables:
                    if rec.code == patch.recoverable_code:
                        rec.target = patch.replace_target
            if patch.outcome_code and patch.extra_signals:
                for det in copied.business_outcomes:
                    if det.code == patch.outcome_code:
                        det.all_of = [*det.all_of, *patch.extra_signals]
        if selected != "base":
            copied.variant.variant_id = selected
        copied.steps = [by_id[s.id] for s in copied.steps]
        return copied

    def apply_overlays(self) -> CapabilityArtifact:
        return self.apply_variant(None)
