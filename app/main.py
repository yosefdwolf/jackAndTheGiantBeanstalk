import hmac
import os
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()  # local dev only; on Railway the key comes from service variables

import openai  # noqa: E402
from fastapi import FastAPI, File, Form, Header, HTTPException, Request, UploadFile  # noqa: E402
from fastapi.responses import FileResponse, Response  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from .book.builder import PDF_NAME, build_book  # noqa: E402
from .book.cast import MissingSheetError  # noqa: E402
from .book.log import fields, log, setup_logging, start_book, step, total_cost  # noqa: E402
from .book.pages import ChildInfo  # noqa: E402
from .book.providers import is_mock  # noqa: E402
from .book.story import PRONOUNS, load_story  # noqa: E402
from .faces import UploadError, prepare  # noqa: E402

STATIC = Path(__file__).resolve().parent.parent / "static"
MAX_UPLOAD_BYTES = 25 * 1024 * 1024  # phone photos can be large; they are downscaled on arrival
MAX_FIELD = 300

setup_logging(os.getenv("LOG_LEVEL", "INFO"))
app = FastAPI(title="Jack and the Beanstalk")
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/options")
def options():
    story = load_story()
    return {
        "title": story.title,
        "heroes": story.hero_names,
        "pages": len(story.pages),
        "mock": is_mock(),
    }


def check_password(given: str | None) -> None:
    """Every paid request needs APP_PASSWORD. If it isn't set, real books are refused (fail closed)."""
    expected = os.getenv("APP_PASSWORD", "")
    if not expected:
        if is_mock():
            return  # mock books cost nothing
        raise HTTPException(503, "The server has no APP_PASSWORD set, so it won't make books.")
    if not given or not hmac.compare_digest(given.encode(), expected.encode()):
        raise HTTPException(401, "Wrong password.")


def fail(book_id: str, status: int, message: str, reason: str) -> HTTPException:
    """Log why a book was refused and return the error, tagged with the book's reference."""
    log.warning("refused status=%d reason=%s", status, reason)
    return HTTPException(status, f"{message} (ref {book_id})", headers={"X-Book-Id": book_id})


@app.post("/api/book")
async def book_route(
    request: Request,
    x_app_password: str | None = Header(None),
    photo: UploadFile = File(...),
    name: str = Form(...),
    gender: str = Form("boy"),
    age: str = Form(""),
    favourites: str = Form(""),
    about: str = Form(""),
):
    book_id = start_book()
    t0 = time.perf_counter()
    # Never log the password, the photo, or the child's name and details.
    log.info("book requested %s", fields(ip=request.client.host if request.client else None, gender=gender,
                                         details=sum(bool(v.strip()) for v in (age, favourites, about))))
    try:
        check_password(x_app_password)
    except HTTPException as e:
        raise fail(book_id, e.status_code, e.detail,
                   "no APP_PASSWORD set" if e.status_code == 503 else "wrong password")

    data = await photo.read()
    log.info("photo received bytes=%d", len(data))
    if len(data) > MAX_UPLOAD_BYTES:
        raise fail(book_id, 413, "That photo is too large (max 25 MB).", "photo too large")
    if gender not in PRONOUNS:
        raise fail(book_id, 400, "Choose Jack or Jane.", "unknown gender")
    name = name.strip()
    if not name:
        raise fail(book_id, 400, "Please enter the child's name.", "no name")
    if any(len(v) > MAX_FIELD for v in (name, age, favourites, about)):
        raise fail(book_id, 400, f"Each answer can be up to {MAX_FIELD} characters.", "field too long")
    details = [(label, value.strip()) for label, value in
               (("Age", age), ("Favourite things", favourites), ("More about me", about)) if value.strip()]

    try:
        async with step("face check"):
            prepared = prepare(data)
    except UploadError as e:
        raise fail(book_id, 422, str(e), "face check")

    try:
        pdf = await build_book(prepared, ChildInfo(name, details), gender)
    except Exception as e:
        if isinstance(e, MissingSheetError):
            raise fail(book_id, 500, str(e), "missing character sheet")
        if isinstance(e, openai.APITimeoutError):
            raise fail(book_id, 504, "The image service took too long to draw a page. Please try again.", "timeout")
        if isinstance(e, openai.BadRequestError):
            raise fail(book_id, 400, f"The image service rejected this request: {e.message}",
                       f"openai {getattr(e, 'code', '')}")
        if isinstance(e, openai.OpenAIError):
            raise fail(book_id, 502, "The image service failed. Please try again in a moment.",
                       f"openai {type(e).__name__}")
        log.exception("book crashed")
        raise fail(book_id, 500, "Something went wrong on our side.", "unexpected error") from e

    log.info("book done %s", fields(pdf_bytes=len(pdf), seconds=f"{time.perf_counter() - t0:.1f}",
                                    cost=f"${total_cost():.3f}"))
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{PDF_NAME}"', "X-Book-Id": book_id})
