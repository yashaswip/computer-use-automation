from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cua.guardrails.redact import redact_text
from cua.models.results import RunResult


class EvidenceLogger:
    def __init__(self, root: str | Path, run_id: str):
        self.dir = Path(root) / run_id
        self.dir.mkdir(parents=True, exist_ok=True)
        self.log_path = self.dir / "events.jsonl"

    def event(self, kind: str, **payload: Any) -> None:
        row = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "kind": kind,
            **json.loads(redact_text(json.dumps(payload, default=str))),
        }
        with self.log_path.open("a") as f:
            f.write(json.dumps(row) + "\n")

    def write_result(self, result: RunResult) -> Path:
        dumped = json.loads(result.model_dump_json())
        dumped = json.loads(redact_text(json.dumps(dumped)))
        path = self.dir / "result.json"
        path.write_text(json.dumps(dumped, indent=2))
        return path

    def screenshot_path(self, name: str) -> Path:
        return self.dir / name
