"""Step-by-step logging for post-mortems. Every line carries the request's ref.

A step logs when it starts, not only when it ends, so a stuck call shows up as a `start` with no
`done`. Steps inside a book are also saved to the `book_events` table (see set_event_sink).
Never log the password, the API key, the photo, or the child's name and details.
"""
import contextvars
import logging
import sys
import time
import uuid
from contextlib import asynccontextmanager

_ref = contextvars.ContextVar("ref", default="-")
_in_book = contextvars.ContextVar("in_book", default=False)
_cost = contextvars.ContextVar("book_cost", default=None)
_user = contextvars.ContextVar("user_id", default=None)
_sink = None  # async fn(book_id, level, step, event, duration_ms, fields) -> None
_activity_sink = None  # async fn(user_id, book_id, level, step, event, fields) -> None
# Inside a book only these steps are activity; the rest (each picture's tries and costs) is the book's trail.
BOOK_MILESTONES = {"book", "request", "wallet", "review"}

log = logging.getLogger("book")


class _RefFilter(logging.Filter):
    def filter(self, record):
        record.book_id = _ref.get()
        return True


def setup_logging(level: str = "INFO") -> None:
    if log.handlers:
        return
    handler = logging.StreamHandler(sys.stdout)  # the host (Railway) collects stdout
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s book=%(book_id)s %(message)s"))
    handler.addFilter(_RefFilter())
    log.addHandler(handler)
    log.setLevel(level)
    log.propagate = True  # lets tests capture records


def new_ref() -> str:
    return uuid.uuid4().hex[:8]


def set_ref(ref: str) -> None:
    _ref.set(ref)


def current_ref() -> str:
    return _ref.get()


def start_book(ref: str | None = None) -> str:
    """Mark the current task as working on a book (its events go to the DB) with a fresh cost tally."""
    ref = ref or _ref.get()
    if ref == "-":
        ref = new_ref()
    _ref.set(ref)
    _in_book.set(True)
    _cost.set([0.0])
    return ref


def set_event_sink(fn) -> None:
    global _sink
    _sink = fn


def set_activity_sink(fn) -> None:
    global _activity_sink
    _activity_sink = fn


def set_user(user_id) -> None:
    """Who this request is for, so activity rows say who did it."""
    _user.set(user_id)


def add_cost(dollars: float) -> None:
    tally = _cost.get()
    if tally is not None:
        tally[0] += dollars


def total_cost() -> float:
    tally = _cost.get()
    return tally[0] if tally else 0.0


def fields(**kv) -> str:
    return " ".join(f"{k}={v}" for k, v in kv.items() if v not in (None, ""))


async def record(level: str, step: str, event: str, duration_ms: int | None = None, **kv) -> None:
    """Log a line, save it to book_events inside a book, and to activity when it's something a person did.
    Never raises: logging can't break a book."""
    log.log(getattr(logging, level), "%s %s %s", event, step, fields(**kv))
    saved = {k: str(v) for k, v in kv.items() if v not in (None, "")}
    in_book = _in_book.get()
    if _sink and in_book:
        try:
            await _sink(_ref.get(), level, step, event, duration_ms, saved)
        except Exception:
            log.exception("could not save event %s %s", event, step)
    if _activity_sink and (not in_book or step in BOOK_MILESTONES):
        try:
            book = _ref.get() if in_book else saved.get("book")
            await _activity_sink(_user.get(), book if book != "-" else None, level, step, event, saved)
        except Exception:
            log.exception("could not save activity %s %s", event, step)


@asynccontextmanager
async def step(name: str, **kv):
    """Record `start <name>`, then `done <name>` or `failed <name>`, with the duration."""
    await record("INFO", name, "start", **kv)
    t0 = time.perf_counter()
    try:
        yield
    except Exception as e:
        ms = int((time.perf_counter() - t0) * 1000)
        await record("ERROR", name, "failed", ms, seconds=f"{ms / 1000:.1f}", error=type(e).__name__,
                     code=getattr(e, "code", None), provider_request=getattr(e, "request_id", None))
        raise
    ms = int((time.perf_counter() - t0) * 1000)
    await record("INFO", name, "done", ms, seconds=f"{ms / 1000:.1f}")
