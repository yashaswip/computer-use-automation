from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class A11yNode(BaseModel):
    role: str
    name: str = ""
    value: str = ""
    frame: str | None = None
    nth: int = 0


class Observation(BaseModel):
    url: str
    title: str
    frame: str | None
    a11y: list[A11yNode] = Field(default_factory=list)
    aria_yaml: str = ""
    visible_text: str = ""
    alerts: list[str] = Field(default_factory=list)
    screenshot_path: str | None = None

    def compact(self, limit: int = 80) -> str:
        lines = [f"url={self.url}", f"title={self.title}", f"frame={self.frame or 'root'}"]
        if self.alerts:
            lines.append("alerts: " + "; ".join(self.alerts))
        if self.aria_yaml.strip():
            lines.append("aria_snapshot (Playwright YAML, mode=ai):")
            lines.append(self.aria_yaml[:4000])
            return "\n".join(lines)
        for node in self.a11y[:limit]:
            val = f' value="{node.value}"' if node.value else ""
            fr = f" frame={node.frame}" if node.frame else ""
            lines.append(f"- {node.role} name={node.name!r}{val}{fr}")
        text = self.visible_text.strip().replace("\n", " | ")
        if text:
            lines.append("text: " + text[:1200])
        return "\n".join(lines)


class AgentDecision(BaseModel):
    """Structured computer-use action. Enforced by the Responses API schema."""

    thought: str = ""
    action: Literal[
        "click",
        "type",
        "select",
        "press",
        "extract",
        "navigate",
        "done",
        "fail",
        "escalate",
    ]
    role: str | None = None
    name: str | None = None
    frame: str | None = None
    nth: int = 0
    value: str | None = None
    extract_as: str | None = None
    outputs: dict[str, str] | None = None
    reason: str | None = None

    def as_record(self) -> dict[str, Any]:
        return self.model_dump()
