"""The wallet: Stripe top-ups, $0.99 a book, refunds. Stripe is faked, so this is free and offline."""
import itertools

import pytest
from sqlalchemy import select

from app import notify, wallet
from app.db import session as db
from app.db.models import Book, BookImage, Payment
from tests.test_books import ADMIN, PARENT, PASSWORD, client, fund, post_book, rows, run, sign_in, wait_for  # noqa: F401


class FakeStripe:
    """Stands in for Stripe's API: checkout sessions that can be marked paid, and refunds."""

    def __init__(self):
        self.sessions, self.refunds, self.ids = {}, [], itertools.count(1)
        self.fail_refunds = False

    async def __call__(self, method, path, data=None):
        if method == "POST" and path == "/checkout/sessions":
            sid = f"cs_test_{next(self.ids)}"
            self.sessions[sid] = {"id": sid, "url": f"https://checkout.stripe.com/{sid}", "payment_status": "unpaid",
                                  "status": "open", "payment_intent": None, "amount": data["line_items[0][price_data][unit_amount]"]}
            return self.sessions[sid]
        if method == "GET" and path.startswith("/checkout/sessions/"):
            return self.sessions[path.rsplit("/", 1)[1]]
        if method == "POST" and path == "/refunds":
            if self.fail_refunds:
                raise wallet.StripeError("card declined the refund")
            self.refunds.append(data)
            return {"id": f"re_{len(self.refunds)}"}
        raise AssertionError(f"unexpected Stripe call {method} {path}")

    def pay(self, sid):
        self.sessions[sid].update(payment_status="paid", status="complete", payment_intent=f"pi_{sid}")


@pytest.fixture
def stripe(client, monkeypatch):
    fake = FakeStripe()
    monkeypatch.setattr(wallet, "stripe", fake)
    return fake


@pytest.fixture
def emails(monkeypatch):
    sent = []

    async def capture(subject, body):
        sent.append((subject, body))
        return True
    monkeypatch.setattr(notify, "send_admins", capture)
    return sent


def failed(ref):
    """As if page 2 had failed to draw."""
    async def mark():
        async with db.session() as s:
            (await s.get(Book, ref)).status = "failed"
            for i in (await s.execute(select(BookImage).where(BookImage.book_id == ref,
                                                              BookImage.page_number == 2))).scalars():
                i.status = "failed"
            await s.commit()
    run(mark())


def broke(client):
    """A new person with an empty wallet."""
    return sign_in(client, "new@example.com")


def top_up(client, stripe, cents=500):
    r = client.post("/api/wallet/checkout", json={"cents": cents})
    assert r.status_code == 200 and r.json()["url"].startswith("https://checkout.stripe.com/")
    sid = r.json()["url"].rsplit("/", 1)[1]
    stripe.pay(sid)
    return sid


# --- adding money ---------------------------------------------------------------------------------

def test_a_paid_checkout_is_credited_once(client, stripe):
    broke(client)
    sid = top_up(client, stripe)
    for _ in range(3):  # coming back, reloading, and the open-session check all settle the same payment
        w = client.get(f"/api/wallet?paid={sid}").json()
    assert w["balance_cents"] == 500
    assert [t["kind"] for t in w["transactions"]] == ["deposit"]
    assert run(rows(Payment, id=sid))[0].status == "paid"


def test_an_unpaid_checkout_adds_nothing(client, stripe):
    broke(client)
    client.post("/api/wallet/checkout", json={"cents": 1000})
    assert client.get("/api/wallet").json()["balance_cents"] == 0


def test_any_amount_from_one_to_a_hundred_dollars(client, stripe):
    for cents in (100, 1234, 10000):
        assert client.post("/api/wallet/checkout", json={"cents": cents}).status_code == 200
    for cents in (99, 10001, 0, -500):
        r = client.post("/api/wallet/checkout", json={"cents": cents})
        assert r.status_code == 400 and r.json()["detail"]["reason"] == "bad_amount"


def test_wallet_needs_sign_in(client, stripe):
    client.cookies.clear()
    assert client.get("/api/wallet").status_code == 401


def test_the_admin_sees_money_coming_in_and_going_out(client, stripe):
    broke(client)
    sid = top_up(client, stripe)
    client.get(f"/api/wallet?paid={sid}")
    ref = post_book(client).json()["id"]
    wait_for(client, ref)
    assert client.get("/admin/api/activity").status_code == 403

    sign_in(client, ADMIN)
    d = client.get("/admin/api/activity?kind=money").json()
    mine = [(a["step"], a["event"], a["fields"].get("cents")) for a in d["items"] if a["email"] == "new@example.com"]
    assert ("wallet", "checkout opened", "500") in mine and ("wallet", "paid", "500") in mine
    assert ("wallet", "charged", "99") in mine
    assert d["money"]["added"] >= 500 and d["money"]["spent"] >= 99
    books = client.get("/admin/api/activity?kind=books&q=" + ref).json()["items"]
    assert {(a["event"], a["email"]) for a in books} >= {("received", "new@example.com"), ("done", "new@example.com")}
    assert not any(a["step"].startswith("page") for a in books)  # each picture stays in the book's own trail


# --- paying for books -----------------------------------------------------------------------------

def test_a_book_costs_99_cents_and_says_so_in_the_history(client, stripe):
    broke(client)
    top_up(client, stripe)
    client.get("/api/wallet")
    ref = post_book(client).json()["id"]
    wait_for(client, ref)
    w = client.get("/api/wallet").json()
    assert w["balance_cents"] == 401
    assert w["transactions"][0]["kind"] == "book" and w["transactions"][0]["book_id"] == ref
    assert client.get("/api/me").json()["left"] == 4


def test_no_money_no_book(client, stripe):
    broke(client)
    r = post_book(client)
    assert r.status_code == 402 and r.json()["detail"]["reason"] == "no_money"
    assert "$0.99" in r.json()["detail"]["message"]


def test_a_refused_photo_costs_nothing(client, stripe):
    user = broke(client)
    fund(user.id, 99)
    assert post_book(client, name=" ").status_code == 400
    assert client.get("/api/wallet").json()["balance_cents"] == 99


def test_the_last_99_cents_buys_one_book_not_two(client, stripe, monkeypatch):
    monkeypatch.setenv("MOCK_DELAY", "0.3")
    user = broke(client)
    fund(user.id, 150)
    ref = post_book(client).json()["id"]
    assert post_book(client).status_code == 402
    wait_for(client, ref)


def test_retrying_a_failed_book_is_free(client, stripe):
    user = broke(client)
    fund(user.id, 99)
    ref = post_book(client).json()["id"]
    wait_for(client, ref)
    failed(ref)
    assert client.post(f"/api/books/{ref}/retry", headers={"X-App-Password": PASSWORD}).status_code == 202
    assert wait_for(client, ref)["status"] == "done"
    assert client.get("/api/wallet").json()["balance_cents"] == 0


def test_admins_and_the_unlimited_list_are_free(client, stripe):
    sign_in(client, ADMIN)
    client.post("/admin/api/unlimited", json={"email": "friend@example.com"})
    for email in ("friend@example.com", ADMIN):
        sign_in(client, email)
        assert post_book(client).status_code == 202
        assert client.get("/api/me").json()["left"] is None
        assert client.get("/api/wallet").json()["transactions"] == []


# --- unspent money back to the card: straight away ------------------------------------------------

def test_unspent_money_goes_straight_back_to_the_card(client, stripe, emails):
    broke(client)
    sid = top_up(client, stripe, 1000)
    client.get("/api/wallet")
    r = client.post("/api/wallet/refund", json={"cents": 600})
    assert r.status_code == 200 and r.json() == {"sent_cents": 600, "problem": None}
    assert stripe.refunds == [{"payment_intent": f"pi_{sid}", "amount": 600}]
    w = client.get("/api/wallet").json()
    assert w["balance_cents"] == 400 and w["refundable_cents"] == 400
    assert w["transactions"][0]["kind"] == "refund" and w["transactions"][0]["cents"] == -600
    assert emails == [] and w["refund_requests"] == []  # no review, no email


def test_a_refund_can_span_two_top_ups(client, stripe, emails):
    broke(client)
    first, second = top_up(client, stripe, 100), top_up(client, stripe, 500)
    client.get("/api/wallet")
    assert client.post("/api/wallet/refund", json={"cents": 550}).json()["sent_cents"] == 550
    assert [(x["payment_intent"], x["amount"]) for x in stripe.refunds] == [(f"pi_{second}", 500), (f"pi_{first}", 50)]
    assert client.get("/api/wallet").json()["balance_cents"] == 50


def test_money_spent_on_a_book_cant_go_back_to_the_card(client, stripe, emails):
    broke(client)
    top_up(client, stripe, 500)
    client.get("/api/wallet")
    wait_for(client, post_book(client).json()["id"])
    assert client.get("/api/wallet").json()["refundable_cents"] == 401
    r = client.post("/api/wallet/refund", json={"cents": 500})
    assert r.status_code == 400 and r.json()["detail"]["reason"] == "too_much"


def test_no_negative_or_zero_refunds(client, stripe):
    for cents in (0, -100):
        assert client.post("/api/wallet/refund", json={"cents": cents}).status_code == 422


def test_a_refund_stripe_rejects_keeps_the_money(client, stripe, emails):
    broke(client)
    top_up(client, stripe, 500)
    client.get("/api/wallet")
    stripe.fail_refunds = True
    r = client.post("/api/wallet/refund", json={"cents": 300})
    assert r.status_code == 502 and "card declined" in r.json()["detail"]["message"]
    assert client.get("/api/wallet").json()["balance_cents"] == 500


# --- a book that came out wrong: reviewed --------------------------------------------------------

def paid_book(client):
    user = broke(client)
    fund(user.id, 99)
    ref = post_book(client).json()["id"]
    wait_for(client, ref)
    return ref


def test_book_refund_is_reviewed_then_goes_back_to_the_wallet(client, stripe, emails):
    ref = paid_book(client)
    assert [b["id"] for b in client.get("/api/wallet").json()["books_to_ask_about"]] == [ref]
    r = client.post("/api/wallet/book-refunds", json={"book_id": ref, "reason": "my face is wrong on page 4"})
    assert r.status_code == 201
    assert emails and ref in emails[0][0] and "page 4" in emails[0][1]
    w = client.get("/api/wallet").json()
    assert w["balance_cents"] == 0 and w["refund_requests"][0]["status"] == "pending"
    assert w["books_to_ask_about"] == []
    assert client.post("/api/wallet/book-refunds", json={"book_id": ref, "reason": "again"}).status_code == 400

    sign_in(client, ADMIN)
    req = client.get("/admin/api/refunds").json()["items"][0]
    assert req["email"] == "new@example.com" and req["book_id"] == ref and req["cents"] == 99
    assert client.post(f"/admin/api/refunds/{req['id']}", json={"approve": True, "note": "sorry!"}).json()["status"] == "approved"
    assert client.post(f"/admin/api/refunds/{req['id']}", json={"approve": False}).status_code == 409

    sign_in(client, "new@example.com")
    w = client.get("/api/wallet").json()
    assert w["balance_cents"] == 99 and w["transactions"][0]["kind"] == "book_refund"
    assert w["refundable_cents"] == 0  # back in the wallet, not to the card
    assert stripe.refunds == []


def test_denied_book_refund_moves_no_money(client, stripe, emails):
    ref = paid_book(client)
    client.post("/api/wallet/book-refunds", json={"book_id": ref, "reason": "x"})
    sign_in(client, ADMIN)
    rid = client.get("/admin/api/refunds?status=pending").json()["items"][0]["id"]
    client.post(f"/admin/api/refunds/{rid}", json={"approve": False, "note": "looks right to us"})
    sign_in(client, "new@example.com")
    w = client.get("/api/wallet").json()
    assert w["balance_cents"] == 0 and w["refund_requests"][0]["status"] == "denied"
    assert w["refund_requests"][0]["admin_note"] == "looks right to us"


def test_a_book_refund_needs_a_reason(client, stripe, emails):
    ref = paid_book(client)
    assert client.post("/api/wallet/book-refunds", json={"book_id": ref, "reason": "  "}).status_code == 422


def test_cant_ask_about_someone_elses_or_a_free_book(client, stripe, emails):
    ref = post_book(client).json()["id"]  # PARENT's book
    wait_for(client, ref)
    broke(client)
    assert client.post("/api/wallet/book-refunds", json={"book_id": ref, "reason": "x"}).status_code == 400
    sign_in(client, ADMIN)
    free = post_book(client).json()["id"]  # admins don't pay, so there's nothing to give back
    wait_for(client, free)
    assert client.post("/api/wallet/book-refunds", json={"book_id": free, "reason": "x"}).status_code == 400


def test_only_admins_decide_refunds(client, stripe):
    assert client.get("/admin/api/refunds").status_code == 403
    assert client.post("/admin/api/refunds/1", json={"approve": True}).status_code == 403


def test_email_without_smtp_is_just_logged(monkeypatch):
    for k in ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD"):
        monkeypatch.delenv(k, raising=False)
    assert run(notify.send_admins("x", "y")) is False


def test_wallet_page_loads(client):
    assert client.get("/wallet").status_code == 200
