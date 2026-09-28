from __future__ import annotations

import re
from typing import Any

_SENSITIVE_KEYS = {
    "password",
    "ssn",
    "tax_id",
    "account_number",
    "token",
    "secret",
    "authorization",
}

_PATTERNS = [
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[REDACTED_SSN]"),
    (re.compile(r"\b(?:\d[ -]*?){13,19}\b"), "[REDACTED_PAN]"),
    (re.compile(r"password\s*[:=]\s*\S+", re.I), "password=[REDACTED]"),
    (re.compile(r"\bSV-\d+-[A-F0-9]+\b"), "[REDACTED_ACCOUNT]"),
]


def redact_text(text: str) -> str:
    out = text
    for rx, repl in _PATTERNS:
        out = rx.sub(repl, out)
    return out


def redact_params(params: dict[str, Any], sensitive_names: list[str] | None = None) -> dict[str, Any]:
    names = {n.lower() for n in (sensitive_names or [])} | _SENSITIVE_KEYS
    out: dict[str, Any] = {}
    for k, v in params.items():
        if k.lower() in names:
            out[k] = "[REDACTED]"
        else:
            out[k] = v
    return out
