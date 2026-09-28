from __future__ import annotations

from urllib.parse import urlparse

from cua.config import Policy
from cua.models.artifact import ActionType, Step


class PolicyDenied(PermissionError):
    pass


class Guardrails:
    def __init__(self, policy: Policy):
        self.policy = policy

    def check_action(self, action: ActionType) -> None:
        if action not in self.policy.allowed_actions:
            raise PolicyDenied(f"action '{action}' is not allowlisted")

    def check_url(self, url: str) -> None:
        parsed = urlparse(url)
        host = parsed.hostname or ""
        if host not in self.policy.allowed_hosts:
            raise PolicyDenied(f"host '{host}' is not allowlisted")
        prefix_ok = any(url.startswith(prefix) for prefix in self.policy.allowed_url_prefixes)
        local_ok = host in {"127.0.0.1", "localhost"} and parsed.scheme in {"http", "https"}
        if not (prefix_ok or local_ok):
            raise PolicyDenied(f"url '{url}' is outside allowed prefixes")
        path = parsed.path or ""
        for frag in self.policy.forbidden_url_patterns:
            if frag in path:
                raise PolicyDenied(f"url matches forbidden pattern '{frag}'")

    def is_irreversible(self, step: Step) -> bool:
        return step.risk == "irreversible" or step.intent in self.policy.irreversible_intents
