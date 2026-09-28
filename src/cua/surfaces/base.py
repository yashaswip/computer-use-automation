"""Surface driver protocol.

Perception and actuation live here. The capability artifact never stores a
Playwright locator object — only role/name/text/css candidates that any
driver (web a11y, desktop UI Automation, etc.) can interpret.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from cua.models.artifact import LocatorCandidate
from cua.models.observation import Observation


class SurfaceDriver(ABC):
    kind: str = "abstract"

    @abstractmethod
    async def goto(self, url: str) -> None: ...

    @abstractmethod
    async def observe(self, screenshot_to: Path | None = None) -> Observation: ...

    @abstractmethod
    async def click(self, locator: LocatorCandidate) -> str: ...

    @abstractmethod
    async def type_text(self, locator: LocatorCandidate, value: str) -> str: ...

    @abstractmethod
    async def select(self, locator: LocatorCandidate, value: str) -> str: ...

    @abstractmethod
    async def press(self, key: str) -> str: ...

    @abstractmethod
    async def extract(self, locator: LocatorCandidate) -> str: ...

    @abstractmethod
    async def screenshot(self, path: Path) -> None: ...

    @abstractmethod
    async def current_url(self) -> str: ...

    @abstractmethod
    async def close(self) -> None: ...

    async def wait_ms(self, ms: int) -> None:
        import asyncio

        await asyncio.sleep(ms / 1000)
