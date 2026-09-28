from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    openai_api_key: str = ""
    openai_model: str = "gpt-4.1-mini"
    llm_provider: str = "openai"
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-5"
    target_base_url: str = "http://127.0.0.1:8765"
    operator_base_url: str = "http://127.0.0.1:8766"
    headless: bool = False
    capabilities_dir: str = "capabilities"
    evidence_dir: str = "evidence/runs"
    policy_path: str = "policies/default.yaml"


class Policy(BaseModel):
    id: str
    allowed_hosts: list[str]
    allowed_url_prefixes: list[str]
    allowed_actions: list[str]
    forbidden_url_patterns: list[str] = Field(default_factory=list)
    irreversible_intents: list[str] = Field(default_factory=list)
    max_steps: int = 25
    max_duration_seconds: int = 180
    sensitive_param_names: list[str] = Field(default_factory=list)


def load_policy(path: str | Path | None = None) -> Policy:
    p = Path(path or Settings().policy_path)
    data = yaml.safe_load(p.read_text())
    return Policy.model_validate(data)
