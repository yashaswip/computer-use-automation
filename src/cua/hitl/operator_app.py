"""Minimal operator surface.

Not a co-browsing console. The headed Chromium window is the live session.
This page is a separate process: it reads the intervention off disk, shows
why automation stopped, and writes resume/abort back to that same file.
"""

from __future__ import annotations

import html

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse

from cua.hitl.control import LiveSession
from cua.hitl.handoff import read_intervention, record_human, write_decision

app = FastAPI(title="CUA Operator")
SESSION: LiveSession | None = None


def bind(session: LiveSession) -> None:
    global SESSION
    SESSION = session


def read_decision() -> str | None:
    from cua.hitl.handoff import consume_decision

    return consume_decision()


@app.get("/", response_class=HTMLResponse)
def home() -> str:
    iv = read_intervention()
    if not iv or iv.status != "open":
        return """<!doctype html><meta charset="utf-8"><meta http-equiv="refresh" content="2">
        <title>Operator</title>
        <body style="font-family:sans-serif;max-width:720px;margin:40px">
        <h1>Operator console</h1>
        <p>No open intervention. Automation is in control.</p>
        </body>"""
    shot = ""
    if iv.screenshot_path:
        shot = '<p><img src="/screenshot" style="max-width:100%;border:1px solid #ccc"></p>'
    reason = html.escape(iv.reason)
    observed = html.escape(iv.observed[:800])
    step = html.escape(iv.step_id or "n/a")
    return f"""<!doctype html><meta charset="utf-8"><meta http-equiv="refresh" content="2">
    <title>Intervention {html.escape(iv.id)}</title>
    <body style="font-family:sans-serif;max-width:800px;margin:32px">
    <h1>Human takeover required</h1>
    <p><b>Run:</b> {html.escape(iv.run_id)}</p>
    <p><b>Reason:</b> {reason}</p>
    <p><b>Step:</b> {step}</p>
    <p><b>Observed:</b> {observed}</p>
    {shot}
    <p>Use the headed browser window — that is the same live session. Then:</p>
    <form method="post" action="/resume" style="display:inline"><button>Resume automation</button></form>
    <form method="post" action="/abort" style="display:inline;margin-left:8px"><button>Abort run</button></form>
    </body>"""


@app.get("/status")
def status():
    iv = read_intervention()
    if iv:
        return iv.model_dump()
    if SESSION:
        return SESSION.state.model_dump()
    return {"owner": "none"}


@app.get("/screenshot")
def screenshot():
    iv = read_intervention()
    if not iv or not iv.screenshot_path:
        return JSONResponse({"error": "no screenshot"}, status_code=404)
    return FileResponse(iv.screenshot_path)


@app.post("/resume")
def resume(request: Request):
    record_human("resume", "operator resumed automation")
    write_decision("resume")
    if SESSION and SESSION.owner == "human":
        SESSION.resume()
    if "text/html" in (request.headers.get("accept") or ""):
        return RedirectResponse("/", status_code=302)
    return {"ok": True, "owner": "automation"}


@app.post("/abort")
def abort(request: Request):
    record_human("abort", "operator aborted the run")
    write_decision("abort")
    if SESSION and SESSION.owner == "human":
        SESSION.abort()
    if "text/html" in (request.headers.get("accept") or ""):
        return RedirectResponse("/", status_code=302)
    return {"ok": True, "owner": "closed"}
