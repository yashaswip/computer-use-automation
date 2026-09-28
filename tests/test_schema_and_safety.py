from cua.config import load_policy
from cua.guardrails.policy import Guardrails, PolicyDenied
from cua.guardrails.redact import redact_params, redact_text
from cua.models.artifact import CapabilityArtifact


def test_artifact_seed_validates():
    art = CapabilityArtifact.model_validate_json(
        open("capabilities/lookup-member-savings-balance.json").read()
    )
    assert art.slug == "lookup-member-savings-balance"
    assert any(p.name == "member_id" for p in art.parameters)
    assert art.business_outcomes
    open_step = next(s for s in art.steps if s.id == "s04")
    assert open_step.target is not None
    assert open_step.target.primary.name == "Open member {{member_id}}"


def test_redact_ssn_and_account():
    text = "ssn 123-45-6789 account SV-12345-ABCD password: hunter2"
    out = redact_text(text)
    assert "123-45-6789" not in out
    assert "hunter2" not in out
    assert "[REDACTED_ACCOUNT]" in out


def test_redact_params():
    out = redact_params({"member_id": "12345", "password": "x"}, ["password"])
    assert out["member_id"] == "12345"
    assert out["password"] == "[REDACTED]"


def test_policy_blocks_foreign_host():
    g = Guardrails(load_policy("policies/default.yaml"))
    g.check_url("http://127.0.0.1:8765/search")
    try:
        g.check_url("https://evil.example/login")
        assert False, "should deny"
    except PolicyDenied:
        pass
    try:
        g.check_action("shell")  # type: ignore[arg-type]
        assert False
    except PolicyDenied:
        pass
