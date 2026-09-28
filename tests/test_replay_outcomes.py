import pytest

from cua.catalog.store import Catalog
from cua.replay.executor import ReplayExecutor
from tests.fakes import ScriptedSurface, page


@pytest.mark.asyncio
async def test_replay_reports_member_not_found_as_business_outcome(tmp_path, monkeypatch):
    monkeypatch.chdir(".")
    art = Catalog().load("lookup-member-savings-balance")
    surface = ScriptedSurface(
        [
            page("Fieldbook logon", "http://127.0.0.1:8765/login"),
            page("No matching member record.", "http://127.0.0.1:8765/search?q=99999"),
        ]
    )
    result = await ReplayExecutor().run(
        art,
        {"member_id": "99999"},
        surface=surface,
        require_confirm_irreversible=False,
        hitl_timeout_s=1,
    )
    assert result.status == "business_outcome"
    assert result.business_outcome == "MEMBER_NOT_FOUND"


@pytest.mark.asyncio
async def test_replay_reports_permission_denied(monkeypatch):
    art = Catalog().load("lookup-member-savings-balance")
    surface = ScriptedSurface(
        [
            page("Fieldbook logon", "http://127.0.0.1:8765/login"),
            page("Permission denied for this record.", "http://127.0.0.1:8765/search?q=00000"),
        ]
    )
    result = await ReplayExecutor().run(
        art, {"member_id": "00000"}, surface=surface, require_confirm_irreversible=False, hitl_timeout_s=1
    )
    assert result.status == "business_outcome"
    assert result.business_outcome == "PERMISSION_DENIED"


@pytest.mark.asyncio
async def test_missing_parameter_is_a_hard_failure():
    art = Catalog().load("lookup-member-savings-balance")
    surface = ScriptedSurface(
        [
            page("Fieldbook logon", "http://127.0.0.1:8765/login"),
            page("Member search form", "http://127.0.0.1:8765/search"),
        ]
    )
    result = await ReplayExecutor().run(
        art, {}, surface=surface, require_confirm_irreversible=False, hitl_timeout_s=1
    )
    assert result.status == "failed"
    assert result.failed_step_id == "s02"
    assert "member_id" in (result.error or "")
