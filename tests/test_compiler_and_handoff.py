from cua.agent.compiler import RecordedAct, compile_artifact
from cua.hitl.control import LiveSession
from cua.hitl.handoff import consume_decision, read_intervention, write_decision
from cua.models.artifact import bind_locator
from cua.catalog.store import Catalog


def test_compiler_parameterizes_member_id_and_checkpoint():
    acts = [
        RecordedAct(
            {"action": "type", "role": "textbox", "name": "Member number", "thought": "enter id"},
            "textbox Member number",
            "12345",
        ),
        RecordedAct(
            {
                "action": "click",
                "role": "link",
                "name": "Open member 12345",
                "frame": "main",
                "thought": "open the record",
            },
            "link",
            None,
        ),
    ]
    art = compile_artifact(
        run_id="disc-test",
        goal="look up member 12345 ssn 123-45-6789 and read the savings balance",
        model="test",
        entry_url="http://127.0.0.1:8765/login",
        acts=acts,
        outputs={"savings_balance": "2,540.17"},
        final_text="Member Inquiry — 12345 ALVAREZ",
    )
    click = next(step for step in art.steps if step.action == "click")
    assert click.target is not None
    assert click.target.primary.name == "Open member {{member_id}}"
    assert art.checkpoint.all_of[0].text == "Member Inquiry"
    assert art.provenance is not None
    assert "123-45-6789" not in art.provenance.goal_redacted
    assert "[REDACTED_SSN]" in art.provenance.goal_redacted


def test_lakeshore_overlay_is_opt_in():
    art = Catalog().load("lookup-member-savings-balance")
    base = art.apply_variant(None)
    assert base.steps[0].target is not None
    assert base.steps[0].target.primary.name == "Sign On"
    lake = art.apply_variant("lakeshore")
    assert lake.steps[0].target is not None
    assert lake.steps[0].target.primary.name == "Log On"
    assert lake.entry.url is not None and lake.entry.url.endswith("skin=lakeshore")
    assert lake.variant.tenant_id == "lakeshore-cu"
    assert lake.recoverables[0].target is not None
    assert lake.recoverables[0].target.primary.name == "Continue"
    bound = bind_locator(base.steps[3].target.primary, {"member_id": "67890"})  # type: ignore[union-attr]
    assert bound.name == "Open member 67890"


def test_handoff_file_is_visible_to_another_process(tmp_path, monkeypatch):
    monkeypatch.setattr("cua.hitl.handoff.ROOT", tmp_path / "hitl")
    session = LiveSession(object(), "run-1")  # type: ignore[arg-type]
    session.escalate(reason="stuck on dialog", observed="maintenance notice", step_id="s02")
    loaded = read_intervention()
    assert loaded is not None
    assert loaded.status == "open"
    assert loaded.reason == "stuck on dialog"
    write_decision("resume")
    assert consume_decision() == "resume"
    after = read_intervention()
    assert after is not None
    assert after.status == "resumed"
