"""Printed books: a finished book as a hardcover, made and shipped by Lulu's Print API.

The reader looks through the PDF and ticks that it's ready (nothing is ordered before that), types a US address,
sees the price, and places the order: the wallet is charged and Lulu gets a print job. LULU_API points at Lulu's
sandbox, where jobs are never printed or shipped. Lulu fetches the two print files (inside pages, wraparound
cover) from signed links on this site, built fresh from the saved pictures (app/book/pdf.py, print_files).

Settings: LULU_CLIENT_KEY and LULU_CLIENT_SECRET (from developers.sandbox.lulu.com), LULU_API, LULU_POD_PACKAGE
(the product: trim, colour, binding, paper), LULU_SHIPPING, PRINT_PROFIT_CENTS, and LULU_CONTACT_EMAIL (who Lulu
writes to about a job; printing stays off without it). PUBLIC_URL is this site's address as Lulu can reach it."""
import math
import os
import re
import time
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select

from . import auth, wallet
from .book import jobs
from .book.log import current_ref, record
from .book.pdf import MIN_PRINT_PAGES
from .book.story import story_for
from .db.models import Book, PrintOrder, Transaction
from .db.session import session

router = APIRouter()

LULU_API = os.getenv("LULU_API", "https://api.sandbox.lulu.com").rstrip("/")
# 11 x 8.5 in landscape, full colour, premium, hardcover casewrap, 80# coated white paper, gloss cover.
POD_PACKAGE = os.getenv("LULU_POD_PACKAGE", "1100X0850.FC.PRE.CW.080CW444.GXX")
SHIPPING = os.getenv("LULU_SHIPPING", "MAIL")  # the cheapest US option for this book (GROUND isn't offered)
# The price: what Lulu charges us for that address (printing, shipping, tax), plus Stripe's fee on the money the
# reader adds (2.9% + 30 cents), plus our profit, rounded up to the next .99.
PROFIT_CENTS = int(os.getenv("PRINT_PROFIT_CENTS", "500"))
STRIPE_RATE, STRIPE_FIXED_CENTS = 0.029, 30
MAX_PRICE_CENTS = wallet.MAX_TOP_UP  # one top-up has to be able to cover it
FILE_LINK_DAYS = 14  # how long Lulu can fetch an order's files (it does so within minutes)
CHECK_EVERY = timedelta(seconds=60)  # how often looking at an order asks Lulu for news
US_STATES = set("AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC "
                "ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY PR".split())


def configured() -> bool:
    return bool(os.getenv("LULU_CLIENT_KEY") and os.getenv("LULU_CLIENT_SECRET") and contact_email())


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# --- Lulu ------------------------------------------------------------------------------------------

class LuluError(Exception):
    pass


class Lulu:
    """The few Print API calls the shop needs. Tests swap in a fake with the same methods."""
    _token: tuple[str, float] | None = None

    async def _auth(self) -> str:
        if self._token and self._token[1] > time.time() + 30:
            return self._token[0]
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.post(f"{LULU_API}/auth/realms/glasstree/protocol/openid-connect/token",
                             data={"grant_type": "client_credentials"},
                             auth=(os.environ["LULU_CLIENT_KEY"], os.environ["LULU_CLIENT_SECRET"]))
        if r.status_code != 200:
            raise LuluError(f"sign-in refused ({r.status_code})")
        body = r.json()
        Lulu._token = (body["access_token"], time.time() + float(body.get("expires_in", 300)))
        return body["access_token"]

    async def _call(self, method: str, path: str, body: dict | None = None) -> dict:
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.request(method, f"{LULU_API}{path}", json=body,
                                headers={"Authorization": f"Bearer {await self._auth()}"})
        if r.status_code >= 400:
            raise LuluError(f"{path} {r.status_code}: {r.text[:500]}")
        return r.json()

    async def quote(self, address: dict, pages: int) -> dict:
        return await self._call("POST", "/print-job-cost-calculations/", {
            "line_items": [{"page_count": pages, "pod_package_id": POD_PACKAGE, "quantity": 1}],
            "shipping_address": address, "shipping_option": SHIPPING})

    async def cover_size(self, pages: int) -> tuple[float, float]:
        d = await self._call("POST", "/cover-dimensions/", {"pod_package_id": POD_PACKAGE,
                                                           "interior_page_count": pages, "unit": "pt"})
        return float(d["width"]), float(d["height"])

    async def create_job(self, order_id: str, title: str, address: dict, interior_url: str, cover_url: str) -> dict:
        return await self._call("POST", "/print-jobs/", {
            "contact_email": contact_email(), "external_id": order_id, "shipping_level": SHIPPING,
            "shipping_address": address,
            "line_items": [{"external_id": order_id, "title": title[:250], "quantity": 1,
                            "printable_normalization": {"pod_package_id": POD_PACKAGE,
                                                        "cover": {"source_url": cover_url},
                                                        "interior": {"source_url": interior_url}}}]})

    async def job(self, job_id: str) -> dict:
        return await self._call("GET", f"/print-jobs/{job_id}/")


lulu = Lulu()


def contact_email() -> str:
    """Who Lulu writes to about a job. Set on purpose (LULU_CONTACT_EMAIL), never taken from the admin list."""
    return os.getenv("LULU_CONTACT_EMAIL", "").strip()


def cents(amount) -> int:
    return int((Decimal(str(amount or "0")) * 100).quantize(Decimal("1")))


# --- addresses -------------------------------------------------------------------------------------

class AddressIn(BaseModel):
    name: str
    street1: str
    street2: str = ""
    city: str
    state_code: str
    postcode: str
    phone_number: str


def clean_address(a: AddressIn) -> dict:
    """Lulu's address shape, US only for now (the one price includes US shipping). A kind note if a part's
    missing or doesn't look right; the street itself is checked by the carrier, not here."""
    fields = {k: " ".join(str(v).split()) for k, v in a.model_dump().items()}
    for key, label in (("name", "the name"), ("street1", "the street"), ("city", "the city"),
                       ("state_code", "the state"), ("postcode", "the ZIP code"), ("phone_number", "a phone number")):
        if not fields[key]:
            raise _bad(f"Please add {label}.", key)
        if len(fields[key]) > 80:
            raise _bad("That's a bit long for an address line.", key)
    fields["state_code"] = fields["state_code"].upper()
    if fields["state_code"] not in US_STATES:
        raise _bad("Please use a US state's two letters, like NY or CA. We ship in the US for now.", "state_code")
    if not re.fullmatch(r"\d{5}(-\d{4})?", fields["postcode"]):
        raise _bad("A US ZIP code is 5 digits, like 10001.", "postcode")
    if len(re.sub(r"\D", "", fields["phone_number"])) < 10:
        raise _bad("The delivery company needs a phone number with the area code.", "phone_number")
    return {**fields, "country_code": "US"}


def _bad(message: str, field: str | None = None) -> HTTPException:
    return HTTPException(422, {"message": message, "ref": current_ref(), "reason": "address",
                               **({"field": field} if field else {})})


# --- the signed file links Lulu downloads from -----------------------------------------------------

def file_link(request: Request, order_id: str, which: str) -> str:
    token = auth.sign({"o": order_id, "f": which, "exp": int(time.time()) + FILE_LINK_DAYS * 86400})
    base = os.getenv("PUBLIC_URL") or wallet._site(request)  # https behind Railway's proxy
    return f"{base.rstrip('/')}/print-files/{token}/{which}.pdf"


@router.get("/print-files/{token}/{name}.pdf")
async def print_file(token: str, name: str):
    """For Lulu: an order's inside pages or cover. Only a link this site signed works, and only for a while."""
    data = auth.unsign(token)
    if not data or data.get("f") != name or name not in ("interior", "cover") or data.get("exp", 0) < time.time():
        raise HTTPException(404, "No such file.")
    async with session() as s:
        order = await s.get(PrintOrder, data["o"])
    if order is None:
        raise HTTPException(404, "No such file.")
    size = await lulu.cover_size(MIN_PRINT_PAGES) if name == "cover" and configured() else None
    files = await jobs.print_pdfs(order.book_id, size)
    if files is None:
        raise HTTPException(404, "No such file.")
    await record("INFO", "print", "file fetched", order=order.id, file=name)
    return Response(files[0 if name == "interior" else 1], media_type="application/pdf")


# --- the shop --------------------------------------------------------------------------------------

async def _signed_in(request: Request):
    user = await auth.current_user(request)
    if user is None:
        raise HTTPException(401, {"message": "Please sign in first.", "ref": current_ref(), "reason": "not_signed_in"})
    return user


async def _own_book(user, ref: str) -> Book:
    async with session() as s:
        book = await s.get(Book, ref)
    if book is None or (book.user_id != user.id and not auth.is_admin(user)):
        raise HTTPException(404, {"message": "No book of yours with that reference.", "ref": current_ref()})
    if book.status != "done":
        raise HTTPException(409, {"message": "That book isn't finished yet.", "ref": current_ref()})
    return book


async def _own_order(user, order_id: str) -> PrintOrder:
    async with session() as s:
        order = await s.get(PrintOrder, order_id)
    if order is None or (order.user_id != user.id and not auth.is_admin(user)):
        raise HTTPException(404, {"message": "No order of yours with that reference.", "ref": current_ref()})
    return order


def order_out(o: PrintOrder) -> dict:
    a = o.address or {}
    return {"id": o.id, "book_id": o.book_id, "status": o.status, "price_cents": o.price_cents,
            "price": wallet.dollars(o.price_cents), "lulu_status": o.lulu_status, "lulu_message": o.lulu_message,
            "tracking": o.tracking or [], "error": o.error, "ship_to": f"{a.get('name', '')}, {a.get('city', '')}, {a.get('state_code', '')}",
            "placed_at": o.placed_at.isoformat() if o.placed_at else None, "created_at": o.created_at.isoformat()}


def stripe_fee(price_cents: int) -> int:
    return round(price_cents * STRIPE_RATE) + STRIPE_FIXED_CENTS


def price_for(lulu_cents: int) -> int:
    """Lulu's charge, plus Stripe's fee and our profit, rounded up to .99: Lulu $23.95 makes $30.99."""
    floor = math.ceil((lulu_cents + PROFIT_CENTS + STRIPE_FIXED_CENTS) / (1 - STRIPE_RATE))
    return (floor + 1) // 100 * 100 + 99 if floor % 100 != 99 else floor


@router.get("/api/printing")
async def printing_info(request: Request, book: str):
    """What the order page needs: the price, whether printing is set up, and this book's earlier orders."""
    user = await _signed_in(request)
    row = await _own_book(user, book)
    story = story_for(row.story_key)
    async with session() as s:
        orders = (await s.execute(select(PrintOrder).where(PrintOrder.book_id == book, PrintOrder.status != "draft")
                                  .order_by(PrintOrder.created_at.desc()))).scalars().all()
        balance = await wallet.balance(s, user.id)
    return {"ready": configured(), "profit": wallet.dollars(PROFIT_CENTS), "balance_cents": balance, "free": await wallet.is_free(user), "orders": [order_out(o) for o in orders],
            "pdf_url": f"/api/books/{book}/pdf?inline=1",  # shown in the page, not downloaded
            "read_url": f"/stories/{story.slug}#book={book}"}  # the flip book


class QuoteIn(BaseModel):
    book: str
    approved: bool
    address: AddressIn


@router.post("/api/print-orders")
async def start_order(request: Request, body: QuoteIn):
    """Checks the address with Lulu and prices it. Nothing is charged or ordered yet."""
    user = await _signed_in(request)
    book = await _own_book(user, body.book)
    if not body.approved:
        raise HTTPException(422, {"message": "Please look through every page and tick that the book is ready to print.",
                                  "ref": current_ref(), "reason": "not_approved", "field": "approved"})
    address = clean_address(body.address)
    if not configured():
        raise HTTPException(503, {"message": "Printed books aren't switched on yet.", "ref": current_ref(),
                                  "reason": "printing_off"})
    try:
        quote = await lulu.quote(address, MIN_PRINT_PAGES)
    except LuluError as e:
        await record("WARNING", "print", "quote failed", book=book.id, error=str(e)[:300])
        raise _bad("The printer couldn't price a delivery to that address. Please check it and try again.")
    lulu_cost = cents(quote.get("total_cost_incl_tax"))
    price = price_for(lulu_cost)
    if price > MAX_PRICE_CENTS:
        await record("WARNING", "print", "too dear to ship", book=book.id, lulu_cents=lulu_cost)
        raise _bad("We can't ship a printed book to that address yet.")
    order = PrintOrder(id=uuid.uuid4().hex[:8], book_id=book.id, user_id=user.id, status="draft", address=address,
                       shipping_level=SHIPPING, price_cents=price, lulu_cost_cents=lulu_cost, quote=quote,
                       approved_at=utcnow())
    async with session() as s:
        s.add(order)
        await s.commit()
    await record("INFO", "print", "priced", order=order.id, book=book.id, lulu_cents=lulu_cost)
    return order_out(order)


@router.post("/api/print-orders/{order_id}/place")
async def place_order(request: Request, order_id: str):
    """Charges the wallet and sends the job to Lulu. If Lulu says no, the money goes straight back."""
    user = await _signed_in(request)
    order = await _own_order(user, order_id)
    if order.status != "draft":
        return order_out(order)  # placed already (a double click)
    free = await wallet.is_free(user)
    async with session() as s:
        await wallet.lock(s, user.id)
        if not free:
            if await wallet.balance(s, user.id) < order.price_cents:
                raise HTTPException(402, {"message": f"A printed book is {wallet.dollars(order.price_cents)}. "
                                                     "Add money to your wallet first.", "ref": current_ref(),
                                          "reason": "no_money"})
            s.add(Transaction(user_id=user.id, amount_cents=-order.price_cents, kind="print", book_id=order.book_id,
                              note=f"Printed copy, order {order.id}"))
        row = await s.get(PrintOrder, order.id)
        row.status, row.placed_at = "placed", utcnow()
        await s.commit()
    book = await _own_book(user, order.book_id)
    try:
        job = await lulu.create_job(order.id, story_for(book.story_key).title, order.address,
                                    file_link(request, order.id, "interior"), file_link(request, order.id, "cover"))
    except LuluError as e:
        await record("ERROR", "print", "job refused", order=order.id, error=str(e)[:300])
        async with session() as s:
            row = await s.get(PrintOrder, order.id)
            row.status, row.error = "failed", "The printer couldn't take the order."
            if not free:
                s.add(Transaction(user_id=user.id, amount_cents=order.price_cents, kind="print_refund",
                                  book_id=order.book_id, note=f"Order {order.id} didn't go through"))
            await s.commit()
        raise HTTPException(502, {"message": "The printer couldn't take the order, so your money is back in your wallet. "
                                             "Please try again in a little while.", "ref": current_ref()})
    async with session() as s:
        row = await s.get(PrintOrder, order.id)
        _copy_job(row, job)
        await s.commit()
        order = row
    await record("INFO", "print", "placed", order=order.id, job=order.lulu_job_id)
    return order_out(order)


def _copy_job(row: PrintOrder, job: dict) -> None:
    status = job.get("status") or {}
    row.lulu_job_id = str(job.get("id") or row.lulu_job_id or "")
    row.lulu_status, row.lulu_message, row.checked_at = status.get("name"), status.get("message"), utcnow()
    tracking = [{"carrier": (li.get("messages") or {}).get("carrier_name"),
                 "urls": (li.get("messages") or {}).get("tracking_urls") or []}
                for li in (status.get("line_item_statuses") or []) if (li.get("messages") or {}).get("tracking_urls")]
    if tracking:
        row.tracking = tracking


@router.get("/api/print-orders/{order_id}")
async def order_status(request: Request, order_id: str):
    """An order, with Lulu's latest news (asked at most once a minute)."""
    user = await _signed_in(request)
    order = await _own_order(user, order_id)
    checked = order.checked_at and order.checked_at.replace(tzinfo=order.checked_at.tzinfo or timezone.utc)  # SQLite drops it
    if order.lulu_job_id and configured() and (checked is None or utcnow() - checked >= CHECK_EVERY):
        try:
            job = await lulu.job(order.lulu_job_id)
            async with session() as s:
                row = await s.get(PrintOrder, order.id)
                _copy_job(row, job)
                await s.commit()
                order = row
        except LuluError as e:
            await record("WARNING", "print", "status failed", order=order.id, error=str(e)[:300])
    return order_out(order)


@router.get("/api/print-orders")
async def my_orders(request: Request):
    user = await _signed_in(request)
    async with session() as s:
        orders = (await s.execute(select(PrintOrder).where(PrintOrder.user_id == user.id, PrintOrder.status != "draft")
                                  .order_by(PrintOrder.created_at.desc()))).scalars().all()
    return [order_out(o) for o in orders]


async def admin_orders() -> list[dict]:
    """Every placed order with what it cost us and what we kept, for the admin site."""
    async with session() as s:
        orders = (await s.execute(select(PrintOrder).where(PrintOrder.status != "draft")
                                  .order_by(PrintOrder.created_at.desc()).limit(200))).scalars().all()
        books = {b.id: b for b in (await s.execute(select(Book).where(Book.id.in_([o.book_id for o in orders])))).scalars()}
    out = []
    for o in orders:
        made = cents((books.get(o.book_id).total_cost if books.get(o.book_id) else 0) or 0)
        fee = stripe_fee(o.price_cents)
        out.append({**order_out(o), "lulu_cost_cents": o.lulu_cost_cents, "making_cents": made,
                    "stripe_fee_cents": fee, "lulu_job_id": o.lulu_job_id,
                    "margin_cents": o.price_cents - o.lulu_cost_cents - made - fee})
    return out
