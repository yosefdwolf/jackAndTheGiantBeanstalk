"""Google sign-in. Everyone signs in (as well as knowing the magic word); admins are ADMIN_EMAILS.

The OAuth code flow is done by hand with httpx: send the browser to Google, swap the code for a
token, read the verified email. The session is a signed cookie holding the user's id, so no
session table is needed. COOKIE_DOMAIN=jack.graydates.com shares it with admin.jack.graydates.com.

DEV_LOGIN=1 (local only, and only while Google isn't configured) skips Google, so the site can be
tried on localhost without credentials.
"""
import base64
import hashlib
import hmac
import json
import os
import secrets
import time
import uuid
from datetime import datetime, timezone
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select

from .book.log import current_ref, record, set_user
from .db.models import UnlimitedEmail, User
from .db.session import session

router = APIRouter()

COOKIE = "jack_session"
STATE_COOKIE = "jack_oauth"
SESSION_DAYS = 30
GOOGLE_AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO = "https://openidconnect.googleapis.com/v1/userinfo"


def admin_emails() -> set[str]:
    return {e.strip().lower() for e in os.getenv("ADMIN_EMAILS", "").split(",") if e.strip()}


def is_admin(user: User | None) -> bool:
    return user is not None and user.email.lower() in admin_emails()


def google_configured() -> bool:
    return bool(os.getenv("GOOGLE_CLIENT_ID") and os.getenv("GOOGLE_CLIENT_SECRET"))


def _secret() -> bytes:
    secret = os.getenv("SESSION_SECRET", "")
    if not secret:
        if dev_login_allowed():
            return b"local-dev-only"
        raise HTTPException(503, {"message": "The server has no SESSION_SECRET set, so sign-in is off.",
                                  "ref": current_ref(), "reason": "no_session_secret"})
    return secret.encode()


def dev_login_allowed() -> bool:
    return os.getenv("DEV_LOGIN", "") == "1" and not google_configured()


# --- signed values --------------------------------------------------------------------------------

def sign(data: dict) -> str:
    body = base64.urlsafe_b64encode(json.dumps(data, separators=(",", ":")).encode()).decode().rstrip("=")
    mac = hmac.new(_secret(), body.encode(), hashlib.sha256).hexdigest()[:32]
    return f"{body}.{mac}"


def unsign(value: str | None) -> dict | None:
    if not value or "." not in value:
        return None
    body, mac = value.rsplit(".", 1)
    try:
        expected = hmac.new(_secret(), body.encode(), hashlib.sha256).hexdigest()[:32]
    except HTTPException:
        return None
    if not hmac.compare_digest(mac, expected):
        return None
    try:
        data = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    except ValueError:
        return None
    return data if data.get("exp", 0) > time.time() else None


def session_cookie(user_id: uuid.UUID) -> str:
    return sign({"uid": str(user_id), "exp": int(time.time()) + SESSION_DAYS * 86400})


def _cookie_args(request: Request) -> dict:
    domain = os.getenv("COOKIE_DOMAIN") or None
    if domain and not request.url.hostname.endswith(domain):
        domain = None  # e.g. localhost while COOKIE_DOMAIN is set for the live site
    return {"httponly": True, "samesite": "lax", "secure": _scheme(request) == "https", "domain": domain}


def _scheme(request: Request) -> str:
    return request.headers.get("x-forwarded-proto", request.url.scheme).split(",")[0].strip()


def _origin(request: Request) -> str:
    return f"{_scheme(request)}://{request.headers.get('host', request.url.netloc)}"


def _safe_next(next_url: str | None) -> str:
    """Only same-site paths, so the sign-in link can't be used to bounce people elsewhere."""
    if not next_url or not next_url.startswith("/") or next_url.startswith("//") or "\\" in next_url:
        return "/"
    return next_url


# --- who is signed in -----------------------------------------------------------------------------

async def current_user(request: Request) -> User | None:
    data = unsign(request.cookies.get(COOKIE))
    if not data:
        return None
    try:
        uid = uuid.UUID(data["uid"])
    except (KeyError, ValueError):
        return None
    async with session() as s:
        user = await s.get(User, uid)
    if user:
        set_user(user.id)
    return user


async def has_unlimited(user: User) -> bool:
    if is_admin(user):
        return True
    async with session() as s:
        return await s.get(UnlimitedEmail, user.email.lower()) is not None


async def upsert_user(sub: str, email: str, name: str | None = None, picture: str | None = None) -> User:
    email = email.lower()
    async with session() as s:
        user = (await s.execute(select(User).where(User.google_sub == sub))).scalar_one_or_none()
        if user is None:  # same email, new sign-in route (e.g. dev sign-in after Google): same person
            user = (await s.execute(select(User).where(User.email == email))).scalar_one_or_none()
            if user is not None and not sub.startswith("dev:"):
                user.google_sub = sub
        if user is None:
            user = User(google_sub=sub, email=email)
            s.add(user)
        user.email, user.name, user.picture_url = email, name, picture
        user.last_login_at = datetime.now(timezone.utc)
        await s.commit()
        return user


# --- routes ---------------------------------------------------------------------------------------

@router.get("/auth/login")
async def login(request: Request, next_url: str = Query("/", alias="next"), email: str | None = None):
    next_url = _safe_next(next_url)
    if dev_login_allowed():
        if request.client is None or request.client.host not in {"127.0.0.1", "::1", "testclient"}:
            raise HTTPException(403, "Dev sign-in only works on this computer.")
        email = (email or next(iter(sorted(admin_emails())), "dev@example.com")).lower()
        user = await upsert_user(f"dev:{email}", email, name=email.split("@")[0])
        set_user(user.id)
        await record("INFO", "sign-in", "dev", email=email)
        response = RedirectResponse(next_url, status_code=303)
        response.set_cookie(COOKIE, session_cookie(user.id), max_age=SESSION_DAYS * 86400, **_cookie_args(request))
        return response
    if not google_configured():
        raise HTTPException(503, {"message": "Google sign-in isn't set up on this server yet.", "ref": current_ref(),
                                  "reason": "no_google"})
    state = secrets.token_urlsafe(24)
    query = urlencode({"client_id": os.environ["GOOGLE_CLIENT_ID"], "redirect_uri": f"{_origin(request)}/auth/callback",
                       "response_type": "code", "scope": "openid email profile", "state": state,
                       "prompt": "select_account"})
    response = RedirectResponse(f"{GOOGLE_AUTH}?{query}", status_code=303)
    response.set_cookie(STATE_COOKIE, sign({"state": state, "next": next_url, "exp": int(time.time()) + 600}),
                        max_age=600, **{**_cookie_args(request), "domain": None})
    return response


async def _refuse_sign_in(request: Request, reason: str, detail: str):
    from .main import save_request_error  # avoid an import cycle at load time
    ref = current_ref()
    await save_request_error(ref, "/auth/callback", 400, reason, detail, browser=request.headers.get("user-agent"))
    await record("WARNING", "sign-in", "refused", reason=reason)
    raise HTTPException(400, {"message": f"Sign-in didn't work ({reason}). Please try again.", "ref": ref,
                              "reason": reason})


@router.get("/auth/callback")
async def callback(request: Request, code: str | None = None, state: str | None = None, error: str | None = None):
    saved = unsign(request.cookies.get(STATE_COOKIE))
    if error:
        await _refuse_sign_in(request, "google_" + error[:40], error)
    if not saved or not state or not hmac.compare_digest(saved.get("state", ""), state) or not code:
        await _refuse_sign_in(request, "bad_state", "state missing or mismatched")
    async with httpx.AsyncClient(timeout=15) as http:
        token = await http.post(GOOGLE_TOKEN, data={
            "code": code, "client_id": os.environ["GOOGLE_CLIENT_ID"], "client_secret": os.environ["GOOGLE_CLIENT_SECRET"],
            "redirect_uri": f"{_origin(request)}/auth/callback", "grant_type": "authorization_code"})
        if token.status_code != 200:
            await _refuse_sign_in(request, "token_exchange", token.text[:500])
        info = await http.get(GOOGLE_USERINFO, headers={"Authorization": f"Bearer {token.json()['access_token']}"})
    if info.status_code != 200:
        await _refuse_sign_in(request, "userinfo", info.text[:500])
    profile = info.json()
    if not profile.get("email") or not profile.get("email_verified"):
        await _refuse_sign_in(request, "email_not_verified", "Google didn't confirm an email address")
    user = await upsert_user(profile["sub"], profile["email"], profile.get("name"), profile.get("picture"))
    set_user(user.id)
    await record("INFO", "sign-in", "done", user=str(user.id), admin=is_admin(user))
    response = RedirectResponse(saved.get("next", "/"), status_code=303)
    response.set_cookie(COOKIE, session_cookie(user.id), max_age=SESSION_DAYS * 86400, **_cookie_args(request))
    response.delete_cookie(STATE_COOKIE)
    return response


@router.get("/auth/logout")
async def logout(request: Request, next_url: str = Query("/", alias="next")):
    response = RedirectResponse(_safe_next(next_url), status_code=303)
    response.delete_cookie(COOKIE, domain=_cookie_args(request)["domain"])
    return response
