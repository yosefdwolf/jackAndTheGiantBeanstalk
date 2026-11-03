import hashlib
import hmac
import io
import os
import traceback
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()  # local dev only; on Railway the key comes from service variables

from fastapi import FastAPI, File, Form, Header, HTTPException, Request, UploadFile  # noqa: E402
from fastapi.responses import HTMLResponse, JSONResponse, Response  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from PIL import Image, ImageOps  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402
from sqlalchemy import select  # noqa: E402

from . import admin, auth  # noqa: E402
from .book import jobs  # noqa: E402
from .book.log import current_ref, new_ref, record, set_event_sink, set_ref, setup_logging, start_book, step  # noqa: E402
from .book.providers import is_mock  # noqa: E402
from .book.story import PRONOUNS, load_story  # noqa: E402
from .db.models import Book, RequestError, Review  # noqa: E402
from .db.session import create_tables_if_sqlite, session  # noqa: E402
from .faces import UploadError, prepare  # noqa: E402

STATIC = Path(__file__).resolve().parent.parent / "static"
MAX_UPLOAD_BYTES = 25 * 1024 * 1024  # phone photos can be large; they are downscaled on arrival
MAX_FIELD = 300
DAILY_LIMIT = int(os.getenv("DAILY_BOOK_LIMIT", "3"))

setup_logging(os.getenv("LOG_LEVEL", "INFO"))


@asynccontextmanager
async def lifespan(app):
    await create_tables_if_sqlite()
    set_event_sink(jobs.save_event)
    await jobs.resume_unfinished()
    yield


app = FastAPI(title="Jack and the Beanstalk", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC), name="static")
app.include_router(auth.router)
app.include_router(admin.router)
app.add_middleware(admin.AdminHost)  # admin.jack.graydates.com/x is served from /admin/x

# Browsers kept running an old app.js after deploys, so a click did nothing. The page's script and
# stylesheet links carry a content hash, and everything is served with no-cache (re-check each time).
ASSET_FILES = ["app.js", "styles.css", *(str(p.relative_to(STATIC)) for p in sorted((STATIC / "themes").rglob("*.*")))]
ASSET_VERSION = hashlib.sha1(b"".join((STATIC / f).read_bytes() for f in ASSET_FILES)).hexdigest()[:10]
NO_CACHE = {"Cache-Control": "no-cache"}


async def save_request_error(ref, path, status_code, error_type, message, tb=None, browser=None):
    try:
        async with session() as s:
            s.add(RequestError(id=ref, path=path[:256], status_code=status_code, error_type=error_type,
                               message=message, traceback=tb, browser=browser))
            await s.commit()
    except Exception:
        pass  # recording an error must never cause another


@app.middleware("http")
async def refs_and_errors(request: Request, call_next):
    """Every request gets a ref (X-Request-Id). An unexpected crash is saved to request_errors with it."""
    ref = new_ref()
    set_ref(ref)
    try:
        response = await call_next(request)
    except Exception as e:
        await save_request_error(ref, request.url.path, 500, type(e).__name__, str(e), traceback.format_exc(),
                                 request.headers.get("user-agent"))
        await record("ERROR", "request", "crashed", path=request.url.path, error=type(e).__name__)
        response = JSONResponse({"detail": f"Something went wrong on our side. Reference: {ref}", "ref": ref},
                                status_code=500)
    response.headers["X-Request-Id"] = ref
    if request.url.path == "/" or request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache"
    return response


def themed(page: str) -> str:
    """A page from static/, dressed in the story's theme (static/themes/<theme>/)."""
    story = load_story()
    html = (STATIC / page).read_text()
    html = html.replace("<!--THEME_CSS-->", f'<link rel="stylesheet" href="/static/themes/{story.theme}/theme.css">')
    html = html.replace("<!--SCENE-->", (STATIC / "themes" / story.theme / "scene.html").read_text())
    html = html.replace("{{TITLE}}", story.title)
    for asset in ("app.js", "styles.css", f"themes/{story.theme}/theme.css"):
        html = html.replace(f"/static/{asset}\"", f"/static/{asset}?v={ASSET_VERSION}\"")
    return html


@app.get("/")
def index():
    return HTMLResponse(themed("index.html"), headers=NO_CACHE)


@app.get("/privacy")
def privacy():
    """Linked from Google's sign-in screen. CONTACT_EMAIL, else the first admin, is who to write to."""
    contact = os.getenv("CONTACT_EMAIL") or next(iter(sorted(auth.admin_emails())), "")
    return HTMLResponse(themed("privacy.html").replace("{{CONTACT}}", contact), headers=NO_CACHE)


@app.post("/api/client-error")
async def client_error(request: Request):
    """The page reports its own script errors here. Returns the ref the page shows the user."""
    ref = current_ref()
    body = (await request.body())[:2000].decode(errors="replace")
    await save_request_error(ref, "page-script", None, "PageScriptError", body,
                             browser=request.headers.get("user-agent"))
    await record("WARNING", "page script", "error", ip=request.client.host if request.client else None, report=body)
    return {"ref": ref}


@app.post("/no-script")
def no_script():
    """Where the form lands if the page's script failed to load (the script normally takes over)."""
    return HTMLResponse("<p style='font:18px Georgia,serif;padding:24px'>The page didn't finish loading. "
                        "Please <a href='/'>reload it</a> and try again.</p>", status_code=400)


@app.get("/api/options")
def options():
    story = load_story()
    return {"title": story.title, "heroes": story.hero_names, "pages": len(story.pages), "mock": is_mock()}


@app.get("/api/me")
async def me(request: Request):
    """Who is signed in, and how many books they have left today."""
    user = await auth.current_user(request)
    info = {"signed_in": user is not None, "sign_in_url": "/auth/login?next=/", "limit": DAILY_LIMIT}
    if user:
        unlimited = await auth.has_unlimited(user)
        used = await jobs.books_today(user.id)
        info.update(email=user.email, name=user.name, admin=auth.is_admin(user), unlimited=unlimited,
                    used_today=used, left=None if unlimited else max(0, DAILY_LIMIT - used))
    return info


def password_problem(given: str | None) -> tuple[int, str, str] | None:
    """Every paid request needs APP_PASSWORD. If it isn't set, real books are refused (fail closed)."""
    expected = os.getenv("APP_PASSWORD", "")
    if not expected:
        if is_mock():
            return None  # mock books cost nothing
        return 503, "no_app_password", "The server has no APP_PASSWORD set, so it won't make books."
    if not given or not hmac.compare_digest(given.encode(), expected.encode()):
        return 401, "wrong_password", "Wrong password."
    return None


@app.post("/api/unlock", status_code=204)
async def unlock(request: Request, x_app_password: str | None = Header(None)):
    """Checks the password on its own, so the page can open the rest of the form."""
    if problem := password_problem(x_app_password):
        status, reason, message = problem
        ref = current_ref()
        await save_request_error(ref, "/api/unlock", status, reason, message, browser=request.headers.get("user-agent"))
        await record("WARNING", "unlock", "refused", reason=reason, ip=request.client.host if request.client else None)
        raise HTTPException(status, {"message": message, "ref": ref, "reason": reason})
    return Response(status_code=204)


@app.post("/api/photo-preview")
async def photo_preview(photo: UploadFile = File(...)):
    """Turns a photo the browser can't show (e.g. HEIC in Chrome) into a JPEG for the preview and upload."""
    data = await photo.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, {"message": "That photo is too large (max 25 MB).", "ref": current_ref()})
    try:
        img = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
    except Exception:
        raise HTTPException(422, {"message": "That file isn't a photo we can read. Try a JPG, PNG or iPhone photo.",
                                  "ref": current_ref()})
    img.thumbnail((1600, 1600))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=90)
    return Response(buf.getvalue(), media_type="image/jpeg")


@app.post("/api/books", status_code=202)
async def create_book_route(
    request: Request,
    x_app_password: str | None = Header(None),
    photo: UploadFile = File(...),
    name: str = Form(...),
    gender: str = Form("boy"),
    age: str = Form(""),
    favourites: str = Form(""),
    about: str = Form(""),
):
    ref = start_book(current_ref())
    details = [[label, value.strip()[:MAX_FIELD]] for label, value in
               (("Age", age), ("Favourite things", favourites), ("More about me", about)) if value.strip()]
    user = await auth.current_user(request)
    provider, model, quality = await admin.provider_for(user)
    # The row exists before any check, so even a refused request can be looked up by its ref.
    await jobs.create_book(ref, gender=gender, child_name=name.strip()[:MAX_FIELD], details=details,
                           provider=provider, model=model, quality=quality, user_id=user.id if user else None)
    # Never log the password, the photo, or the child's name and details.
    await record("INFO", "request", "received", ip=request.client.host if request.client else None,
                 gender=gender, details=len(details), user=str(user.id) if user else None, provider=provider,
                 model=model)

    async def refuse(status: int, reason: str, message: str):
        await jobs.refuse(ref, reason, message)
        raise HTTPException(status, {"message": message, "ref": ref, "reason": reason}, headers={"X-Book-Id": ref})

    if problem := password_problem(x_app_password):
        await refuse(*problem)
    if user is None:
        await refuse(401, "not_signed_in", "Please sign in with Google first.")
    if not await auth.has_unlimited(user) and await jobs.books_today(user.id, exclude=ref) >= DAILY_LIMIT:
        await refuse(429, "daily_limit", f"That's {DAILY_LIMIT} books today, the most for one day. "
                                         "Come back tomorrow for more!")
    data = await photo.read()
    if len(data) > MAX_UPLOAD_BYTES:
        await refuse(413, "photo_too_large", "That photo is too large (max 25 MB).")
    if gender not in PRONOUNS:
        await refuse(400, "unknown_gender", "Choose Jack or Jane.")
    if not name.strip():
        await refuse(400, "no_name", "Please enter the child's name.")
    if any(len(v) > MAX_FIELD for v in (name, age, favourites, about)):
        await refuse(400, "field_too_long", f"Each answer can be up to {MAX_FIELD} characters.")
    try:
        async with step("face check", photo_bytes=len(data)):
            prepared = prepare(data)
    except UploadError as e:
        await refuse(422, "face_check", str(e))

    await jobs.accept(ref, prepared, photo.content_type or "image/unknown")
    return {"id": ref, "status_url": f"/api/books/{ref}"}


@app.get("/api/books/{ref}")
async def book_status(ref: str):
    data = await jobs.status(ref)
    if data is None:
        raise HTTPException(404, {"message": "No book with that reference.", "ref": ref})
    return data


@app.get("/api/books/{ref}/images/{name}")
async def book_image(ref: str, name: str, w: int | None = None):
    kind, _, page = name.rpartition("-")
    data = await jobs.image_bytes(ref, kind, int(page)) if page.isdigit() else None
    if data is None:
        raise HTTPException(404, "No such image.")
    if w:  # thumbnails for the progress list
        img = Image.open(io.BytesIO(data))
        img.thumbnail((min(w, 1600), min(w, 1600)))
        buf = io.BytesIO()
        img.save(buf, "WEBP", quality=85)
        data = buf.getvalue()
    return Response(data, media_type="image/webp", headers={"Cache-Control": "private, max-age=86400"})


@app.get("/api/books/{ref}/pdf")
async def book_pdf(ref: str, inline: bool = False):
    """Downloads by default; ?inline=1 opens it in the browser (the review card's "open the PDF")."""
    pdf = await jobs.pdf_bytes(ref)
    if pdf is None:
        raise HTTPException(404, {"message": "That book isn't finished.", "ref": ref})
    disposition = "inline" if inline else "attachment"
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'{disposition}; filename="{jobs.PDF_NAME}"'})


# --- reviews: each person rates their own book ----------------------------------------------------

class ReviewIn(BaseModel):
    looks_like_me: int = Field(ge=1, le=5)
    story_rings_true: int = Field(ge=1, le=5)
    looks_professional: int = Field(ge=1, le=5)
    not_good: str = Field("", max_length=2000)
    participant_id: str | None = Field(None, max_length=64, pattern=r"^[\w-]+$")  # from a crowd study's link


async def _own_book(request: Request, ref: str):
    """Only the person who made a book can review it (which also keeps out spam)."""
    user = await auth.current_user(request)
    if user is None:
        raise HTTPException(401, {"message": "Please sign in first.", "ref": current_ref(), "reason": "not_signed_in"})
    async with session() as s:
        book = await s.get(Book, ref)
    if book is None or book.user_id != user.id:
        raise HTTPException(404, {"message": "No book of yours with that reference.", "ref": current_ref()})
    if book.status != "done":
        raise HTTPException(409, {"message": "The book isn't finished yet.", "ref": current_ref()})
    return user, book


def _review_out(r: Review | None) -> dict | None:
    if r is None:
        return None
    return {"book_id": r.book_id, "looks_like_me": r.looks_like_me, "story_rings_true": r.story_rings_true,
            "looks_professional": r.looks_professional, "not_good": r.not_good or ""}


async def _their_review(s, user) -> Review | None:
    """One review per person, whichever of their books it was about."""
    return (await s.execute(select(Review).where(Review.respondent_key == str(user.id))
                            .order_by(Review.created_at.desc()))).scalars().first()


@app.get("/api/books/{ref}/review")
async def get_review(request: Request, ref: str):
    user, _ = await _own_book(request, ref)
    async with session() as s:
        return {"review": _review_out(await _their_review(s, user))}


@app.put("/api/books/{ref}/review")
async def put_review(request: Request, ref: str, body: ReviewIn):
    """One review per person: answering again (on any of their books) replaces their answers, and the
    review moves to the book they answered about last."""
    user, _ = await _own_book(request, ref)
    async with session() as s:
        r = await _their_review(s, user)
        if r is None:
            r = Review(book_id=ref, respondent_key=str(user.id), source="site")
            s.add(r)
        r.book_id = ref
        r.looks_like_me, r.story_rings_true, r.looks_professional = (body.looks_like_me, body.story_rings_true,
                                                                     body.looks_professional)
        r.not_good = body.not_good.strip() or None
        if body.participant_id:
            r.connect_id, r.source = body.participant_id, "connect"
        await s.commit()
    await record("INFO", "review", "saved", book=ref, scores=f"{body.looks_like_me}/{body.story_rings_true}/"
                                                             f"{body.looks_professional}")
    return {"review": _review_out(r)}
