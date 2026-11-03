"""Book jobs. A request creates the book's rows and returns at once; drawing runs in the background.

Every image and step is saved as it happens, so the page can show per-image progress, a dropped
connection doesn't lose a paid book, and a restart resumes without redrawing finished images.
One call per image, no retries.
"""
import asyncio
import hashlib
import io
import statistics
from datetime import datetime, timezone

import openai
from PIL import Image, ImageOps
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from ..db.models import Book, BookEvent, BookImage, Upload
from ..db.session import session
from ..faces import PreparedPhoto, UploadError, from_saved, prepare
from .cast import CastSheets, MissingSheetError
from .log import record, start_book, step
from .pages import BookContext, ChildInfo, RenderedPage, make_page
from .pdf import build_pdf
from .prompts import PromptBuilder
from .providers import SHEET_SIZE, MockImageProvider, get_provider
from .story import DEFAULT_STORY, Casting, load_story
from .styles import get_style

PDF_NAME = "JackAndTheBeanstalk.pdf"
HERO = ("hero_sheet", 0)
DEFAULT_ETA = {"hero_sheet": 22.0, "page": 28.0}  # seconds, until there's history to go on
_tasks: set[asyncio.Task] = set()  # keep references so running books aren't garbage-collected


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def to_webp(png: bytes) -> bytes:
    buf = io.BytesIO()
    Image.open(io.BytesIO(png)).convert("RGB").save(buf, "WEBP", quality=90, method=4)
    return buf.getvalue()


def to_png(data: bytes) -> bytes:
    buf = io.BytesIO()
    Image.open(io.BytesIO(data)).convert("RGB").save(buf, "PNG")
    return buf.getvalue()


def prompt_version() -> str:
    """Changes whenever the story file (and so the prompts) change, to compare results across edits."""
    story = load_story()
    return hashlib.sha1(DEFAULT_STORY.read_bytes() + get_style(story.style).description.encode()).hexdigest()[:8]


def friendly_error(e: BaseException) -> tuple[str, str]:
    """(error_code, message the user sees) for anything that can stop a book."""
    if isinstance(e, MissingSheetError):
        return "missing_sheet", "The book's character pictures are missing on the server."
    if isinstance(e, openai.APITimeoutError):
        return "timeout", "The image service took too long to draw a page. Please try again."
    if isinstance(e, openai.BadRequestError):
        code = getattr(e, "code", None) or "bad_request"
        if code == "moderation_blocked":
            return code, "The image service's safety filter blocked a picture. Trying again usually works."
        return code, f"The image service rejected this request: {e.message}"
    if isinstance(e, openai.OpenAIError):
        return type(e).__name__, "The image service failed. Please try again in a moment."
    return type(e).__name__, "Something went wrong on our side."


# --- event trail ----------------------------------------------------------------------------------

async def save_event(book_id, level, step_name, event, duration_ms, fields):
    async with session() as s:
        s.add(BookEvent(book_id=book_id, level=level, step=step_name, event=event,
                        duration_ms=duration_ms, fields=fields or None))
        await s.commit()


# --- creating a book ------------------------------------------------------------------------------

async def create_book(ref: str, *, gender: str, child_name: str, details: list, provider: str,
                      model: str | None, quality: str | None, user_id=None) -> None:
    """The row exists from the first moment of the request, so every ref can be looked up."""
    story = load_story()
    async with session() as s:
        s.add(Book(id=ref, user_id=user_id, story_key=DEFAULT_STORY.stem, style_key=story.style,
                   prompt_version=prompt_version(), gender=gender[:8], child_name=child_name, details=details,
                   provider=provider, model=model, quality=quality, page_size=None))
        await s.commit()


async def books_today(user_id, exclude: str | None = None) -> int:
    """Books that count towards the daily limit (UTC day). Refused books never count; a failed book
    counts only if at least one picture was drawn, since that's when it cost something."""
    midnight = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    async with session() as s:
        books = (await s.execute(select(Book).where(Book.user_id == user_id, Book.created_at >= midnight)
                                 .options(selectinload(Book.images)))).scalars().all()
    return sum(1 for b in books if b.id != exclude and b.status != "refused"
               and (b.status != "failed" or any(i.status == "done" for i in b.images)))


async def refuse(ref: str, reason: str, message: str) -> None:
    async with session() as s:
        book = await s.get(Book, ref)
        book.status, book.refused_reason, book.error_message, book.finished_at = "refused", reason, message, utcnow()
        await s.commit()
    await record("WARNING", "request", "refused", reason=reason)


async def keep_refused_photo(ref: str, data: bytes, mime: str) -> None:
    """A photo the face check turned away is kept too, so the admin can see why (never drawn from)."""
    try:
        img = Image.open(io.BytesIO(data))
        img = ImageOps.exif_transpose(img).convert("RGB")
        img.thumbnail((1024, 1024))
        buf = io.BytesIO()
        img.save(buf, "WEBP", quality=85)
        async with session() as s:
            s.add(Upload(book_id=ref, image=buf.getvalue(), mime=mime[:32], width=img.width, height=img.height))
            await s.commit()
    except Exception:
        pass  # unreadable files have nothing to show


async def accept(ref: str, photo: PreparedPhoto, mime: str) -> None:
    """Save the photo and one waiting row per image, then start drawing in the background."""
    story = load_story()
    img = Image.open(io.BytesIO(photo.full_png))
    async with session() as s:
        s.add(Upload(book_id=ref, image=to_webp(photo.full_png), mime=mime, width=img.width, height=img.height,
                     face_box=photo.face_box))
        s.add(BookImage(book_id=ref, kind="hero_sheet", page_number=0))
        for spec in story.pages:
            if make_page(spec).needs_image:
                s.add(BookImage(book_id=ref, kind="page", page_number=spec.number))
        await s.commit()
    spawn(ref)


async def retry(ref: str) -> bool:
    """Redraw only the pictures that didn't finish; finished ones are kept and not paid for again.
    Started by the person pressing "try again", never automatically (one call per image, no loops)."""
    async with session() as s:
        book = (await s.execute(select(Book).where(Book.id == ref).options(selectinload(Book.images)))).scalar_one()
        if book.status not in ("failed", "interrupted"):
            return False
        for i in book.images:
            if i.status != "done":
                i.status, i.error_code, i.error_message, i.started_at, i.finished_at = "waiting", None, None, None, None
        book.status, book.error_code, book.error_message, book.finished_at = "queued", None, None, None
        await s.commit()
    start_book(ref)
    await record("INFO", "book", "retry", note="the reader asked to redraw the missing pictures")
    spawn(ref)
    return True


def spawn(ref: str) -> None:
    task = asyncio.create_task(run_book(ref))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


# --- drawing --------------------------------------------------------------------------------------

async def _set_image(ref, key, **values):
    async with session() as s:
        row = (await s.execute(select(BookImage).where(BookImage.book_id == ref, BookImage.kind == key[0],
                                                       BookImage.page_number == key[1]))).scalar_one()
        for k, v in values.items():
            setattr(row, k, v)
        await s.commit()


async def _draw(ref, key, provider, prompt, refs, call):
    """Draw one image, saving drawing / done / failed on its row as it goes. Returns PNG bytes."""
    await _set_image(ref, key, status="drawing", started_at=utcnow(), finished_at=None, prompt=prompt,
                     refs=refs, provider=provider.name, model=provider.model, quality=provider.quality,
                     error_code=None, error_message=None)
    try:
        result = await call()
    except Exception as e:
        code, message = friendly_error(e)
        await _set_image(ref, key, status="failed", finished_at=utcnow(), error_code=code, error_message=message,
                         provider_request_id=getattr(e, "request_id", None))
        raise
    await _set_image(ref, key, status="done", finished_at=utcnow(), image=to_webp(result.png),
                     cost=result.cost, tokens=result.tokens or None, provider_request_id=result.request_id)
    return result.png


async def _load(ref):
    async with session() as s:
        return (await s.execute(select(Book).where(Book.id == ref)
                                .options(selectinload(Book.upload), selectinload(Book.images)))).scalar_one()


def _context(book, hero_png, provider):
    story = load_story()
    casting = Casting(story, book.gender)
    prompts = PromptBuilder(get_style(story.style), story, casting)
    fallback = None
    if isinstance(provider, MockImageProvider):  # mock books work before the real sheets exist
        def fallback(key):
            return MockImageProvider._draw(f"{key} sheet", SHEET_SIZE, None, 0)
    child = ChildInfo(book.child_name, [tuple(d) for d in book.details])
    return story, BookContext(casting, prompts, provider, CastSheets(hero_png, fallback=fallback), child)


async def run_book(ref: str) -> None:
    start_book(ref)
    try:
        async with step("book", ref=ref):
            await _run(ref)
    except Exception as e:
        code, message = friendly_error(e)
        async with session() as s:
            book = await s.get(Book, ref)
            book.status, book.error_code, book.error_message, book.finished_at = "failed", code, message, utcnow()
            await s.commit()


async def _run(ref: str) -> None:
    book = await _load(ref)
    async with session() as s:
        row = await s.get(Book, ref)
        row.status, row.started_at = "running", row.started_at or utcnow()
        await s.commit()

    provider = get_provider(book.provider, book.model, book.quality)
    rows = {(i.kind, i.page_number): i for i in book.images}
    upload = book.upload
    if upload.face_box:
        photo = from_saved(upload.image, upload.face_box)  # the same face crop and size the model saw
    else:  # accepted before face boxes were saved
        try:
            photo = prepare(upload.image)
        except UploadError:
            photo = from_saved(upload.image, None)

    hero = rows[HERO]
    if hero.status == "done":
        hero_png = to_png(hero.image)
    else:
        if upload.face_description is None:
            description = await provider.describe_face(photo.face_png)
            async with session() as s:
                (await s.get(Upload, ref)).face_description = description
                await s.commit()
        else:
            description = upload.face_description
        story, ctx = _context(book, b"", provider)
        prompt = ctx.prompts.hero_sheet(description)
        hero_png = await _draw(ref, HERO, provider, prompt, ["photo"],
                               lambda: provider.edit("hero sheet", [("photo.png", photo.full_png)], prompt, SHEET_SIZE))

    story, ctx = _context(book, hero_png, provider)
    pages = [make_page(spec) for spec in story.pages]
    todo = [p for p in pages if p.needs_image and rows[("page", p.spec.number)].status != "done"]
    # All pages at once: a book takes about as long as its slowest page.
    outcomes = await asyncio.gather(
        *(_draw(ref, ("page", p.spec.number), provider, p.prompt(ctx), list(p.spec.cast),
                (lambda p=p: p.draw(ctx))) for p in todo),
        return_exceptions=True)
    failures = [o for o in outcomes if isinstance(o, BaseException)]

    async with session() as s:
        row = await s.get(Book, ref)
        images = (await s.execute(select(BookImage).where(BookImage.book_id == ref))).scalars().all()
        row.total_cost = sum(float(i.cost or 0) for i in images)
        row.finished_at = utcnow()
        if failures:
            row.status = "failed"
            row.error_code, row.error_message = friendly_error(failures[0])
        else:
            row.status = "done"
        await s.commit()
    if failures:
        raise failures[0]


# --- reading back ---------------------------------------------------------------------------------

async def eta_seconds(kind: str, provider: str, model: str | None) -> float:
    """Median of how long this kind of image recently took with this model, for the progress bars."""
    if provider == "mock":
        return max(2.0, MockImageProvider().delay)
    async with session() as s:
        rows = (await s.execute(
            select(BookImage.started_at, BookImage.finished_at)
            .where(BookImage.kind == kind, BookImage.status == "done", BookImage.provider == provider,
                   BookImage.model == model, BookImage.started_at.is_not(None))
            .order_by(BookImage.finished_at.desc()).limit(30))).all()
    durations = [(f - s).total_seconds() for s, f in rows if f]
    return round(statistics.median(durations), 1) if len(durations) >= 3 else DEFAULT_ETA[kind]


def _iso(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:  # SQLite drops the timezone; everything is stored in UTC
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


async def status(ref: str) -> dict | None:
    async with session() as s:
        book = (await s.execute(select(Book).where(Book.id == ref).options(selectinload(Book.images)))).scalar_one_or_none()
    if book is None:
        return None
    story = load_story()
    casting = Casting(story, book.gender)
    texts = {spec.number: casting.fill(spec.text) for spec in story.pages}
    etas = {}
    images = []
    for i in sorted(book.images, key=lambda i: (i.kind != "hero_sheet", i.page_number)):
        if i.kind not in etas:
            etas[i.kind] = await eta_seconds(i.kind, book.provider, book.model)
        images.append({
            "kind": i.kind, "page": i.page_number, "status": i.status,
            "label": "Your cartoon" if i.kind == "hero_sheet" else f"Page {i.page_number}",
            "text": texts.get(i.page_number, ""),
            "started_at": _iso(i.started_at), "finished_at": _iso(i.finished_at),
            "eta_seconds": etas[i.kind], "error": i.error_message,
            "image_url": f"/api/books/{ref}/images/{i.kind}-{i.page_number}" if i.status == "done" else None,
        })
    result = {"id": book.id, "status": book.status, "error": book.error_message, "refused_reason": book.refused_reason,
              "server_time": _iso(utcnow()), "images": images,
              "pdf_url": f"/api/books/{ref}/pdf" if book.status == "done" else None}
    if book.status == "done":
        result["book"] = _flipbook(book, story, casting)
    return result


def _flipbook(book, story, casting) -> dict:
    """What the on-site flip book shows: the same pages and text as the PDF, plus a cover."""
    pages = []
    for spec in story.pages:
        if make_page(spec).needs_image:
            pages.append({"kind": "illustrated", "number": spec.number, "text": casting.fill(spec.text),
                          "text_zone": spec.text_zone, "image_url": f"/api/books/{book.id}/images/page-{spec.number}"})
        else:
            pages.append({"kind": spec.type, "number": spec.number})
    return {"title": story.title, "hero": casting.hero_name, "child_name": book.child_name,
            "details": [list(d) for d in book.details], "cover_url": f"/api/books/{book.id}/images/hero_sheet-0",
            "pages": pages}


async def image_bytes(ref: str, kind: str, page: int) -> bytes | None:
    async with session() as s:
        return (await s.execute(select(BookImage.image).where(BookImage.book_id == ref, BookImage.kind == kind,
                                                              BookImage.page_number == page,
                                                              BookImage.status == "done"))).scalar_one_or_none()


async def pdf_bytes(ref: str) -> bytes | None:
    """Rebuilt from the saved images on each download, so PDFs don't take up database space."""
    book = await _load(ref)
    if book.status != "done":
        return None
    rows = {(i.kind, i.page_number): i for i in book.images}
    story, ctx = _context(book, to_png(rows[HERO].image), get_provider("mock"))
    pages = []
    for spec in story.pages:
        page = make_page(spec)
        image = to_png(rows[("page", spec.number)].image) if page.needs_image else None
        pages.append(page.layout(ctx, image))
    cover = RenderedPage(0, "cover", image=ctx.sheets.hero_sheet, child=ctx.child)
    return build_pdf(pages, story.title, cover=cover)


async def resume_unfinished() -> None:
    """After a restart (e.g. a deploy), carry on with books that were mid-way. Finished images are kept."""
    async with session() as s:
        refs = (await s.execute(select(Book.id).where(Book.status.in_(("queued", "running"))))).scalars().all()
        for ref in refs:
            (await s.get(Book, ref)).status = "interrupted"
        await s.commit()
    for ref in refs:
        start_book(ref)
        await record("WARNING", "book", "interrupted", note="server restarted; resuming")
        spawn(ref)
