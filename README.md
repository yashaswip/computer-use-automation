# Automation: discover once, replay many

A small but complete **record-once / replay-many** layer for AI agents that must operate legacy UIs with no API.

The model discovers how to finish a goal inside a live surface. The successful run is compiled into a **versioned capability artifact**. Production invocations **replay that artifact deterministically** — no model in the decision loop. Runtime exceptions are classified as business outcomes, recoverables, or hard failures. When the system cannot safely continue, it **pauses the same live session** and hands control to a human.

This is the take-home for interface.ai's Applied AI Engineer assignment.

**Stack:** Playwright accessibility snapshots (`locator.aria_snapshot(mode="ai")`) for perception, OpenAI Responses API structured outputs for discovery, and a plain step executor for replay. Production invocation does not call a model. Coordinates and an agent framework would make the recording harder to review and impossible to replay deterministically.

## What you are looking at

| Path | Role |
| --- | --- |
| `target_app/` | **Fieldbook 6.2** — local stand-in for a bank back-office console (frameset, table layout, no test IDs). Copperline is the reference tenant; Lakeshore is the other brand kit. |
| `src/cua/models/artifact.py` | Typed capability schema |
| `src/cua/agent/` | LLM observe → decide → act loop + artifact compiler |
| `src/cua/replay/` | Deterministic executor |
| `src/cua/hitl/` | Control-transfer model + minimal operator page |
| `src/cua/guardrails/` | Allowlist, irreversible gating, redaction |
| `capabilities/` | Reviewable artifacts an agent can invoke |
| `evidence/` | Discovery + replay logs from real runs |
| `REPORT.md` | Design write-up (the seven required headings) |

## Setup

Python 3.11+ recommended.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
playwright install chromium
cp .env.example .env   # add OPENAI_API_KEY only if you will run discover
```

Replay and tests do **not** need a model key.

## Demo path

Terminal A — the target console:

```bash
python -m cua serve-target
# http://127.0.0.1:8765   demo logon: operator / fieldbook
```

Terminal B — deterministic replay (no LLM):

```bash
python -m cua replay \
  --artifact lookup-member-savings-balance \
  --param member_id=12345
```

Expected: `status=success`, `outputs.savings_balance=2,540.17`.

Business outcome (not a crash):

```bash
python -m cua replay \
  --artifact lookup-member-savings-balance \
  --param member_id=99999
```

Expected: `status=business_outcome`, `business_outcome=MEMBER_NOT_FOUND`.

Permission denial:

```bash
python -m cua replay --artifact lookup-member-savings-balance --param member_id=00000
```

Expected: `status=business_outcome`, `business_outcome=PERMISSION_DENIED`.

Same capability on a second institution (Lakeshore CU runs the same vendor product with different labels):

```bash
python -m cua replay \
  --artifact lookup-member-savings-balance \
  --variant lakeshore \
  --param member_id=12345
```

Expected: `status=success`, `outputs.savings_balance=2,540.17`. Without `--variant`, that skin fails at sign-on: the button is "Log On", not "Sign On".

Another member (the open-link name is `Open member {{member_id}}`, not a hardcoded 12345):

```bash
python -m cua replay \
  --artifact lookup-member-savings-balance \
  --param member_id=67890
```

Expected: `status=success`, `outputs.savings_balance=110.00`.

Agent-facing catalog invoke (stretch):

```bash
python -m cua catalog list
python -m cua catalog invoke lookup-member-savings-balance --param member_id=12345
```

Irreversible path (opens a sub-account). By default replay **pauses for a human** on Submit. Unattended:

```bash
python -m cua replay \
  --artifact open-member-sub-account \
  --param member_id=12345 \
  --param product=SAVINGS \
  --param nickname=Rainy \
  --approve-irreversible
```

Optional operator console (handoff UI):

```bash
python -m cua serve-operator
# http://127.0.0.1:8766
```

When automation escalates, use the **headed Chromium window** (the live session) and click **Resume automation** on the operator page.

## Discovery (LLM in the loop — required once)

```bash
# .env must contain OPENAI_API_KEY
python -m cua discover \
  --goal "look up member 12345 and read their current savings balance" \
  --url http://127.0.0.1:8765/login
```

This writes `evidence/runs/disc-*/` (events, screenshots, trace, compiled artifact) and, if a reviewed file already exists, `capabilities/<slug>.draft.json` so discovery does not overwrite the catalog entry. Review the draft, then promote the parts you want into `capabilities/`.

A real discovery run is required before you submit. Replay evidence can be regenerated with no key; the discovery transcript cannot be invented.

## Tests

```bash
pytest -q
```

Includes schema/guardrail unit tests, scripted-surface outcome taxonomy, a live Playwright happy path + not-found path, and a same-session HITL resume.

## Design in one paragraph

Perception/actuation is a `SurfaceDriver` (Playwright + accessibility roles today; desktop UI Automation would be another driver). The artifact stores **role/name locators with `{{param}}` templates and fallbacks**, typed parameters/outputs, detectors for expected business outcomes, and recoverable interstitials. Replay never calls the LLM. Guardrails allowlist hosts and actions, redact secrets from logs, and treat irreversible submits as HITL-gated. A second skin of the same vendor product (Lakeshore CU) replays through `overlays` selected by `--variant`, not a second recording. The operator page and the replay process share the intervention through `.hitl/`, because they are not the same process.

Read `REPORT.md` for trade-offs and cuts.
