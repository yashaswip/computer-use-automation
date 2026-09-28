import asyncio
from pathlib import Path

import pytest

from cua.catalog.store import Catalog
from cua.hitl.control import LiveSession
from cua.models.artifact import LocatorCandidate
from cua.replay.executor import ReplayExecutor
from cua.surfaces.playwright_surface import PlaywrightSurface


@pytest.mark.asyncio
async def test_live_replay_happy_path(target_url):
    art = Catalog().load("lookup-member-savings-balance")
    art.entry.url = target_url + "/login"
    surface, _ = await PlaywrightSurface.launch(headless=True)
    try:
        result = await ReplayExecutor().run(
            art,
            {"member_id": "12345"},
            surface=surface,
            require_confirm_irreversible=False,
        )
        assert result.status == "success"
        assert "2,540.17" in str(result.outputs.get("savings_balance"))
    finally:
        await surface.close()


@pytest.mark.asyncio
async def test_live_replay_other_member_uses_template(target_url):
    """The recorded link name contained 12345. Replay must bind a different id."""
    art = Catalog().load("lookup-member-savings-balance")
    art.entry.url = target_url + "/login"
    surface, _ = await PlaywrightSurface.launch(headless=True)
    try:
        result = await ReplayExecutor().run(
            art,
            {"member_id": "67890"},
            surface=surface,
            require_confirm_irreversible=False,
        )
        assert result.status == "success", result.error
        assert "110.00" in str(result.outputs.get("savings_balance"))
    finally:
        await surface.close()


@pytest.mark.asyncio
async def test_lakeshore_overlay_replays_same_capability(target_url):
    art = Catalog().load("lookup-member-savings-balance")
    surface, _ = await PlaywrightSurface.launch(headless=True)
    try:
        result = await ReplayExecutor().run(
            art,
            {"member_id": "12345"},
            surface=surface,
            require_confirm_irreversible=False,
            variant_id="lakeshore",
            entry_url=target_url + "/login?skin=lakeshore",
        )
        assert result.status == "success", result.error
        assert "2,540.17" in str(result.outputs.get("savings_balance"))
    finally:
        await surface.close()


@pytest.mark.asyncio
async def test_base_locators_do_not_fit_lakeshore(target_url):
    art = Catalog().load("lookup-member-savings-balance")
    surface, _ = await PlaywrightSurface.launch(headless=True)
    try:
        result = await ReplayExecutor().run(
            art,
            {"member_id": "12345"},
            surface=surface,
            require_confirm_irreversible=False,
            entry_url=target_url + "/login?skin=lakeshore",
        )
        assert result.status == "failed"
        assert result.failed_step_id == "s01"
    finally:
        await surface.close()


@pytest.mark.asyncio
async def test_live_replay_not_found(target_url):
    art = Catalog().load("lookup-member-savings-balance")
    art.entry.url = target_url + "/login"
    surface, _ = await PlaywrightSurface.launch(headless=True)
    try:
        result = await ReplayExecutor().run(
            art,
            {"member_id": "99999"},
            surface=surface,
            require_confirm_irreversible=False,
        )
        assert result.status == "business_outcome"
        assert result.business_outcome == "MEMBER_NOT_FOUND"
    finally:
        await surface.close()


@pytest.mark.asyncio
async def test_hitl_same_session_resume(target_url):
    """Human acts on the same Playwright page, then automation resumes."""
    surface, _ = await PlaywrightSurface.launch(headless=True)
    session = LiveSession(surface, "hitl-test")
    try:
        await surface.goto(target_url + "/login")
        await surface.click(LocatorCandidate(kind="role_name", role="button", name="Sign On", exact=False))
        await asyncio.sleep(0.3)
        # interstitial
        try:
            await surface.click(
                LocatorCandidate(kind="role_name", role="button", name="Acknowledge", exact=False, frame="main")
            )
        except LookupError:
            pass
        iv = session.escalate(reason="stuck on search", observed="need human to type member", step_id="s02")
        assert session.owner == "human"
        session.record_human("type", "typed 12345 in live session")
        await surface.type_text(
            LocatorCandidate(kind="role_name", role="textbox", name="Member number", exact=False, frame="main"),
            "12345",
        )
        await surface.click(LocatorCandidate(kind="role_name", role="button", name="Search", exact=False, frame="main"))
        session.resume()
        assert session.owner == "automation"
        assert iv.status == "resumed"
        obs = await surface.observe()
        assert "ALVAREZ" in obs.visible_text or "Open" in obs.visible_text
    finally:
        await surface.close()


@pytest.mark.asyncio
async def test_playwright_ai_aria_snapshot(target_url):
    surface, _ = await PlaywrightSurface.launch(headless=True)
    try:
        await surface.goto(target_url + "/login")
        obs = await surface.observe()
        assert obs.aria_yaml
        assert "Sign On" in obs.aria_yaml or "button" in obs.aria_yaml.lower()
        assert "# frame=" in obs.aria_yaml
    finally:
        await surface.close()
