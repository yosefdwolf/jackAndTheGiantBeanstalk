"""Book jobs. A request creates the book's rows and returns at once; drawing runs in the background.

Every image and step is saved as it happens, so the page can show per-image progress, a dropped
connection doesn't lose a paid book, and a restart resumes without redrawing finished images.
Each picture gets up to 3 tries (MAX_TRIES), a short pause apart: the assignment's quality loop asks
for it, and the image service's safety filter mostly blocks by mistake. A failed try isn't charged.
If a picture still fails, the book stops and its owner can try the missing pictures again by hand.
"""
import asyncio
import hashlib
import io
import os
import statistics
import uuid
from datetime import datetime, timezone

import openai
from PIL import Image, ImageOps
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from ..db.models import Activity, Book, BookEvent, BookImage, Upload
from ..db.session import session
from ..faces import PreparedPhoto, UploadError, from_saved, prepare
from . import bible
from .cast import CastSheets, MissingSheetError
from .log import record, start_book, step
from .pages import BookContext, ChildInfo, RenderedPage, make_page
from .pdf import build_pdf
from .prompts import PromptBuilder
from .providers import SHEET_SIZE, MockImageProvider, get_provider
from .story import DEFAULT_STORY, Casting, display_name, story_file, story_for
from .styles import get_style

HERO = ("hero_sheet", 0)
DEFAULT_ETA = {"hero_sheet": 22.0, "page": 28.0}  # seconds, until there's history to go on
# Pictures drawn at the same time. OpenAI refuses too many image calls at once, and a book now has 20.
IMAGE_CONCURRENCY = int(os.getenv("IMAGE_CONCURRENCY", "5"))
MAX_TRIES = 3
RETRY_PAUSE = float(os.getenv("RETRY_PAUSE_SECONDS", "2"))
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


def to_jpeg(data: bytes) -> bytes:
    """Pictures go into the PDF as JPEG: lossless PNG made a 20-page book about 65 MB."""
    buf = io.BytesIO()
    Image.open(io.BytesIO(data)).convert("RGB").save(buf, "JPEG", quality=88, optimize=True)
    return buf.getvalue()


def prompt_version(story) -> str:
    """Changes whenever the story file (and so the prompts) change, to compare results across edits."""
    return hashlib.sha1(story_file(story).read_bytes() + get_style(story.style).description.encode()).hexdigest()[:8]


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


async def save_activity(user_id, book_id, level, step_name, event, fields):
    async with session() as s:
        if user_id is None and fields.get("user"):
            user_id = uuid.UUID(fields["user"])
        if user_id is None and book_id:  # e.g. a book resumed after a restart, outside the request
            user_id = (await s.execute(select(Book.user_id).where(Book.id == book_id))).scalar_one_or_none()
        s.add(Activity(user_id=user_id, book_id=book_id, level=level, step=step_name, event=event[:32],
                       fields=fields or None))
        await s.commit()


# --- creating a book ------------------------------------------------------------------------------

async def create_book(ref: str, *, gender: str, child_name: str, details: list, provider: str,
                      model: str | None, quality: str | None, user_id=None, story_key: str = DEFAULT_STORY.stem) -> None:
    """The row exists from the first moment of the request, so every ref can be looked up."""
    story = story_for(story_key)
    story_id = await bible.ensure_story(story) if story.key == story_key else None  # None: an unknown story, refused
    async with session() as s:
        s.add(Book(id=ref, user_id=user_id, story_key=story_key, story_id=story_id, style_key=story.style,
                   prompt_version=prompt_version(story), gender=gender[:8], child_name=child_name, details=details,
                   provider=provider, model=model, quality=quality, page_size=None))
        await s.commit()


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
    img = Image.open(io.BytesIO(photo.full_png))
    async with session() as s:
        story = story_for((await s.get(Book, ref)).story_key)
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
    """Draw one image, up to MAX_TRIES times, a short pause apart. Returns PNG bytes, or raises the last
    error. Never more than MAX_TRIES calls: this is the only loop around the image service."""
    for attempt in range(1, MAX_TRIES + 1):
        try:
            return await _draw_once(ref, key, provider, prompt, refs, call, attempt)
        except Exception as e:
            code, _ = friendly_error(e)
            await record("WARNING", f"{key[0]} {key[1]}", "try failed", attempt=attempt, error=code)
            if attempt == MAX_TRIES:
                raise
            await asyncio.sleep(RETRY_PAUSE)


async def _draw_once(ref, key, provider, prompt, refs, call, attempt):
    """One try, saving drawing / done / failed on the image's row as it goes."""
    await _set_image(ref, key, status="drawing", attempts=attempt, started_at=utcnow(), finished_at=None, prompt=prompt,
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


def _context(book, hero_png, provider, sheets=None):
    story = story_for(book.story_key)
    casting = Casting(story, book.gender, display_name(book.child_name) or None)  # the story text says their name
    prompts = PromptBuilder(get_style(story.style), story, Casting(story, book.gender))  # prompts say "Jack"
    child = ChildInfo(display_name(book.child_name), [tuple(d) for d in book.details])
    return story, BookContext(casting, prompts, provider, CastSheets(hero_png, sheets), child)


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

    # The story's characters come from the character bible; any not drawn yet are drawn alongside the
    # child's cartoon, so a brand-new story costs no extra waiting.
    story, ctx = _context(book, b"", provider)
    cast_task = asyncio.create_task(bible.sheets_for(story, ctx.prompts, provider))
    cast_task.add_done_callback(lambda t: t.cancelled() or t.exception())  # if the cartoon fails first, no warning

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
        prompt = ctx.prompts.hero_sheet(description)
        hero_png = await _draw(ref, HERO, provider, prompt, ["photo"],
                               lambda: provider.edit("hero sheet", [("photo.png", photo.full_png)], prompt, SHEET_SIZE))

    story, ctx = _context(book, hero_png, provider, await cast_task)
    pages = [make_page(spec) for spec in story.pages]
    # Only pages this book has rows for: books made before pages were added keep their own pages.
    todo = [p for p in pages if p.needs_image and ("page", p.spec.number) in rows
            and rows[("page", p.spec.number)].status != "done"]
    # A few pages at a time; each picture waits its turn (shown as "waiting" on its progress bar).
    gate = asyncio.Semaphore(IMAGE_CONCURRENCY)

    async def draw_page(p):
        async with gate:
            return await _draw(ref, ("page", p.spec.number), provider, p.prompt(ctx), list(p.spec.cast),
                               lambda: p.draw(ctx))

    outcomes = await asyncio.gather(*(draw_page(p) for p in todo), return_exceptions=True)
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
    story = story_for(book.story_key)
    casting = Casting(story, book.gender, display_name(book.child_name) or None)
    texts = {spec.number: casting.fill(spec.text) for spec in story.pages}
    lines = {spec.number: spec.progress for spec in story.pages}  # the witty line while it's drawn
    etas = {}
    images = []
    for i in sorted(book.images, key=lambda i: (i.kind != "hero_sheet", i.page_number)):
        if i.kind not in etas:
            etas[i.kind] = await eta_seconds(i.kind, book.provider, book.model)
        images.append({
            "kind": i.kind, "page": i.page_number, "status": i.status,
            "label": "Your cartoon" if i.kind == "hero_sheet" else f"Page {i.page_number}",
            "progress": story.site.get("hero_progress", "") if i.kind == "hero_sheet" else lines.get(i.page_number, ""),
            "text": texts.get(i.page_number, ""),
            "started_at": _iso(i.started_at), "finished_at": _iso(i.finished_at),
            "eta_seconds": etas[i.kind], "error": i.error_message, "attempt": i.attempts or 1,
            "image_url": f"/api/books/{ref}/images/{i.kind}-{i.page_number}" if i.status == "done" else None,
        })
    result = {"id": book.id, "status": book.status, "hero": casting.hero_name, "error": book.error_message, "refused_reason": book.refused_reason,
              "server_time": _iso(utcnow()), "images": images,
              "pdf_url": f"/api/books/{ref}/pdf" if book.status == "done" else None}
    if book.status == "done":
        result["book"] = _flipbook(book, story, casting)
    return result


def _flipbook(book, story, casting) -> dict:
    """What the on-site flip book shows: the same pages and text as the PDF, plus a cover."""
    drawn = {i.page_number for i in book.images if i.kind == "page" and i.status == "done"}
    pages = []
    for spec in story.pages:
        if make_page(spec).needs_image:
            if spec.number not in drawn:
                continue  # a page added to the story after this book was made
            pages.append({"kind": "illustrated", "number": spec.number, "text": casting.fill(spec.text),
                          "text_zone": spec.text_zone, "image_url": f"/api/books/{book.id}/images/page-{spec.number}"})
        else:
            pages.append({"kind": spec.type, "number": spec.number})
    return {"title": story.title, "hero": casting.story_hero, "child_name": display_name(book.child_name),
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
    story, ctx = _context(book, to_jpeg(rows[HERO].image), get_provider("mock"))
    pages = []
    for spec in story.pages:
        page = make_page(spec)
        if page.needs_image and (("page", spec.number) not in rows or rows[("page", spec.number)].status != "done"):
            continue  # a page added to the story after this book was made
        image = to_jpeg(rows[("page", spec.number)].image) if page.needs_image else None
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
