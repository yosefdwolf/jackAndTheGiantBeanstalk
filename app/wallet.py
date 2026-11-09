"""The wallet: add money with Stripe (test mode), pay $0.99 per book, and get money back.

Two kinds of money back:
- Unspent money goes straight back to the card it came from, with no review: it was never used.
- A book that came out wrong can be asked about. The admin looks at it, and if approved, the book's
  price goes back into the wallet (not the card). Reviewed, because otherwise anyone could ask for
  every book back and get them free.

Money is kept in cents. Every change to a balance is one row in `transactions` (what caused it is
on the row), so the balance is their sum and the history page is those rows.

Adding money uses Stripe Checkout: we open a session, the person pays on Stripe's page, and when
they come back we ask Stripe whether it was paid before crediting it (once, whatever happens).
Open sessions are checked again whenever the wallet loads, so closing the tab after paying is fine.
"""
import os

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from . import auth, notify
from .book.log import current_ref, record
from .db.models import Book, Payment, RefundRequest, Transaction, User, now
from .db.session import session

BOOK_PRICE_CENTS = int(os.getenv("BOOK_PRICE_CENTS", "99"))
TOP_UPS = (100, 500, 1000, 2000)  # the buttons, in cents; any amount in between also works
MIN_TOP_UP, MAX_TOP_UP = 100, 10000  # $1 to $100
STRIPE = "https://api.stripe.com/v1"

router = APIRouter()


class StripeError(Exception):
    pass


async def stripe(method: str, path: str, data: dict | None = None) -> dict:
    """One call to Stripe. The key comes from STRIPE_SECRET_KEY and only test keys are accepted."""
    key = os.getenv("STRIPE_SECRET_KEY", "")
    if not key.startswith("sk_test_"):
        raise StripeError("Payments aren't set up (STRIPE_SECRET_KEY must be a test key).")
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.request(method, STRIPE + path, data=data, auth=(key, ""))
    body = r.json()
    if r.status_code >= 400:
        raise StripeError(body.get("error", {}).get("message", f"Stripe said {r.status_code}"))
    return body


def dollars(cents: int) -> str:
    return f"{'-' if cents < 0 else ''}${abs(cents) / 100:.2f}"


# --- balances ------------------------------------------------------------------------------------

async def balance(s, user_id) -> int:
    return (await s.execute(select(func.coalesce(func.sum(Transaction.amount_cents), 0))
                            .where(Transaction.user_id == user_id))).scalar_one()


async def refundable_to_card(s, user_id) -> int:
    """What Stripe can still send back: paid top-ups minus what's already been refunded. (A book refund
    adds to the balance but not to this, since it never came from a card.)"""
    return (await s.execute(select(func.coalesce(func.sum(Payment.amount_cents - Payment.refunded_cents), 0))
                            .where(Payment.user_id == user_id, Payment.status == "paid"))).scalar_one()


async def lock(s, user_id):
    """One wallet change at a time per person, so two books can't both spend the last 99¢."""
    await s.execute(select(User.id).where(User.id == user_id).with_for_update())


async def is_free(user: User) -> bool:
    return await auth.has_unlimited(user)  # admins and the unlimited list


async def can_afford_a_book(user: User) -> bool:
    if await is_free(user):
        return True
    async with session() as s:
        return await balance(s, user.id) >= BOOK_PRICE_CENTS


async def charge_for_book(user: User, ref: str) -> bool:
    """Takes $0.99 for a book that's about to be drawn. False if there isn't enough."""
    if await is_free(user):
        return True
    async with session() as s:
        await lock(s, user.id)
        if await balance(s, user.id) < BOOK_PRICE_CENTS:
            return False
        s.add(Transaction(user_id=user.id, amount_cents=-BOOK_PRICE_CENTS, kind="book", book_id=ref))
        await s.commit()
    await record("INFO", "wallet", "charged", book=ref, cents=BOOK_PRICE_CENTS)
    return True


COST_SAMPLE = 20  # recent books the average cost to make one is taken over


async def cost_per_book() -> dict:
    """What making a book costs us in API calls, on average over the last COST_SAMPLE finished books drawn by a
    real image model: every picture and every retry, the picture checks and the face description (Book.total_cost).
    Shown in admin's Money panel beside the price."""
    async with session() as s:
        costs = (await s.execute(select(Book.total_cost).where(Book.status == "done", Book.provider != "mock",
                                                               Book.total_cost > 0)
                                 .order_by(Book.finished_at.desc()).limit(COST_SAMPLE))).scalars().all()
    if not costs:
        return {"average": None, "books": 0}
    return {"average": round(sum(float(c) for c in costs) / len(costs), 3), "books": len(costs)}


def no_money_message() -> str:
    return f"A book costs {dollars(BOOK_PRICE_CENTS)}. Add money to your wallet to make one."


# --- adding money --------------------------------------------------------------------------------

async def settle(payment_id: str) -> None:
    """Ask Stripe whether a checkout was paid, and credit it once if so."""
    session_ = await stripe("GET", f"/checkout/sessions/{payment_id}")
    async with session() as s:
        p = await s.get(Payment, payment_id, with_for_update=True)
        if p is None or p.status != "open":
            return
        if session_.get("payment_status") == "paid":
            p.status, p.payment_intent, p.paid_at = "paid", session_.get("payment_intent"), now()
            s.add(Transaction(user_id=p.user_id, amount_cents=p.amount_cents, kind="deposit", payment_id=p.id,
                              note="Added with a card"))
            await s.commit()
            await record("INFO", "wallet", "paid", payment=p.id[-8:], cents=p.amount_cents)
        elif session_.get("status") == "expired":
            p.status = "expired"
            await s.commit()


async def settle_open(user_id) -> None:
    async with session() as s:
        open_ids = (await s.execute(select(Payment.id).where(Payment.user_id == user_id,
                                                             Payment.status == "open"))).scalars().all()
    for pid in open_ids:
        try:
            await settle(pid)
        except StripeError as e:
            await record("WARNING", "wallet", "check failed", payment=pid[-8:], error=str(e))


def _site(request: Request) -> str:
    """This site's address as the browser sees it (Railway sits behind a proxy that speaks https)."""
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    return f"{proto}://{request.headers.get('host', request.url.netloc)}"


async def _signed_in(request: Request) -> User:
    user = await auth.current_user(request)
    if user is None:
        raise HTTPException(401, {"message": "Please sign in first.", "ref": current_ref(), "reason": "not_signed_in"})
    return user


class TopUpIn(BaseModel):
    cents: int


@router.post("/api/wallet/checkout")
async def checkout(request: Request, body: TopUpIn):
    """Opens a Stripe Checkout page for $1 to $100. The page sends the browser there."""
    user = await _signed_in(request)
    if not MIN_TOP_UP <= body.cents <= MAX_TOP_UP:
        raise HTTPException(400, {"message": f"Add between {dollars(MIN_TOP_UP)} and {dollars(MAX_TOP_UP)}.",
                                  "ref": current_ref(), "reason": "bad_amount"})
    site = _site(request)
    try:
        cs = await stripe("POST", "/checkout/sessions", {
            "mode": "payment",
            "line_items[0][quantity]": 1,
            "line_items[0][price_data][currency]": "usd",
            "line_items[0][price_data][unit_amount]": body.cents,
            "line_items[0][price_data][product_data][name]": "Picture book wallet",
            "customer_email": user.email,
            "client_reference_id": str(user.id),
            "metadata[user_id]": str(user.id),
            "success_url": f"{site}/wallet?paid={{CHECKOUT_SESSION_ID}}",
            "cancel_url": f"{site}/wallet",
        })
    except StripeError as e:
        await record("ERROR", "wallet", "checkout failed", error=str(e))
        raise HTTPException(502, {"message": f"Couldn't open the payment page: {e}", "ref": current_ref()})
    async with session() as s:
        s.add(Payment(id=cs["id"], user_id=user.id, amount_cents=body.cents))
        await s.commit()
    await record("INFO", "wallet", "checkout opened", cents=body.cents)
    return {"url": cs["url"]}


# --- what the wallet page shows ------------------------------------------------------------------

KIND_LABELS = {"deposit": "Added money", "book": "Book", "refund": "Back to your card",
               "book_refund": "Book refunded to your wallet"}


def _tx_out(t: Transaction) -> dict:
    return {"id": t.id, "at": t.created_at.isoformat(), "cents": t.amount_cents, "kind": t.kind,
            "label": KIND_LABELS.get(t.kind, t.kind), "book_id": t.book_id, "note": t.note}


def _request_out(r: RefundRequest) -> dict:
    return {"id": r.id, "book_id": r.book_id, "cents": r.amount_cents, "reason": r.reason,
            "status": r.status, "admin_note": r.admin_note, "at": r.created_at.isoformat(),
            "decided_at": r.decided_at.isoformat() if r.decided_at else None}


@router.get("/api/wallet")
async def wallet(request: Request, paid: str | None = None):
    user = await _signed_in(request)
    if paid:
        try:
            await settle(paid)
        except StripeError as e:
            await record("WARNING", "wallet", "check failed", error=str(e))
    await settle_open(user.id)
    async with session() as s:
        bal, card = await balance(s, user.id), await refundable_to_card(s, user.id)
        txs = (await s.execute(select(Transaction).where(Transaction.user_id == user.id)
                               .order_by(Transaction.created_at.desc(), Transaction.id.desc()))).scalars().all()
        reqs = (await s.execute(select(RefundRequest).where(RefundRequest.user_id == user.id)
                                .order_by(RefundRequest.created_at.desc()))).scalars().all()
        asked = {r.book_id for r in reqs if r.status in ("pending", "approved")}
        paid_for = [t.book_id for t in txs if t.kind == "book" and t.book_id not in asked]
        books = (await s.execute(select(Book.id, Book.child_name, Book.created_at)
                                 .where(Book.id.in_(paid_for)))).all() if paid_for else []
    return {"balance_cents": bal, "refundable_cents": max(0, min(bal, card)), "price_cents": BOOK_PRICE_CENTS,
            "top_ups": TOP_UPS, "min_top_up": MIN_TOP_UP, "max_top_up": MAX_TOP_UP, "free": await is_free(user),
            "transactions": [_tx_out(t) for t in txs], "refund_requests": [_request_out(r) for r in reqs],
            "books_to_ask_about": [{"id": b.id, "name": b.child_name, "at": b.created_at.isoformat()}
                                   for b in sorted(books, key=lambda b: b.created_at, reverse=True)]}


# --- unspent money back to the card: straight away, no review --------------------------------------

class CardRefundIn(BaseModel):
    cents: int = Field(ge=1)


@router.post("/api/wallet/refund")
async def refund_to_card(request: Request, body: CardRefundIn):
    """Sends unspent money back through Stripe, across their top-ups newest first. Each Stripe refund
    is its own row in the history. Only what Stripe actually sent comes off the balance."""
    user = await _signed_in(request)
    async with session() as s:
        await lock(s, user.id)
        limit = min(await balance(s, user.id), await refundable_to_card(s, user.id))
        if body.cents > limit:
            raise HTTPException(400, {"message": f"You can get up to {dollars(max(0, limit))} back.",
                                      "ref": current_ref(), "reason": "too_much"})
        sent, problem = 0, None
        payments = (await s.execute(select(Payment).where(Payment.user_id == user.id, Payment.status == "paid")
                                    .order_by(Payment.paid_at.desc()))).scalars().all()
        for p in payments:
            take = min(body.cents - sent, p.amount_cents - p.refunded_cents)
            if take <= 0:
                continue
            try:
                refund = await stripe("POST", "/refunds", {"payment_intent": p.payment_intent, "amount": take})
            except StripeError as e:
                problem = str(e)
                break
            p.refunded_cents += take
            s.add(Transaction(user_id=user.id, amount_cents=-take, kind="refund", stripe_refund_id=refund["id"]))
            sent += take
            if sent == body.cents:
                break
        await s.commit()
    await record("INFO" if not problem else "ERROR", "wallet", "refunded to card", cents=sent, asked=body.cents,
                 error=problem)
    if problem and not sent:
        raise HTTPException(502, {"message": f"Stripe couldn't send it back: {problem}", "ref": current_ref()})
    return {"sent_cents": sent, "problem": problem}


# --- a book that came out wrong: the admin decides -----------------------------------------------

class BookRefundIn(BaseModel):
    book_id: str = Field(max_length=16)
    reason: str = Field(max_length=1000)


@router.post("/api/wallet/book-refunds", status_code=201)
async def ask_about_a_book(request: Request, body: BookRefundIn):
    user = await _signed_in(request)
    if not body.reason.strip():
        raise HTTPException(422, {"message": "Please say what went wrong with the book.", "ref": current_ref(),
                                  "reason": "missing_reason"})
    async with session() as s:
        await lock(s, user.id)
        charge = (await s.execute(select(Transaction).where(Transaction.user_id == user.id, Transaction.kind == "book",
                                                            Transaction.book_id == body.book_id))).scalars().first()
        asked = (await s.execute(select(RefundRequest.id).where(
            RefundRequest.book_id == body.book_id, RefundRequest.status.in_(("pending", "approved"))))).first()
        if charge is None or asked is not None:
            raise HTTPException(400, {"message": "That book can't be asked about (it wasn't paid for, or it already "
                                                 "has been).", "ref": current_ref(), "reason": "not_refundable"})
        r = RefundRequest(user_id=user.id, book_id=body.book_id, amount_cents=-charge.amount_cents,
                          reason=body.reason.strip())
        s.add(r)
        await s.commit()
    await record("INFO", "wallet", "book refund asked", book=r.book_id, request=r.id)
    await notify.send_admins(
        f"Book refund request: {user.email}, book {r.book_id}",
        f"{user.name or user.email} ({user.email}) says book {r.book_id} came out wrong and asks for its "
        f"{dollars(r.amount_cents)} back in their wallet.\n\nWhat they said:\n{r.reason}\n\n"
        f"Look at the book and approve or deny it in the admin site, Refunds tab.")
    return {"request": _request_out(r)}


async def decide(request_id: int, approve: bool, admin: User, note: str | None) -> RefundRequest:
    """The admin approves or denies a book refund. Approved: the book's price goes back in their wallet."""
    async with session() as s:
        r = await s.get(RefundRequest, request_id, with_for_update=True)
        if r is None:
            raise HTTPException(404, {"message": "No such refund request.", "ref": current_ref()})
        if r.status != "pending":
            raise HTTPException(409, {"message": f"That request is already {r.status}.", "ref": current_ref()})
        r.decided_at, r.decided_by, r.admin_note = now(), admin.id, (note or "").strip() or None
        r.status = "approved" if approve else "denied"
        if approve:
            s.add(Transaction(user_id=r.user_id, amount_cents=r.amount_cents, kind="book_refund", book_id=r.book_id,
                              refund_request_id=r.id, note=r.admin_note))
        await s.commit()
    await record("INFO", "wallet", f"book refund {r.status}", request=r.id, book=r.book_id)
    return r


async def admin_requests(status: str = "") -> list[dict]:
    async with session() as s:
        q = select(RefundRequest, User.email).join(User, User.id == RefundRequest.user_id)
        if status:
            q = q.where(RefundRequest.status == status)
        rows = (await s.execute(q.order_by(RefundRequest.created_at.desc()))).all()
        out = []
        for r, email in rows:
            out.append({**_request_out(r), "email": email, "balance_cents": await balance(s, r.user_id)})
    return out

