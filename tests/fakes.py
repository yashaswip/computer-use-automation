from __future__ import annotations

from pathlib import Path

from cua.models.artifact import LocatorCandidate
from cua.models.observation import A11yNode, Observation
from cua.surfaces.base import SurfaceDriver


class ScriptedSurface(SurfaceDriver):
    kind = "web"

    def __init__(self, pages: list[Observation]):
        self.pages = pages
        self.i = 0
        self.clicks: list[str] = []
        self.typed: list[tuple[str, str]] = []
        self.url = pages[0].url if pages else "http://127.0.0.1:8765"

    async def goto(self, url: str) -> None:
        self.url = url

    async def observe(self, screenshot_to: Path | None = None) -> Observation:
        obs = self.pages[min(self.i, len(self.pages) - 1)]
        return obs

    async def click(self, locator: LocatorCandidate) -> str:
        self.clicks.append(locator.name or locator.kind)
        self.i = min(self.i + 1, len(self.pages) - 1)
        return locator.name or "click"

    async def type_text(self, locator: LocatorCandidate, value: str) -> str:
        self.typed.append((locator.name or "", value))
        return locator.name or "type"

    async def select(self, locator: LocatorCandidate, value: str) -> str:
        return value

    async def press(self, key: str) -> str:
        return key

    async def extract(self, locator: LocatorCandidate) -> str:
        return "2,540.17"

    async def screenshot(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"")

    async def current_url(self) -> str:
        return self.url

    async def close(self) -> None:
        return None


def page(text: str, url: str = "http://127.0.0.1:8765/search") -> Observation:
    return Observation(
        url=url,
        title="Fieldbook",
        frame="main",
        visible_text=text,
        a11y=[A11yNode(role="button", name="Search", frame="main")],
        alerts=[],
    )
