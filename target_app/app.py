"""Fieldbook 6.2 — intentionally hostile back-office stand-in.

Copperline Credit Union is the reference tenant. Lakeshore Community CU
runs the same Harrow Systems product with a different brand kit.


No test IDs, table-based layout, frameset chrome, nested tables for forms.
Exceptional states: not-found, permission denied, validation, interstitial,
and a session-timeout path used by replay tests.
"""

from __future__ import annotations

import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

ROOT = os.path.dirname(__file__)
templates = Jinja2Templates(directory=os.path.join(ROOT, "templates"))

app = FastAPI(title="Fieldbook 6.2")
app.add_middleware(
    SessionMiddleware,
    secret_key=os.environ.get("TARGET_SESSION_SECRET", "heritage-demo-not-secret"),
    max_age=60 * 60,
)
app.mount("/static", StaticFiles(directory=os.path.join(ROOT, "static")), name="static")

MEMBERS: dict[str, dict[str, Any]] = {
    "12345": {
        "id": "12345",
        "name": "ALVAREZ, MARIA E",
        "status": "Active",
        "branch": "0412-Westlake",
        "savings_balance": "2,540.17",
        "checking_balance": "318.02",
        "permission": "ok",
    },
    "67890": {
        "id": "67890",
        "name": "CHEN, DAVID L",
        "status": "Active",
        "branch": "0098-Harbor",
        "savings_balance": "110.00",
        "checking_balance": "8,902.44",
        "permission": "ok",
    },
    "00000": {
        "id": "00000",
        "name": "RESTRICTED RECORD",
        "status": "Restricted",
        "branch": "0001-Ops",
        "savings_balance": "—",
        "checking_balance": "—",
        "permission": "denied",
    },
}

DEMO_USER = "operator"
DEMO_PASS = "fieldbook"

# Two institutions, one vendor product. Outcome copy stays vendor-stable.
# Control labels are the branded part a tenant overlay has to retarget.
SKINS: dict[str, dict[str, str]] = {
    "copperline": {
        "id": "copperline",
        "institution": "Copperline Credit Union",
        "vendor": "Fieldbook 6.2",
        "sign_on": "Sign On",
        "member_field": "Member number",
        "search": "Search",
        "ack": "Acknowledge",
        "savings_label": "Savings",
        "savings_name": "Savings balance",
        "checking_label": "Checking",
        "checking_name": "Checking balance",
    },
    "lakeshore": {
        "id": "lakeshore",
        "institution": "Lakeshore Community CU",
        "vendor": "Fieldbook 6.2",
        "sign_on": "Log On",
        "member_field": "Account number",
        "search": "Find",
        "ack": "Continue",
        "savings_label": "Share",
        "savings_name": "Share balance",
        "checking_label": "Draft",
        "checking_name": "Draft balance",
    },
}


def _authed(request: Request) -> bool:
    return bool(request.session.get("user"))


def _expired(request: Request) -> bool:
    iso = request.session.get("expires_at")
    if not iso:
        return False
    try:
        exp = datetime.fromisoformat(iso)
    except ValueError:
        return False
    return datetime.now(timezone.utc) > exp


def _labels(request: Request) -> dict[str, str]:
    skin = request.session.get("skin") or "copperline"
    return SKINS.get(skin, SKINS["copperline"])


def _page(request: Request, name: str, **ctx: Any) -> HTMLResponse:
    labels = _labels(request)
    return templates.TemplateResponse(
        request, name, {"request": request, "labels": labels, "skin": labels["id"], **ctx}
    )


@app.get("/", response_model=None)
def root(request: Request) -> HTMLResponse | RedirectResponse:
    if not _authed(request):
        return RedirectResponse("/login", status_code=302)
    return _page(request, "frameset.html")


@app.get("/login", response_class=HTMLResponse)
def login_form(
    request: Request, notice: str | None = None, skin: str | None = None
) -> HTMLResponse:
    if skin:
        request.session["skin"] = skin if skin in SKINS else "copperline"
    elif "skin" not in request.session:
        request.session["skin"] = "copperline"
    return _page(request, "login.html", notice=notice, error=None)


@app.post("/login", response_model=None)
def login(request: Request, username: str = Form(...), password: str = Form(...)):
    if username.strip() != DEMO_USER or password != DEMO_PASS:
        return _page(
            request,
            "login.html",
            error="Logon rejected. Check operator ID / password.",
            notice=None,
        )
    request.session["user"] = username
    request.session["seen_notice"] = False
    request.session["expires_at"] = (
        datetime.now(timezone.utc) + timedelta(hours=2)
    ).isoformat()
    return RedirectResponse("/", status_code=302)


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login?notice=signed_off", status_code=302)


@app.get("/nav", response_class=HTMLResponse)
def nav(request: Request) -> HTMLResponse:
    return _page(request, "nav.html", user=request.session.get("user"))


@app.get("/main", response_model=None)
def main(request: Request) -> HTMLResponse | RedirectResponse:
    if not _authed(request):
        return RedirectResponse("/login", status_code=302)
    if _expired(request):
        request.session.clear()
        return RedirectResponse("/login?notice=timeout", status_code=302)
    if not request.session.get("seen_notice"):
        return RedirectResponse("/notice", status_code=302)
    return RedirectResponse("/search", status_code=302)


@app.get("/notice", response_model=None)
def notice(request: Request) -> HTMLResponse | RedirectResponse:
    if not _authed(request):
        return RedirectResponse("/login", status_code=302)
    return _page(request, "notice.html")


@app.post("/notice/ack")
def ack_notice(request: Request):
    request.session["seen_notice"] = True
    return RedirectResponse("/search", status_code=302)


@app.get("/search", response_model=None)
def search(request: Request, q: str | None = None) -> HTMLResponse | RedirectResponse:
    if not _authed(request):
        return RedirectResponse("/login", status_code=302)
    if _expired(request):
        request.session.clear()
        return RedirectResponse("/login?notice=timeout", status_code=302)
    result = None
    outcome = None
    if q is not None:
        member = MEMBERS.get(q.strip())
        if member is None:
            outcome = "not_found"
        elif member["permission"] == "denied":
            outcome = "denied"
        else:
            result = member
    return _page(
        request,
        "search.html",
        q=q or "",
        result=result,
        outcome=outcome,
    )


@app.get("/member/{member_id}", response_model=None)
def member_detail(request: Request, member_id: str) -> HTMLResponse | RedirectResponse:
    if not _authed(request):
        return RedirectResponse("/login", status_code=302)
    member = MEMBERS.get(member_id)
    if not member:
        return _page(request, "search.html", q=member_id, result=None, outcome="not_found")
    if member["permission"] == "denied":
        return _page(request, "search.html", q=member_id, result=None, outcome="denied")
    return _page(request, "member.html", member=member, opened=None)


@app.get("/member/{member_id}/open", response_model=None)
def open_form(request: Request, member_id: str) -> HTMLResponse | RedirectResponse:
    if not _authed(request):
        return RedirectResponse("/login", status_code=302)
    member = MEMBERS.get(member_id)
    if not member or member["permission"] != "ok":
        return RedirectResponse("/search", status_code=302)
    return _page(request, "open_account.html", member=member, error=None)


@app.post("/member/{member_id}/open", response_model=None)
def open_account(
    request: Request,
    member_id: str,
    product: str = Form(...),
    nickname: str = Form(""),
):
    member = MEMBERS.get(member_id)
    if not member:
        return RedirectResponse("/search", status_code=302)
    if not product.strip():
        return _page(
            request,
            "open_account.html",
            member=member,
            error="Product type is required.",
        )
    if len(nickname.strip()) > 20:
        return _page(
            request,
            "open_account.html",
            member=member,
            error="Nickname exceeds 20 characters.",
        )
    acct = f"SV-{member_id}-{secrets.token_hex(2).upper()}"
    return _page(
        request,
        "confirm.html",
        member=member,
        product=product,
        nickname=nickname.strip() or "(none)",
        account_number=acct,
    )


@app.get("/__test__/expire")
def expire_session(request: Request):
    """Test hook: force the next navigation to look like a timeout."""
    request.session["expires_at"] = (
        datetime.now(timezone.utc) - timedelta(seconds=1)
    ).isoformat()
    return {"ok": True}


@app.get("/health")
def health():
    return {"ok": True, "app": "fieldbook-6.2"}
