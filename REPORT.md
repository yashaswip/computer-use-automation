# Design write-up

## 1. Architecture

Three runtimes, one contract.

1. **Fieldbook 6.2** is a local proxy for a bank servicing console (Harrow Systems). Copperline Credit Union is the reference tenant. It exists so discovery and replay can hit real runtime exceptions (not-found, permission denied, validation, interstitial, timeout) on a **hostile** surface: frameset chrome, table forms, no test IDs.
2. **Discovery** is an LLM observe → decide → act loop against a `SurfaceDriver`. Perception is Playwright’s **ARIA snapshot YAML (`mode=ai`)**, not a scraped DOM. Decisions are **strict structured outputs** from the OpenAI **Responses API** (`responses.parse` + Pydantic). A low-detail screenshot is attached as a vision fallback. Provider `store=False` so session content is not retained. Playwright **traces** (`trace.zip`) are written as evidence.
3. **Replay** loads a `CapabilityArtifact` and executes steps in order. It is the production path an AI agent would call. No model is consulted for “what next.”

Boundaries:

- `SurfaceDriver` — perceive / act. Swap Playwright for a desktop driver without changing artifacts.
- `CapabilityArtifact` — the agent-invocable contract (parameters, steps, locators, checkpoint, outcome detectors).
- `Guardrails` — allowlist + irreversible class, applied on every act in both modes.
- `LiveSession` — who owns the live surface (`automation` | `human` | `closed`). Escalation does not spawn a new browser.

I kept this a single process plus two small HTTP apps (target, operator). Queues and multi-tenant routing would be premature; the schema already has a `variant` / `overlays` seam for that.

Trade-off: accessibility-tree locators over screenshot-click. Playwright’s AI ARIA snapshot is what current computer-use stacks (Playwright MCP, Stagehand-style agents) actually feed the model. Coordinates remain a last-resort `boxes` option I did not turn on for replay — they are brittle and unreviewable. Role/name is shared with desktop UI Automation. Screenshots are evidence plus a discovery-time vision hint, not the production targeting channel.

## 2. Artifact schema

The artifact is **not** the model transcript. It is a typed JSON document (`schema_version`, `artifact_version`) an agent can catalog and call.

- **Contract:** `parameters` and `outputs` with types, sensitivity flags, examples.
- **Steps:** ordered `intent` + `action` + `target` + `value` binding (`literal` | `parameter` | `secret_ref`). Secrets are referenced, never stored.
- **Locators:** `primary` plus `fallbacks`. Preference order is `role_name` → `label`/`text` → `css`/`xpath`. CSS is last because Fieldbook-style markup will churn attributes long before the accessible name does. Names may contain `{{param}}`. Discovery sees one member id; the compiler rewrites `Open member 12345` into `Open member {{member_id}}` so the next invocation is not stuck on the recorded example.
- **Checkpoint:** success is asserted, not assumed.
- **Detectors:** `business_outcomes` vs `recoverables`. “No matching member record” is a **result** for the caller. A maintenance dialog is something replay may dismiss by itself.
- **Variant + overlays:** one base artifact per vendor flow. A patch is tagged with `variant_id` and can replace a step target, a recoverable’s button, the entry URL, or append outcome signals. Base replay ignores other tenants’ patches. Lakeshore CU is a second brand kit on Fieldbook 6.2 (harbor blue, different control names); `--variant lakeshore` is the specialization, not a re-record. Copperline keeps the copper/manila desk the recording was made on.

Discovery compiles a first draft from the trace (parameterizing member IDs). The checked-in `capabilities/*.json` files are the **reviewed** form of that contract — the thing I would actually expose to an agent. That split is deliberate: the model is a good explorer and a poor schema designer.

## 3. Determinism & error handling

Replay is deterministic because control flow is data: the same steps, the same locator cascade, `{{param}}` bound from the invocation inputs, explicit waits after navigation, no sampling. A missing parameter is a hard failure on that step, not an empty string typed into the form.

After every step (and before acting) replay:

1. Observes the surface.
2. Matches **business outcomes** (not-found, permission denied, session expired, validation). If matched, it **stops and returns that code** — it does not grind through the remaining steps.
3. Matches **recoverables** (maintenance interstitial) and executes the recorded dismiss action, bounded by `max_times`.
4. Executes the step with primary then fallback locators.
5. On act failure: re-observe (the failure may have *caused* a business outcome), else hard-fail with `failed_step_id`, expected intent, observed snapshot, and a screenshot.

UI drift is secondary here (enterprise UIs are slow-moving). The locator cascade and checkpoint are the hedge. A second-tenant overlay is the hedge for branded/versioned markup.

## 4. Heterogeneity & multi-tenant

**Surface seam.** An artifact step says *click the control whose role is button and name is Search in frame main*. The web driver maps that to Playwright `get_by_role`. A desktop driver would map the same candidate to UI Automation / AX. Frames become windows. The flow document does not mention DOM.

**Multi-tenant reuse.** Hundreds of institutions run ~20 vendor products. I store **one base artifact per (vendor_product, flow)** and a cheap overlay per tenant build. The demo is that design, not a sketch of it: Copperline and Lakeshore Community CU both run Fieldbook 6.2. Vendor outcome copy stays stable ("No matching member record", "Scheduled maintenance notice", screen title "Member Inquiry"). Branded controls change (Sign On/Log On, Member number/Account number, Search/Find, Savings/Share, Acknowledge/Continue), and so does the chrome (copper vs harbor). `apply_variant("lakeshore")` swaps the locators and the entry URL. Replaying the base artifact against Lakeshore fails at sign-on, which is the drift signal: the recording no longer matches this build, and the fix is an overlay or a bounded rediscovery of the failing step, not a new flow. I did not build a tenant router or a canary scheduler. Desktop UI Automation is the same locator vocabulary behind another `SurfaceDriver`; I did not write that driver.

## 5. Escalation & handoff

Stuck is: max steps, policy denial, unknown dialog, locator miss that is not a known outcome, or an **irreversible** step.

`LiveSession.escalate(...)` flips `owner` to `human` and writes an `InterventionRequest` to `.hitl/intervention.json` (capability, step, redacted goal, observed text, screenshot path). The operator page is a **second process**. It cannot see the replay process’s memory, so the file is the seam. Automation `assert_automation()` thereafter. The Chromium instance **does not restart**.

The operator surface is intentionally bare: poll the file, show why we stopped, show the screenshot, tell the human to use the headed window (the live session), then **Resume** or **Abort**. That writes `.hitl/decision`, which the replay process polls. Human actions append to `.hitl/human.jsonl` and are copied onto the run result. Resume sets `owner=automation`; replay continues from the next observe.

What I mocked: a full co-browsing toolbar, cursor sharing, and multi-operator routing. What is real: exclusive control, same `SurfaceDriver`, pause/resume, intervention payload, and a test that types into the paused page and resumes.

## 6. Safety

- Configurable allowlist: hosts, URL prefixes, action types, forbidden paths (`/admin/wire`).
- Irreversible intents (`submit_new_account`) pause for a human unless the caller opts into `--approve-irreversible` (an attended production agent would pass an approval token, not a CLI flag).
- Passwords are `secret_ref`; logs/events run through redaction (SSN, PAN-ish, account-like tokens, password assignments). Artifacts store parameters by name, not demo PII beyond the public member numbers in the stand-in.
- The agent is prompted not to leave the host.

Limits: this is not a full DLP or keystroke-isolation layer. A malicious model could still type a secret into a field; we avoid persisting it. Allowlists are origin-level, not field-level.

## 7. Cuts

Done as a thin vertical slice of every Section 3 requirement, plus two stretches: **catalog invoke**, and a **second-tenant overlay** (Lakeshore CU) on the same capability.

Left out on purpose:

- Screenshot-coordinate CUA and a desktop driver (seam only).
- Real co-browsing operator console. The handoff file and the headed window are the real mechanism; the page is the mock.
- An approval state machine and N-run stability scores. Discovery already refuses to overwrite a reviewed catalog file; it writes `*.draft.json` instead.
- Bounded LLM one-step recovery on replay failure.
- A tenant router, canary scheduler, or per-institution deploy. The overlay schema is the extension point, and one variant is implemented so the story is executable.

Next: canary replays that flip `artifact_version` and overlay locators when a vendor patch shifts a name; then a proper capability registry in front of the bank agent’s tool loop.
