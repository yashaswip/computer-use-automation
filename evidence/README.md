# Evidence

Checked-in replay runs (no model):

- `replay-success/` — member 12345, savings balance 2,540.17
- `replay-not-found/` — `MEMBER_NOT_FOUND` for member 99999, with a screenshot
- `replay-denied/` — `PERMISSION_DENIED` for member 00000, with a screenshot
- `replay-lakeshore/` — the same capability on the Lakeshore brand kit (`--variant lakeshore`)

`runs/` is local scratch from tests and is gitignored.

Discovery is not checked in until you run it. `cua discover` writes `runs/disc-*/` (events, screenshots, `trace.zip`, `artifact.json`). That transcript has to be a real model call. Do not hand-write one. Copy the run you want reviewers to see into `evidence/discovery/` before you push.
