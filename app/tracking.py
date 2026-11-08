"""What visitors look at and click (static/track.js sends it here), and the admin's Funnel tab built from it.

Privacy: no cookies; a random visitor ID the browser keeps; no IP; never what anyone typed or the child's
name or photo; nothing at all from browsers that ask not to be tracked (Do Not Track, Global Privacy
Control). Events are deleted after 90 days. Money and books themselves are in their own tables already.
"""
import json
import re
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import delete, func, select

from . import auth
from .admin import require_admin
from .db.models import Book, PageEvent, User
from .db.session import session

KEEP_DAYS = 90
router = APIRouter()

# The only events and properties accepted; anything else is dropped.
EVENTS = {"page_view", "click", "rage_click", "photo_added", "book_requested", "book_refused", "no_money",
          "book_ready", "book_failed", "reached_end", "review_opened", "review_sent", "checkout_started",
          "money_added", "card_refund", "book_refund_asked"}
PROPS = {"target", "source", "reason", "fresh", "cents", "story", "ref"}
ID = re.compile(r"^[a-z0-9]{8,24}$")
BOTS = re.compile(r"bot|crawl|spider|slurp|headless|preview|lighthouse|pingdom|monitor", re.I)

# The book funnel: each step counts visitors who did it after the step before.
BOOK_STEPS = [
    ("Came to the site", lambda e: e.name == "page_view"),
    ("Opened a story", lambda e: e.name == "page_view" and e.path.startswith("/stories/")),
    ("Added a photo", lambda e: e.name == "photo_added"),
    ("Pressed Generate", lambda e: e.name == "book_requested"),
    ("Got their book", lambda e: e.name == "book_ready" and (e.props or {}).get("fresh") == "1"),
    ("Read to the end", lambda e: e.name == "reached_end"),
    ("Downloaded the PDF", lambda e: e.name == "click" and (e.props or {}).get("target") == "download"),
    ("Left a review", lambda e: e.name == "review_sent"),
]
WALLET_STEPS = [
    ("Opened the wallet", lambda e: e.name == "page_view" and e.path == "/wallet"),
    ("Went to pay", lambda e: e.name == "checkout_started"),
    ("Money added", lambda e: e.name == "money_added"),
]


def _clean_props(raw) -> dict | None:
    if not isinstance(raw, dict):
        return None
    out = {k: str(v)[:64] for k, v in raw.items() if k in PROPS and v is not None}
    return out or None


@router.post("/api/e", status_code=204)
async def collect(request: Request):
    """One event from the page. Always 204, so a broken event never shows the visitor an error."""
    if request.headers.get("sec-gpc") == "1" or request.headers.get("dnt") == "1" \
            or BOTS.search(request.headers.get("user-agent", "")):
        return Response(status_code=204)
    body = await request.body()
    if len(body) > 2048:
        return Response(status_code=204)
    try:
        data = json.loads(body)
    except ValueError:
        return Response(status_code=204)
    name, visitor, sess = data.get("name"), str(data.get("visitor", "")), str(data.get("session", ""))
    if name not in EVENTS or not ID.match(visitor) or not ID.match(sess):
        return Response(status_code=204)
    path = str(data.get("path", "/")).split("?")[0].split("#")[0][:128] or "/"
    user = await auth.current_user(request)
    async with session() as s:
        s.add(PageEvent(visitor=visitor, session=sess, user_id=user.id if user else None, name=name, path=path,
                        props=_clean_props(data.get("props"))))
        await s.commit()
    return Response(status_code=204)


async def forget_old() -> None:
    async with session() as s:
        await s.execute(delete(PageEvent).where(PageEvent.at < datetime.now(timezone.utc) - timedelta(days=KEEP_DAYS)))
        await s.commit()


def _funnel(by_visitor: dict, steps) -> list[dict]:
    counts = [0] * len(steps)
    for events in by_visitor.values():
        after = None
        for i, (_, test) in enumerate(steps):
            hit = next((e for e in events if test(e) and (after is None or e.at >= after)), None)
            if hit is None:
                break
            counts[i] += 1
            after = hit.at
    out = []
    for i, (label, _) in enumerate(steps):
        prev = counts[i - 1] if i else None
        out.append({"step": label, "visitors": counts[i],
                    "of_previous": round(counts[i] / prev, 3) if prev else None,
                    "of_first": round(counts[i] / counts[0], 3) if counts[0] else None})
    return out


def _utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt  # SQLite hands back naive times


def _pct(values, q):
    if not values:
        return None
    values = sorted(values)
    return round(values[min(len(values) - 1, int(q * len(values)))], 1)


@router.get("/admin/api/funnel")
async def funnel(days: int = 7, _=Depends(require_admin)):
    await forget_old()
    since = datetime.now(timezone.utc) - timedelta(days=max(1, min(days, KEEP_DAYS)))
    admins = auth.admin_emails()
    async with session() as s:
        admin_ids = set((await s.execute(select(User.id).where(func.lower(User.email).in_(admins)))).scalars()) \
            if admins else set()
        events = (await s.execute(select(PageEvent).where(PageEvent.at >= since)
                                  .order_by(PageEvent.at, PageEvent.id).limit(200_000))).scalars().all()
        drawn = (await s.execute(select(Book.started_at, Book.finished_at).where(
            Book.status == "done", Book.created_at >= since, Book.started_at.is_not(None)))).all()
        per_user = (await s.execute(select(Book.user_id, func.count()).where(Book.status == "done",
                                    Book.user_id.is_not(None)).group_by(Book.user_id))).all()

    # Anyone who was ever signed in as an admin is left out: it's your own testing.
    admin_visitors = {e.visitor for e in events if e.user_id in admin_ids}
    events = [e for e in events if e.visitor not in admin_visitors]
    by_visitor = defaultdict(list)
    for e in events:
        by_visitor[e.visitor].append(e)

    pages, page_people = Counter(), defaultdict(set)
    clicks, click_people, rage = Counter(), defaultdict(set), Counter()
    blocked = Counter()
    for e in events:
        p = e.props or {}
        if e.name == "page_view":
            pages[e.path] += 1
            page_people[e.path].add(e.visitor)
        elif e.name == "click":
            clicks[p.get("target", "?")] += 1
            click_people[p.get("target", "?")].add(e.visitor)
        elif e.name == "rage_click":
            rage[(p.get("target", "?"), e.path)] += 1
        elif e.name == "no_money":
            blocked["Not enough money for a book"] += 1
        elif e.name == "book_refused":
            blocked[f"Book refused: {p.get('reason', '?')}"] += 1
        elif e.name == "book_failed":
            blocked["Book failed while drawing"] += 1

    # People per day (UTC). A person is one browser's visitor ID, signed in or not; a visit ends after 30 minutes
    # with nothing happening (static/track.js). A refresh adds neither. "New" is the first day we saw them.
    async with session() as s:
        first_seen = {v: _utc(at) for v, at in (await s.execute(select(PageEvent.visitor, func.min(PageEvent.at))
                                                                   .group_by(PageEvent.visitor))).all()}
    per_day = defaultdict(lambda: {"people": set(), "new": set(), "signed_in": set(), "visits": set()})
    for e in events:
        at = _utc(e.at)
        d = per_day[at.date().isoformat()]
        d["people"].add(e.visitor)
        d["visits"].add(e.session)
        if e.user_id:
            d["signed_in"].add(e.visitor)
        if first_seen.get(e.visitor) and first_seen[e.visitor].date() == at.date():
            d["new"].add(e.visitor)
    days_out = [{"day": k, **{f: len(v[f]) for f in ("people", "new", "signed_in", "visits")}}
                for k, v in sorted(per_day.items(), reverse=True)]
    signed_in = len({e.visitor for e in events if e.user_id})

    to_first_book = []
    for evs in by_visitor.values():
        ready = next((e for e in evs if e.name == "book_ready" and (e.props or {}).get("fresh") == "1"), None)
        if ready:
            to_first_book.append((ready.at - evs[0].at).total_seconds() / 60)
    seconds = [(f - s_).total_seconds() for s_, f in drawn if f]
    makers = [n for uid, n in per_user if uid not in admin_ids]

    return {
        "visitors": len(by_visitor), "sessions": len({e.session for e in events}), "signed_in": signed_in,
        "new_visitors": sum(1 for v in by_visitor if first_seen.get(v) and first_seen[v] >= since),
        "days": days_out,
        "book_funnel": _funnel(by_visitor, BOOK_STEPS), "wallet_funnel": _funnel(by_visitor, WALLET_STEPS),
        "blocked": [{"what": k, "times": v} for k, v in blocked.most_common()],
        "pages": [{"path": k, "views": v, "visitors": len(page_people[k])} for k, v in pages.most_common(20)],
        "clicks": [{"target": k, "clicks": v, "visitors": len(click_people[k])} for k, v in clicks.most_common(25)],
        "rage_clicks": [{"target": t, "path": path, "times": v} for (t, path), v in rage.most_common(10)],
        "minutes_to_first_book": {"median": round(statistics.median(to_first_book), 1) if to_first_book else None,
                                  "count": len(to_first_book)},
        "drawing_seconds": {"p50": _pct(seconds, 0.5), "p95": _pct(seconds, 0.95), "books": len(seconds)},
        "second_book": {"makers": len(makers), "again": sum(n >= 2 for n in makers)},
        "keep_days": KEEP_DAYS,
    }
