from __future__ import annotations

from pathlib import Path

from playwright.async_api import Frame, Locator, Page, async_playwright

from cua.models.artifact import LocatorCandidate
from cua.models.observation import A11yNode, Observation
from cua.surfaces.base import SurfaceDriver

INTERESTING_ROLES = [
    "textbox",
    "searchbox",
    "button",
    "link",
    "combobox",
    "checkbox",
    "radio",
    "heading",
    "alert",
    "status",
    "dialog",
    "cell",
    "columnheader",
    "tab",
    "menuitem",
]


class PlaywrightSurface(SurfaceDriver):
    kind = "web"

    def __init__(self, page: Page):
        self.page = page
        self._preferred_frame: str | None = None
        self._context = page.context
        self._trace_path: Path | None = None

    @classmethod
    async def launch(cls, *, headless: bool = False, cdp_url: str | None = None) -> tuple["PlaywrightSurface", object]:
        pw = await async_playwright().start()
        if cdp_url:
            browser = await pw.chromium.connect_over_cdp(cdp_url)
            context = browser.contexts[0] if browser.contexts else await browser.new_context()
            page = context.pages[0] if context.pages else await context.new_page()
        else:
            browser = await pw.chromium.launch(headless=headless)
            context = await browser.new_context(viewport={"width": 1100, "height": 720})
            page = await context.new_page()
        surface = cls(page)
        surface._pw = pw
        surface._browser = browser
        return surface, pw

    async def start_trace(self, path: Path) -> None:
        self._trace_path = path
        await self._context.tracing.start(screenshots=True, snapshots=True, sources=False)

    async def goto(self, url: str) -> None:
        await self.page.goto(url, wait_until="domcontentloaded")
        self._preferred_frame = "main" if self._frame("main") else None

    async def current_url(self) -> str:
        frame = self._active_frame()
        try:
            return frame.url
        except Exception:
            return self.page.url

    async def observe(self, screenshot_to: Path | None = None) -> Observation:
        await self.page.wait_for_timeout(80)
        frame = self._active_frame()
        yaml_chunks: list[str] = []
        nodes: list[A11yNode] = []
        for fr in self._frames():
            yaml_chunks.append(await self._aria_yaml(fr))
            nodes.extend(await self._snapshot_frame(fr))
        aria_yaml = "\n".join(c for c in yaml_chunks if c).strip()
        text = ""
        try:
            text = await frame.locator("body").inner_text(timeout=2000)
        except Exception:
            text = ""
        alerts = [n.name for n in nodes if n.role in {"alert", "status"} and n.name]
        if not alerts:
            alerts = [
                line.strip()
                for line in aria_yaml.splitlines()
                if "alert" in line.lower() or "status" in line.lower()
            ][:8]
        path = None
        if screenshot_to:
            await self.screenshot(screenshot_to)
            path = str(screenshot_to)
        title = ""
        try:
            title = await frame.title()
        except Exception:
            title = await self.page.title()
        return Observation(
            url=await self.current_url(),
            title=title,
            frame=self._name_of(frame),
            a11y=nodes,
            aria_yaml=aria_yaml,
            visible_text=text[:2500],
            alerts=alerts,
            screenshot_path=path,
        )

    async def click(self, locator: LocatorCandidate) -> str:
        handle, used = await self._resolve(locator)
        await handle.click(timeout=locator_timeout(locator))
        try:
            await self.page.wait_for_load_state("domcontentloaded", timeout=5000)
        except Exception:
            pass
        await self.page.wait_for_timeout(200)
        return used

    async def type_text(self, locator: LocatorCandidate, value: str) -> str:
        handle, used = await self._resolve(locator)
        await handle.fill(value, timeout=locator_timeout(locator))
        return used

    async def select(self, locator: LocatorCandidate, value: str) -> str:
        handle, used = await self._resolve(locator)
        await handle.select_option(value, timeout=locator_timeout(locator))
        return used

    async def press(self, key: str) -> str:
        await self.page.keyboard.press(key)
        return f"press:{key}"

    async def extract(self, locator: LocatorCandidate) -> str:
        handle, _ = await self._resolve(locator)
        text = await handle.inner_text(timeout=locator_timeout(locator))
        return text.strip()

    async def screenshot(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        await self.page.screenshot(path=str(path), full_page=True)

    async def close(self) -> None:
        if self._trace_path:
            try:
                self._trace_path.parent.mkdir(parents=True, exist_ok=True)
                await self._context.tracing.stop(path=str(self._trace_path))
            except Exception:
                pass
            self._trace_path = None
        browser = getattr(self, "_browser", None)
        pw = getattr(self, "_pw", None)
        if browser:
            await browser.close()
        if pw:
            await pw.stop()

    def _frame(self, name: str) -> Frame | None:
        for fr in self.page.frames:
            if fr.name == name:
                return fr
        return None

    def _frames(self) -> list[Frame]:
        useful: list[Frame] = []
        for fr in self.page.frames:
            url = fr.url or ""
            if url in {"", "about:blank"} and not fr.name:
                continue
            useful.append(fr)
        return useful or [self.page.main_frame]

    def _name_of(self, frame: Frame) -> str | None:
        return frame.name or None

    def _active_frame(self) -> Frame:
        if self._preferred_frame:
            fr = self._frame(self._preferred_frame)
            if fr:
                return fr
        main = self._frame("main")
        return main or self.page.main_frame

    async def _aria_yaml(self, frame: Frame) -> str:
        label = self._name_of(frame) or "root"
        try:
            snap = await frame.locator("body").aria_snapshot(mode="ai", timeout=800)
        except Exception:
            try:
                snap = await frame.locator("body").aria_snapshot(timeout=800)
            except Exception:
                return ""
        return f"# frame={label}\n{snap}"

    async def _snapshot_frame(self, frame: Frame) -> list[A11yNode]:
        nodes: list[A11yNode] = []
        fname = self._name_of(frame)
        for role in INTERESTING_ROLES:
            try:
                loc = frame.get_by_role(role)  # type: ignore[arg-type]
                count = await loc.count()
            except Exception:
                continue
            for i in range(min(count, 20)):
                item = loc.nth(i)
                try:
                    name = (await item.get_attribute("aria-label")) or ""
                    if not name:
                        name = (await item.inner_text(timeout=500)).strip()
                    name = " ".join(name.split())[:80]
                    value = ""
                    try:
                        raw_val = await item.input_value(timeout=200)
                    except Exception:
                        raw_val = ""
                    if role in {"textbox", "searchbox"} and "password" in (name or "").lower():
                        value = "[REDACTED]"
                    else:
                        value = raw_val[:80]
                    nodes.append(A11yNode(role=role, name=name, value=value[:80], frame=fname, nth=i))
                except Exception:
                    continue
        return nodes

    async def _resolve(self, candidate: LocatorCandidate) -> tuple[Locator, str]:
        frames = []
        if candidate.frame:
            fr = self._frame(candidate.frame)
            if fr:
                frames = [fr]
        if not frames:
            frames = [self._active_frame()] + [f for f in self._frames() if f is not self._active_frame()]
        last_err: Exception | None = None
        for frame in frames:
            try:
                loc = self._locator_in(frame, candidate)
                await loc.first.wait_for(state="visible", timeout=2500)
                if candidate.frame or self._name_of(frame):
                    self._preferred_frame = candidate.frame or self._name_of(frame)
                desc = describe_locator(candidate, self._name_of(frame))
                return loc.nth(candidate.nth), desc
            except Exception as e:
                last_err = e
                continue
        raise LookupError(f"control not found: {describe_locator(candidate, candidate.frame)} ({last_err})")

    def _locator_in(self, frame: Frame, c: LocatorCandidate) -> Locator:
        if c.kind == "role_name":
            kwargs: dict = {}
            if c.name:
                kwargs["name"] = c.name
                kwargs["exact"] = c.exact
            return frame.get_by_role(c.role or "button", **kwargs)  # type: ignore[arg-type]
        if c.kind == "label" and c.label:
            return frame.get_by_label(c.label, exact=c.exact)
        if c.kind == "placeholder" and c.placeholder:
            return frame.get_by_placeholder(c.placeholder, exact=c.exact)
        if c.kind == "text" and c.text:
            return frame.get_by_text(c.text, exact=c.exact)
        if c.kind == "test_id" and c.test_id:
            return frame.get_by_test_id(c.test_id)
        if c.kind == "css" and c.css:
            return frame.locator(c.css)
        if c.kind == "xpath" and c.xpath:
            return frame.locator(f"xpath={c.xpath}")
        raise LookupError(f"incomplete locator {c.kind}")


def describe_locator(c: LocatorCandidate, frame: str | None) -> str:
    bits = [c.kind]
    if c.role:
        bits.append(f"role={c.role}")
    if c.name:
        bits.append(f"name={c.name!r}")
    if c.text:
        bits.append(f"text={c.text!r}")
    if c.css:
        bits.append(f"css={c.css}")
    if frame:
        bits.append(f"frame={frame}")
    return " ".join(bits)


def locator_timeout(c: LocatorCandidate) -> int:
    return 8000
