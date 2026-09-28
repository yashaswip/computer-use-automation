from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

from openai import OpenAI

from cua.agent.prompts import DISCOVERY_SYSTEM, discovery_user
from cua.config import Settings
from cua.models.observation import AgentDecision, Observation


class LLMClient:
    """Discovery brain: OpenAI Responses API + strict Pydantic structured output.

    Replay never uses this. store=False so bank-session content is not kept on the provider.
    """

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or Settings()
        if not self.settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is required for discover")
        self.client = OpenAI(api_key=self.settings.openai_api_key)
        self.model = self.settings.openai_model

    def decide(self, goal: str, observation: Observation, remaining: int, outputs: dict[str, Any]) -> AgentDecision:
        content: list[dict[str, Any]] = [
            {"type": "input_text", "text": discovery_user(goal, observation.compact(), remaining, outputs)}
        ]
        if observation.screenshot_path and Path(observation.screenshot_path).exists():
            raw = Path(observation.screenshot_path).read_bytes()
            b64 = base64.b64encode(raw).decode("ascii")
            content.append(
                {
                    "type": "input_image",
                    "image_url": f"data:image/png;base64,{b64}",
                    "detail": "low",
                }
            )
        resp = self.client.responses.parse(
            model=self.model,
            instructions=DISCOVERY_SYSTEM,
            input=[{"role": "user", "content": content}],
            text_format=AgentDecision,
            temperature=0,
            store=False,
        )
        parsed = resp.output_parsed
        if parsed is None:
            raise RuntimeError("model returned no structured decision")
        return parsed
