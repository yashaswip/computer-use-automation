"""Cross-process handoff files.

The replay process and the operator page are separate processes. They share
the live browser only through the screen the human can see; they share the
*intervention* through this directory. In-memory session state is not enough.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from cua.models.intervention import InterventionRequest

ROOT = Path(".hitl")


def reset() -> None:
    if not ROOT.exists():
        return
    for path in ROOT.iterdir():
        if path.is_file():
            path.unlink()


def publish(req: InterventionRequest) -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    (ROOT / "intervention.json").write_text(req.model_dump_json(indent=2))


def read_intervention() -> InterventionRequest | None:
    path = ROOT / "intervention.json"
    if not path.exists():
        return None
    return InterventionRequest.model_validate_json(path.read_text())


def write_decision(kind: str) -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    (ROOT / "decision").write_text(kind)
    current = read_intervention()
    if current:
        current.status = "resumed" if kind == "resume" else "aborted"
        publish(current)


def consume_decision() -> str | None:
    path = ROOT / "decision"
    if not path.exists():
        return None
    value = path.read_text().strip()
    path.unlink(missing_ok=True)
    return value or None


def record_human(kind: str, detail: str) -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    row = {"kind": kind, "detail": detail, "at": datetime.now(timezone.utc).isoformat()}
    with (ROOT / "human.jsonl").open("a") as handle:
        handle.write(json.dumps(row) + "\n")


def read_humans() -> list[dict]:
    path = ROOT / "human.jsonl"
    if not path.exists():
        return []
    rows = []
    for line in path.read_text().splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows
