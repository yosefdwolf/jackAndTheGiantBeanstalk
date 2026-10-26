"""Step-by-step logging for post-mortems. Every line carries the book's ID.

A step logs when it starts, not only when it ends, so a stuck call shows up as a `start` with no
`done`. Never log the password, the API key, the photo, or the child's name and details.
"""
import contextvars
import logging
import sys
import time
import uuid
from contextlib import asynccontextmanager

_book_id = contextvars.ContextVar("book_id", default="-")
_cost = contextvars.ContextVar("book_cost", default=None)

log = logging.getLogger("book")


class _BookIdFilter(logging.Filter):
    def filter(self, record):
        record.book_id = _book_id.get()
        return True


def setup_logging(level: str = "INFO") -> None:
    if log.handlers:
        return
    handler = logging.StreamHandler(sys.stdout)  # the host (Railway) collects stdout
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s book=%(book_id)s %(message)s"))
    handler.addFilter(_BookIdFilter())
    log.addHandler(handler)
    log.setLevel(level)
    log.propagate = True  # lets tests capture records


def start_book() -> str:
    """Give the current request a short book ID and a fresh cost tally. Returns the ID."""
    book_id = uuid.uuid4().hex[:8]
    _book_id.set(book_id)
    _cost.set([0.0])
    return book_id


def add_cost(dollars: float) -> None:
    tally = _cost.get()
    if tally is not None:
        tally[0] += dollars


def total_cost() -> float:
    tally = _cost.get()
    return tally[0] if tally else 0.0


def fields(**kv) -> str:
    return " ".join(f"{k}={v}" for k, v in kv.items() if v not in (None, ""))


@asynccontextmanager
async def step(name: str, **kv):
    """Log `start <name>`, then `done <name> Ns` or `failed <name> Ns ErrorType`."""
    log.info("start %s %s", name, fields(**kv))
    t0 = time.perf_counter()
    try:
        yield
    except Exception as e:
        log.error("failed %s %.1fs %s %s", name, time.perf_counter() - t0, type(e).__name__,
                  fields(code=getattr(e, "code", None), openai_request=getattr(e, "request_id", None)))
        raise
    log.info("done %s %.1fs", name, time.perf_counter() - t0)
