"""Printed books through Lulu (a fake Lulu here): approve the PDF, give a US address, see the price, place the
order. The wallet pays; Lulu fetches the print files from signed links; a refused job gives the money back."""
import io
import re

import pytest
from pypdf import PdfReader

from app import printing
from app.db.models import PrintOrder, Transaction
from tests.test_books import (ADMIN, PARENT, client, fund, post_book, rows, run, sign_in,  # noqa: F401 (fixture)
                              wait_for)

ADDRESS = {"name": "Sam's Mom", "street1": "101 Independence Ave SE", "city": "Washington", "state_code": "dc",
           "postcode": "20540", "phone_number": "(202) 555-0100"}


class FakeLulu:
    def __init__(self, cost="24.50", refuse=False):
        self.cost, self.refuse, self.jobs, self.quotes = cost, refuse, [], []

    async def quote(self, address, pages):
        self.quotes.append((address, pages))
        return {"total_cost_incl_tax": self.cost, "currency": "USD"}

    async def cover_size(self, pages):
        return 1710.0, 720.0

    async def create_job(self, order_id, title, address, interior_url, cover_url):
        if self.refuse:
            raise printing.LuluError("400: bad file")
        self.jobs.append({"order": order_id, "title": title, "interior": interior_url, "cover": cover_url})
        return {"id": 4242, "status": {"name": "CREATED", "message": "Print-job is currently being validated"}}

    async def job(self, job_id):
        return {"id": job_id, "status": {"name": "SHIPPED", "message": "All line-items were shipped",
                                         "line_item_statuses": [{"messages": {"carrier_name": "UPS",
                                                                              "tracking_urls": ["https://t.example/1"]}}]}}


@pytest.fixture
def lulu(monkeypatch):
    fake = FakeLulu()
    monkeypatch.setattr(printing, "lulu", fake)
    monkeypatch.setenv("LULU_CLIENT_KEY", "k")
    monkeypatch.setenv("LULU_CLIENT_SECRET", "s")
    monkeypatch.setenv("LULU_CONTACT_EMAIL", "orders@example.com")
    return fake


def a_finished_book(client):
    ref = post_book(client).json()["id"]
    wait_for(client, ref)
    return ref


def balance(client):
    return client.get("/api/wallet").json()["balance_cents"]


def test_nothing_is_priced_before_the_pdf_is_approved(client, lulu):
    ref = a_finished_book(client)
    r = client.post("/api/print-orders", json={"book": ref, "approved": False, "address": ADDRESS})
    assert r.status_code == 422 and r.json()["detail"]["field"] == "approved"
    assert not lulu.quotes


def test_order_a_printed_copy(client, lulu, monkeypatch):
    monkeypatch.setattr(printing, "CHECK_EVERY", printing.CHECK_EVERY)  # put back after the test
    ref = a_finished_book(client)
    before = balance(client)
    priced = client.post("/api/print-orders", json={"book": ref, "approved": True, "address": ADDRESS}).json()
    assert priced["status"] == "draft" and priced["price_cents"] == 3099  # Lulu $24.50 + Stripe's fee + $5, up to .99
    address, pages = lulu.quotes[0]
    assert address["state_code"] == "DC" and address["country_code"] == "US" and pages == 24
    assert balance(client) == before  # pricing charges nothing

    placed = client.post(f"/api/print-orders/{priced['id']}/place").json()
    assert placed["status"] == "placed" and placed["lulu_status"] == "CREATED"
    assert balance(client) == before - 3099
    charge = [t for t in run(rows(Transaction, book_id=ref)) if t.kind == "print"]
    assert len(charge) == 1 and charge[0].amount_cents == -3099
    assert client.post(f"/api/print-orders/{priced['id']}/place").json()["status"] == "placed"  # a double click
    assert balance(client) == before - 3099  # charged once

    # Lulu downloads both files from the signed links, without signing in
    job = lulu.jobs[0]
    assert job["title"] == "Jack and the Beanstalk"
    client.cookies.clear()
    path = lambda url: re.sub(r"^https?://[^/]+", "", url)
    interior = client.get(path(job["interior"]))
    assert interior.status_code == 200 and len(PdfReader(io.BytesIO(interior.content)).pages) == 24
    cover = PdfReader(io.BytesIO(client.get(path(job["cover"])).content)).pages[0]
    assert float(cover.mediabox.width) == 1710  # the size Lulu asked for
    assert client.get(path(job["cover"]).replace("/cover.pdf", "/interior.pdf")).status_code == 404  # links are per file
    assert client.get("/print-files/forged.token/interior.pdf").status_code == 404

    sign_in(client, PARENT)
    printing.CHECK_EVERY = printing.timedelta(0)  # as if a minute had passed
    later = client.get(f"/api/print-orders/{priced['id']}").json()
    assert later["lulu_status"] == "SHIPPED" and later["tracking"][0]["urls"] == ["https://t.example/1"]
    info = client.get(f"/api/printing?book={ref}").json()
    assert [o["id"] for o in info["orders"]] == [priced["id"]]
    assert info["read_url"] == f"/stories/jack-and-the-beanstalk#book={ref}"
    shown = client.get(info["pdf_url"])  # shown in the page, never downloaded
    assert shown.headers["content-disposition"].startswith("inline")

    sign_in(client, ADMIN)
    row = client.get("/admin/api/print-orders").json()["items"][0]
    assert row["lulu_cost_cents"] == 2450
    assert row["margin_cents"] == row["price_cents"] - 2450 - row["making_cents"] - row["stripe_fee_cents"]


def test_a_refused_job_gives_the_money_back(client, lulu):
    ref = a_finished_book(client)
    before = balance(client)
    lulu.refuse = True
    order = client.post("/api/print-orders", json={"book": ref, "approved": True, "address": ADDRESS}).json()
    r = client.post(f"/api/print-orders/{order['id']}/place")
    assert r.status_code == 502 and "back in your wallet" in r.json()["detail"]["message"]
    assert balance(client) == before
    assert run(rows(PrintOrder, id=order["id"]))[0].status == "failed"


def test_not_enough_in_the_wallet(client, lulu):
    ref = a_finished_book(client)
    order = client.post("/api/print-orders", json={"book": ref, "approved": True, "address": ADDRESS}).json()
    user = sign_in(client, PARENT)
    fund(user.id, -balance(client) + 100)  # leave $1
    r = client.post(f"/api/print-orders/{order['id']}/place")
    assert r.status_code == 402 and not lulu.jobs and balance(client) == 100


@pytest.mark.parametrize("change, field", [({"state_code": "Ontario"}, "state_code"), ({"postcode": "1234"}, "postcode"),
                                           ({"phone_number": "555"}, "phone_number"), ({"city": " "}, "city")])
def test_a_bad_address_says_which_part(client, lulu, change, field):
    ref = a_finished_book(client)
    r = client.post("/api/print-orders", json={"book": ref, "approved": True, "address": {**ADDRESS, **change}})
    assert r.status_code == 422 and r.json()["detail"]["field"] == field and not lulu.quotes


@pytest.mark.parametrize("lulu_cents, price", [(2395, 3099), (2450, 3099), (3248, 3899), (3990, 4699)])
def test_the_price_is_lulus_charge_plus_fees_and_profit(lulu_cents, price):
    assert printing.price_for(lulu_cents) == price
    kept = price - lulu_cents - printing.stripe_fee(price)
    assert printing.PROFIT_CENTS <= kept < printing.PROFIT_CENTS + 100  # $5, plus whatever rounding to .99 adds


def test_an_address_too_dear_to_ship_to_is_refused(client, lulu):
    ref = a_finished_book(client)
    lulu.cost = "95.00"
    r = client.post("/api/print-orders", json={"book": ref, "approved": True, "address": ADDRESS})
    assert r.status_code == 422 and not run(rows(PrintOrder, book_id=ref))


def test_someone_elses_book_cannot_be_ordered(client, lulu):
    ref = a_finished_book(client)
    sign_in(client, "stranger@example.com")
    r = client.post("/api/print-orders", json={"book": ref, "approved": True, "address": ADDRESS})
    assert r.status_code == 404 and not lulu.quotes


def test_printing_off_until_lulu_keys_are_set(client, monkeypatch):
    monkeypatch.delenv("LULU_CLIENT_KEY", raising=False)
    ref = a_finished_book(client)
    assert client.get(f"/api/printing?book={ref}").json()["ready"] is False
    r = client.post("/api/print-orders", json={"book": ref, "approved": True, "address": ADDRESS})
    assert r.status_code == 503
