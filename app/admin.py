"""The admin site (admin.jack.graydates.com, or /admin locally): every book, its log trail, errors,
the model switch, the unlimited list and refund requests. Only ADMIN_EMAILS can open it.

On the admin host, paths are mapped under /admin (see AdminHost), so the same routes serve both.
"""
import hashlib
import io
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.orm import selectinload

from . import auth, wallet
from .book import bible
from .book.providers import CHOICES, is_mock
from .book.story import Casting, all_stories
from .db.models import (Activity, AdminSettings, Book, BookEvent, BookImage, CharacterPicture, RequestError, Review,
                        StoryCharacter, StoryRow,
                        Transaction, UnlimitedEmail, Upload, User)
from .db.session import session

STATIC = Path(__file__).resolve().parent.parent / "static"
# The admin page's script and stylesheet carry a content hash, so a deploy never leaves a browser running the
# old admin.js (new tabs showed up empty until a hard refresh).
ADMIN_VERSION = hashlib.sha1(b"".join((STATIC / "admin" / f).read_bytes() for f in ("admin.js", "admin.css"))
                             ).hexdigest()[:10]
SLOW_SECONDS = 60  # an image slower than this is flagged
QUESTIONS = [("looks_like_me", "Does this look like me?"),
             ("story_rings_true", "Does the story make sense from page to page?"),
             ("looks_professional", "Does it look professional?")]
router = APIRouter(prefix="/admin")


class AdminHost:
    """On admin.* hosts, serve /x from /admin/x (sign-in, static files and the public API stay put)."""
    KEEP = ("/auth/", "/static/", "/api/", "/admin")

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            host = dict(scope["headers"]).get(b"host", b"").decode()
            if host.startswith("admin.") and not scope["path"].startswith(self.KEEP):
                scope = {**scope, "path": "/admin" + (scope["path"] if scope["path"] != "/" else "")}
        await self.app(scope, receive, send)


async def require_admin(request: Request):
    user = await auth.current_user(request)
    if user is None:
        raise HTTPException(401, {"message": "Sign in first.", "reason": "not_signed_in"})
    if not auth.is_admin(user):
        raise HTTPException(403, {"message": f"{user.email} isn't an admin.", "reason": "not_admin"})
    return user


def _admin_host(request: Request) -> bool:
    return request.headers.get("host", "").startswith("admin.")


def _iso(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _seconds(a, b):
    if a is None or b is None:
        return None
    return round((b - a).total_seconds(), 1)


# --- which model draws a book ---------------------------------------------------------------------

async def provider_for(user: User | None) -> tuple[str, str | None, str | None]:
    """Everyone gets the default (OpenAI Flare). An admin's own books use their switch. MOCK=1 is
    a safety switch that forces placeholders for everyone."""
    if is_mock():
        return "mock", "mock", None
    if auth.is_admin(user):
        async with session() as s:
            settings = await s.get(AdminSettings, user.id)
        if settings:
            return settings.provider, settings.model, settings.quality
    return "openai", None, None


# --- page -----------------------------------------------------------------------------------------

@router.get("")
async def page(request: Request):
    user = await auth.current_user(request)
    home = "/" if _admin_host(request) else "/admin"
    if user is None:
        return RedirectResponse(f"/auth/login?next={home}", status_code=303)
    if not auth.is_admin(user):
        return HTMLResponse(f"<p style='font:18px Georgia,serif;padding:24px'>{user.email} isn't on the admin list. "
                            f"<a href='/auth/logout?next={home}'>Sign in as someone else</a></p>", status_code=403)
    # admin.jack.graydates.com links back to jack.graydates.com; locally /admin links back to /
    host = request.headers.get("host", "")
    site = f"{request.headers.get('x-forwarded-proto', request.url.scheme)}://{host[len('admin.'):]}/" if _admin_host(request) else "/"
    html = (STATIC / "admin" / "index.html").read_text().replace("{{EMAIL}}", user.email).replace("{{SITE}}", site)
    for asset in ("admin.js", "admin.css"):
        html = html.replace(f'/static/admin/{asset}"', f'/static/admin/{asset}?v={ADMIN_VERSION}"')
    return HTMLResponse(html, headers={"Cache-Control": "no-cache"})


# --- books ----------------------------------------------------------------------------------------

def _book_row(b: Book, email: str | None) -> dict:
    images = b.images
    durations = [_seconds(i.started_at, i.finished_at) for i in images if i.status == "done"]
    return {
        "id": b.id, "status": b.status, "reason": b.refused_reason or b.error_code, "message": b.error_message,
        "email": email, "child_name": b.child_name, "gender": b.gender, "provider": b.provider, "model": b.model,
        "quality": b.quality, "cost": float(b.total_cost or 0), "created_at": _iso(b.created_at),
        "seconds": _seconds(b.started_at or b.created_at, b.finished_at),
        "images_done": sum(i.status == "done" for i in images), "images_failed": sum(i.status == "failed" for i in images),
        "images_total": len(images), "slowest": max((d for d in durations if d is not None), default=None),
        "prompt_version": b.prompt_version,
    }


@router.get("/api/books")
async def books(status: str = "", reason: str = "", provider: str = "", q: str = "", since: str = "", until: str = "",
                slow: bool = False, failed: bool = False, limit: int = 100, offset: int = 0, _=Depends(require_admin)):
    query = (select(Book, User.email).outerjoin(User, User.id == Book.user_id)
             .options(selectinload(Book.images)).order_by(Book.created_at.desc()))
    if status:
        query = query.where(Book.status.in_(status.split(",")))
    if failed:
        query = query.where(Book.status.in_(("failed", "interrupted")))
    if reason:
        query = query.where(or_(Book.refused_reason == reason, Book.error_code == reason))
    if provider:
        query = query.where(Book.provider == provider)
    if since:
        query = query.where(Book.created_at >= datetime.fromisoformat(since).replace(tzinfo=timezone.utc))
    if until:
        query = query.where(Book.created_at < datetime.fromisoformat(until).replace(tzinfo=timezone.utc) + timedelta(days=1))
    if q:
        like = f"%{q.strip().lower()}%"
        query = query.where(or_(func.lower(Book.id).like(like), func.lower(User.email).like(like),
                                func.lower(Book.child_name).like(like)))
    async with session() as s:
        rows = (await s.execute(query)).all()
    items = [_book_row(b, email) for b, email in rows]
    if slow:
        items = [i for i in items if (i["slowest"] or 0) > SLOW_SECONDS]
    async with session() as s:
        reasons = (await s.execute(select(Book.refused_reason).distinct().where(Book.refused_reason.is_not(None)))).scalars().all()
        codes = (await s.execute(select(Book.error_code).distinct().where(Book.error_code.is_not(None)))).scalars().all()
        providers = (await s.execute(select(Book.provider).distinct())).scalars().all()
    return {"total": len(items), "items": items[offset:offset + min(limit, 500)],
            "summary": {"cost": round(sum(i["cost"] for i in items), 4),
                        "by_status": {k: sum(i["status"] == k for i in items) for k in sorted({i["status"] for i in items})}},
            "filters": {"reasons": sorted(set(reasons) | set(codes)), "providers": sorted(providers)}}


@router.get("/api/days")
async def days(n: int = 14, _=Depends(require_admin)):
    """Daily totals (UTC), newest first."""
    start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=n - 1)
    async with session() as s:
        rows = (await s.execute(select(Book.created_at, Book.status, Book.total_cost, Book.user_id)
                                .where(Book.created_at >= start))).all()
    out = {}
    for created, status, cost, user_id in rows:
        day = out.setdefault(created.date().isoformat(), {"books": 0, "done": 0, "failed": 0, "refused": 0,
                                                          "cost": 0.0, "people": set()})
        day["books"] += 1
        day["cost"] += float(cost or 0)
        if status in ("done", "failed", "refused"):
            day[status] += 1
        if user_id:
            day["people"].add(user_id)
    return [{"day": d, **{k: v for k, v in t.items() if k != "people"}, "people": len(t["people"]),
             "cost": round(t["cost"], 4)} for d, t in sorted(out.items(), reverse=True)]


@router.get("/api/books/{ref}")
async def book(ref: str, _=Depends(require_admin)):
    async with session() as s:
        b = (await s.execute(select(Book).where(Book.id == ref).options(selectinload(Book.images))
                             )).scalar_one_or_none()
        if b is None:
            raise HTTPException(404, {"message": "No book with that reference.", "ref": ref})
        user = await s.get(User, b.user_id) if b.user_id else None
        upload = (await s.execute(select(Upload.mime, Upload.width, Upload.height, Upload.face_description)
                                  .where(Upload.book_id == ref))).first()
        events = (await s.execute(select(BookEvent).where(BookEvent.book_id == ref).order_by(BookEvent.at, BookEvent.id)
                                  )).scalars().all()
        reviews = (await s.execute(select(Review).where(Review.book_id == ref))).scalars().all()
    # A step that started and never finished is where the book got stuck.
    open_steps = {}
    for e in events:
        if e.event == "start":
            open_steps.setdefault(e.step, []).append(e.id)
        elif e.event in ("done", "failed") and open_steps.get(e.step):
            open_steps[e.step].pop()
    stuck = {i for ids in open_steps.values() for i in ids}
    first = events[0].at if events else None
    return {
        "book": {**_book_row(b, user.email if user else None), "details": b.details, "started_at": _iso(b.started_at),
                 "finished_at": _iso(b.finished_at), "style": b.style_key, "story": b.story_key},
        "upload": dict(upload._mapping) if upload else None,
        "photo_url": f"/admin/api/books/{ref}/photo" if upload else None,
        "reviews": [{**{k: getattr(r, k) for k, _ in QUESTIONS}, "not_good": r.not_good, "at": _iso(r.created_at)}
                    for r in reviews],
        "images": [{
            "kind": i.kind, "page": i.page_number, "status": i.status, "prompt": i.prompt, "refs": i.refs,
            "provider": i.provider, "model": i.model, "quality": i.quality, "tokens": i.tokens,
            "cost": float(i.cost or 0), "provider_request_id": i.provider_request_id, "error_code": i.error_code,
            "error_message": i.error_message, "seconds": _seconds(i.started_at, i.finished_at),
            "started_at": _iso(i.started_at),
            "image_url": f"/api/books/{ref}/images/{i.kind}-{i.page_number}" if i.status == "done" else None,
        } for i in sorted(b.images, key=lambda i: (i.kind != "hero_sheet", i.page_number))],
        "events": [{"id": e.id, "at": _iso(e.at), "offset": _seconds(first, e.at), "level": e.level, "step": e.step,
                    "event": e.event, "duration_ms": e.duration_ms, "fields": e.fields, "stuck": e.id in stuck}
                   for e in events],
    }


@router.get("/api/books/{ref}/photo")
async def photo(ref: str, _=Depends(require_admin)):
    async with session() as s:
        data = (await s.execute(select(Upload.image).where(Upload.book_id == ref))).scalar_one_or_none()
    if data is None:
        raise HTTPException(404, "No photo.")
    return Response(data, media_type="image/webp", headers={"Cache-Control": "private, max-age=3600"})


# --- reviews --------------------------------------------------------------------------------------

@router.get("/api/reviews")
async def reviews(_=Depends(require_admin)):
    async with session() as s:
        rows = (await s.execute(select(Review, Book.child_name, Book.gender, User.email)
                                .join(Book, Book.id == Review.book_id).outerjoin(User, User.id == Book.user_id)
                                .order_by(Review.created_at.desc()))).all()
    people = {r.respondent_key for r, *_ in rows}
    questions = []
    for key, label in QUESTIONS:
        scores = [getattr(r, key) for r, *_ in rows]
        questions.append({"key": key, "label": label, "average": round(sum(scores) / len(scores), 2) if scores else None,
                          "counts": [scores.count(n) for n in range(1, 6)]})
    return {"people": len(people), "count": len(rows), "questions": questions,
            "items": [{"book_id": r.book_id, "at": _iso(r.created_at), "email": email, "child_name": child,
                       "gender": gender, "not_good": r.not_good, **{k: getattr(r, k) for k, _ in QUESTIONS},
                       "source": r.source, "participant_id": r.connect_id, "respondent": r.respondent_key,
                       "cover_url": f"/api/books/{r.book_id}/images/hero_sheet-0"}
                      for r, child, gender, email in rows]}


@router.get("/api/qr.svg")
async def qr(url: str = "", _=Depends(require_admin)):
    """A QR code for handing out the site, e.g. on a slide or in Engage/Connect."""
    import segno
    target = url if url.startswith("https://") else os.getenv("PUBLIC_URL", "https://jack.graydates.com")
    buf = io.BytesIO()
    segno.make(target, error="m").save(buf, kind="svg", scale=10, border=2, dark="#2b2219")
    return Response(buf.getvalue(), media_type="image/svg+xml",
                    headers={"Content-Disposition": 'inline; filename="jack-qr.svg"'})


# --- activity ------------------------------------------------------------------------------------

# Each Activity filter is a set of steps (problems: anything logged as a warning or error).
ACTIVITY_KINDS = {"money": ["wallet"], "sign-ins": ["sign-in", "unlock"], "books": ["book", "request"],
                  "reviews": ["review"]}


@router.get("/api/activity")
async def activity(kind: str = "", q: str = "", days: int = 7, limit: int = 300, _=Depends(require_admin)):
    """Everything people did, newest first, plus the money totals for the period (from the ledger)."""
    since = datetime.now(timezone.utc) - timedelta(days=max(1, min(days, 365)))
    query = (select(Activity, User.email).outerjoin(User, User.id == Activity.user_id)
             .where(Activity.at >= since).order_by(Activity.at.desc(), Activity.id.desc()).limit(min(limit, 1000)))
    if kind == "problems":
        query = query.where(Activity.level != "INFO")
    elif kind in ACTIVITY_KINDS:
        query = query.where(Activity.step.in_(ACTIVITY_KINDS[kind]))
    if q:
        like = f"%{q.strip().lower()}%"
        query = query.where(or_(func.lower(User.email).like(like), func.lower(Activity.book_id).like(like)))
    async with session() as s:
        rows = (await s.execute(query)).all()
        money = dict((await s.execute(select(Transaction.kind, func.sum(Transaction.amount_cents))
                                      .where(Transaction.created_at >= since).group_by(Transaction.kind))).all())
        held = (await s.execute(select(func.sum(Transaction.amount_cents)))).scalar() or 0
    return {"items": [{"id": a.id, "at": _iso(a.at), "email": email, "book_id": a.book_id, "level": a.level,
                       "step": a.step, "event": a.event, "fields": a.fields or {}} for a, email in rows],
            "money": {"added": money.get("deposit", 0), "spent": -money.get("book", 0),
                      "refunded_to_cards": -money.get("refund", 0), "books_refunded": money.get("book_refund", 0),
                      "in_wallets": held}}


# --- the character bible --------------------------------------------------------------------------

@router.get("/api/characters")
async def characters(_=Depends(require_admin)):
    """Every story's characters, each with every saved version and the one books use right now."""
    out = []
    for story in all_stories():
        prompts = bible.prompts_for(story)
        cast = []
        for key, c in story.characters.items():
            chosen = await bible.choose(story, key, prompts)
            async with session() as s:
                versions = (await s.execute(
                    select(CharacterPicture.id, CharacterPicture.name, CharacterPicture.source, CharacterPicture.cost,
                           CharacterPicture.created_at)
                    .join(StoryCharacter, CharacterPicture.character_id == StoryCharacter.id).join(StoryRow)
                    .where(StoryRow.key == story.key, StoryCharacter.key == key).order_by(CharacterPicture.id))).all()
            cast.append({"key": key, "name": Casting(story).fill(c.name), "description": c.description,
                         "picture": c.picture, "why": chosen.why,
                         "in_use": chosen.picture.name if chosen.picture else None,
                         "in_use_url": f"/admin/api/characters/{chosen.picture.id}.png" if chosen.picture else None,
                         "versions": [{"id": v.id, "name": v.name, "source": v.source, "cost": float(v.cost or 0),
                                       "at": _iso(v.created_at), "url": f"/admin/api/characters/{v.id}.png"}
                                      for v in versions]})
        out.append({"key": story.key, "title": story.title, "characters": cast})
    return out


@router.post("/api/characters/{story_key}/{key}/picture")
async def upload_character(story_key: str, key: str, photo: UploadFile = File(...), _=Depends(require_admin)):
    """Replace a character's picture: the upload becomes a new version (the old ones are kept)."""
    from PIL import Image, UnidentifiedImageError
    story = next((s for s in all_stories() if s.key == story_key), None)
    if story is None or key not in story.characters:
        raise HTTPException(404, {"message": "No such character."})
    data = await photo.read()
    if len(data) > 20 * 1024 * 1024:
        raise HTTPException(413, {"message": "That picture is too large (max 20 MB)."})
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except (UnidentifiedImageError, OSError):
        raise HTTPException(400, {"message": "That file isn't a picture we can read."})
    img = img.convert("RGBA" if img.mode in ("RGBA", "LA", "P") else "RGB")
    img.thumbnail((1536, 1536))
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    picture, in_use = await bible.add_upload(story, key, buf.getvalue())
    pin = story.characters[key].picture
    return {"name": picture.name, "in_use": in_use,
            "note": None if in_use else f"Saved as {picture.name}, but the story file pins {pin}, so books keep using "
                                        f"that until the picture: line is changed."}


@router.get("/api/characters/{picture_id}.png")
async def character_png(picture_id: int, w: int = 360, _=Depends(require_admin)):
    from PIL import Image
    async with session() as s:
        data = (await s.execute(select(CharacterPicture.image).where(CharacterPicture.id == picture_id))
                ).scalar_one_or_none()
    if data is None:
        raise HTTPException(404, "No such picture.")
    img = Image.open(io.BytesIO(data)).convert("RGB")
    img.thumbnail((min(w, 1600), min(w, 1600)))
    buf = io.BytesIO()
    img.save(buf, "WEBP", quality=85)
    return Response(buf.getvalue(), media_type="image/webp", headers={"Cache-Control": "private, max-age=86400"})


# --- errors outside books -------------------------------------------------------------------------

@router.get("/api/errors")
async def errors(q: str = "", type: str = "", limit: int = 200, _=Depends(require_admin)):
    query = select(RequestError).order_by(RequestError.created_at.desc()).limit(min(limit, 1000))
    if type:
        query = query.where(RequestError.error_type == type)
    if q:
        like = f"%{q.strip().lower()}%"
        query = query.where(or_(func.lower(RequestError.id).like(like), func.lower(RequestError.message).like(like),
                                func.lower(RequestError.path).like(like)))
    async with session() as s:
        rows = (await s.execute(query)).scalars().all()
        types = (await s.execute(select(RequestError.error_type).distinct())).scalars().all()
    return {"items": [{"id": r.id, "at": _iso(r.created_at), "path": r.path, "status": r.status_code,
                       "type": r.error_type, "message": r.message, "traceback": r.traceback, "browser": r.browser}
                      for r in rows],
            "types": sorted(t for t in types if t)}


# --- the model switch -----------------------------------------------------------------------------

class SettingsIn(BaseModel):
    provider: str
    model: str | None = None
    quality: str | None = None


def _available() -> dict:
    return {
        "openai": bool(os.getenv("OPENAI_API_KEY")),
        "agnes": bool(os.getenv("AGNES_API_KEY")),
        "mock": True,
    }


@router.get("/api/settings")
async def get_settings(user=Depends(require_admin)):
    async with session() as s:
        current = await s.get(AdminSettings, user.id)
    return {"provider": current.provider if current else "openai", "model": current.model if current else None,
            "quality": current.quality if current else None, "choices": CHOICES, "available": _available(),
            "forced_mock": is_mock()}


@router.put("/api/settings")
async def put_settings(body: SettingsIn, user=Depends(require_admin)):
    choice = CHOICES.get(body.provider)
    if choice is None or (body.model and body.model not in choice["models"]) or \
            (body.quality and body.quality not in choice["qualities"]):
        raise HTTPException(400, {"message": "That provider, model or quality isn't one of the choices."})
    async with session() as s:
        current = await s.get(AdminSettings, user.id) or AdminSettings(user_id=user.id)
        current.provider = body.provider
        current.model = body.model or choice["models"][0]
        current.quality = body.quality or choice["default_quality"] or None
        s.add(current)
        await s.commit()
    return await get_settings(user)


# --- unlimited list -------------------------------------------------------------------------------

class EmailIn(BaseModel):
    email: str


@router.get("/api/unlimited")
async def unlimited(_=Depends(require_admin)):
    async with session() as s:
        rows = (await s.execute(select(UnlimitedEmail).order_by(UnlimitedEmail.created_at))).scalars().all()
    return {"admins": sorted(auth.admin_emails()), "emails": [{"email": r.email, "added": _iso(r.created_at)} for r in rows]}


@router.post("/api/unlimited")
async def add_unlimited(body: EmailIn, user=Depends(require_admin)):
    email = body.email.strip().lower()
    if "@" not in email or len(email) > 320:
        raise HTTPException(400, {"message": "That doesn't look like an email address."})
    async with session() as s:
        if await s.get(UnlimitedEmail, email) is None:
            s.add(UnlimitedEmail(email=email, added_by=user.id))
            await s.commit()
    return await unlimited()


@router.delete("/api/unlimited/{email}")
async def remove_unlimited(email: str, _=Depends(require_admin)):
    async with session() as s:
        row = await s.get(UnlimitedEmail, email.lower())
        if row:
            await s.delete(row)
            await s.commit()
    return await unlimited()


# --- refunds: people ask in their wallet, the admin decides here ----------------------------------

@router.get("/api/refunds")
async def refunds(status: str = "", _=Depends(require_admin)):
    items = await wallet.admin_requests(status)
    return {"items": items, "pending": sum(1 for i in items if i["status"] == "pending") if not status else None}


class DecisionIn(BaseModel):
    approve: bool
    note: str | None = None


@router.post("/api/refunds/{request_id}")
async def decide_refund(request_id: int, body: DecisionIn, user=Depends(require_admin)):
    r = await wallet.decide(request_id, body.approve, user, body.note)
    return {"status": r.status, "admin_note": r.admin_note}
