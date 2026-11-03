"""Book requests end to end: background jobs, the ref trail in the database, progress, PDF, resume.

Free and offline: a fresh SQLite database per test, mock images, a stubbed face check.
"""
import asyncio
import io
import time
from pathlib import Path

import httpx
import openai
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from pypdf import PdfReader
from sqlalchemy import select

import app.main
from app.book import jobs, providers
from app.db import session as db
from app.db.models import Book, BookEvent, BookImage, RequestError
from app.faces import PreparedPhoto

PASSWORD = "test-password"


def png(color="tan") -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (512, 512), color).save(buf, "PNG")
    return buf.getvalue()


def jpeg() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (800, 800), "green").save(buf, "JPEG")
    return buf.getvalue()


def run(coro):
    return asyncio.run(coro)


async def rows(model, **where):
    async with db.session() as s:
        q = select(model)
        for k, v in where.items():
            q = q.where(getattr(model, k) == v)
        return (await s.execute(q)).scalars().all()


@pytest.fixture
def client(tmp_path, monkeypatch):
    """A fresh database, mock images, a known password, and a face check that always passes."""
    monkeypatch.setenv("MOCK", "1")
    monkeypatch.delenv("MOCK_DELAY", raising=False)
    monkeypatch.setenv("APP_PASSWORD", PASSWORD)
    fake = PreparedPhoto(full_png=png(), face_png=png())
    monkeypatch.setattr(app.main, "prepare", lambda data: fake)
    monkeypatch.setattr(jobs, "prepare", lambda data: fake)
    db.reset(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    with TestClient(app.main.app) as c:
        yield c
    db.reset()


def post_book(client, password=PASSWORD, **form):
    data = {"name": "Sam", "age": "7", "favourites": "dinosaurs", **form}
    headers = {"X-App-Password": password} if password else {}
    return client.post("/api/books", files={"photo": ("x.jpg", jpeg(), "image/jpeg")}, data=data, headers=headers)


def wait_for(client, ref, timeout=10):
    deadline = time.time() + timeout
    while time.time() < deadline:
        data = client.get(f"/api/books/{ref}").json()
        if data["status"] in ("done", "failed"):
            return data
        time.sleep(0.05)
    raise AssertionError(f"book {ref} still {data['status']}")


# --- every request has a ref, and every ref has a row ---------------------------------------------

def test_every_response_has_a_request_id(client):
    assert len(client.get("/api/options").headers["x-request-id"]) == 8


def test_wrong_password_is_refused_and_recorded(client):
    r = post_book(client, password="nope")
    assert r.status_code == 401
    detail = r.json()["detail"]
    assert detail["reason"] == "wrong_password" and detail["ref"]
    book = run(rows(Book, id=detail["ref"]))[0]
    assert book.status == "refused" and book.refused_reason == "wrong_password"
    assert not run(rows(BookImage, book_id=book.id))  # nothing was drawn


def test_missing_password_is_refused(client):
    assert post_book(client, password=None).status_code == 401


def test_real_mode_without_app_password_refuses(client, monkeypatch):
    monkeypatch.delenv("MOCK")
    monkeypatch.delenv("APP_PASSWORD")
    r = post_book(client, password="anything")
    assert r.status_code == 503 and r.json()["detail"]["reason"] == "no_app_password"


def test_name_is_required(client):
    assert post_book(client, name="  ").json()["detail"]["reason"] == "no_name"


def test_unknown_gender_is_rejected(client):
    assert post_book(client, gender="dragon").json()["detail"]["reason"] == "unknown_gender"


def test_photo_without_face_is_refused(client, monkeypatch):
    from app.faces import prepare as real_prepare
    monkeypatch.setattr(app.main, "prepare", real_prepare)
    r = post_book(client)
    assert r.status_code == 422 and r.json()["detail"]["reason"] == "face_check"


def test_unknown_book_is_404(client):
    assert client.get("/api/books/deadbeef").status_code == 404


# --- a whole book ---------------------------------------------------------------------------------

def test_book_runs_in_the_background_and_is_saved(client):
    r = post_book(client, favourites="dinosaurs, pancakes", about="Loves climbing trees")
    assert r.status_code == 202
    ref = r.json()["id"]
    data = wait_for(client, ref)
    assert data["status"] == "done"
    assert [(i["kind"], i["page"], i["status"]) for i in data["images"]] == \
        [("hero_sheet", 0, "done"), ("page", 1, "done"), ("page", 2, "done"), ("page", 3, "done")]
    assert all(i["eta_seconds"] > 0 and i["started_at"] and i["finished_at"] for i in data["images"])
    # the photo and every image are kept for debugging
    book = run(rows(Book, id=ref))[0]
    assert book.child_name == "Sam" and book.provider == "mock"
    assert all(i.image and i.prompt for i in run(rows(BookImage, book_id=ref)))


def test_pdf_is_rebuilt_from_saved_images(client):
    ref = post_book(client, favourites="dinosaurs, pancakes").json()["id"]
    wait_for(client, ref)
    r = client.get(f"/api/books/{ref}/pdf")
    assert r.headers["content-type"] == "application/pdf"
    assert 'filename="JackAndTheBeanstalk.pdf"' in r.headers["content-disposition"]
    pages = PdfReader(io.BytesIO(r.content)).pages
    assert len(pages) == 4
    assert "nothing left to sell" in pages[0].extract_text()
    about = pages[-1].extract_text()
    assert "About Me" in about and "Sam" in about and "dinosaurs, pancakes" in about


def test_jane_book_uses_jane(client):
    ref = post_book(client, gender="girl").json()["id"]
    wait_for(client, ref)
    assert "Jane and her mother" in PdfReader(io.BytesIO(client.get(f"/api/books/{ref}/pdf").content)).pages[0].extract_text()


def test_thumbnails_are_served(client):
    ref = post_book(client).json()["id"]
    data = wait_for(client, ref)
    r = client.get(data["images"][1]["image_url"] + "?w=200")
    assert r.headers["content-type"] == "image/webp"
    assert max(Image.open(io.BytesIO(r.content)).size) <= 200


# --- the trail for post-mortems -------------------------------------------------------------------

def test_every_step_has_start_and_done_in_the_database(client):
    ref = post_book(client).json()["id"]
    wait_for(client, ref)
    events = run(rows(BookEvent, book_id=ref))
    for name in ("face check", "hero sheet", "page 1", "page 2", "page 3", "book"):
        assert any(e.step == name and e.event == "start" for e in events), name
        assert any(e.step == name and e.event == "done" and e.duration_ms is not None for e in events), name


def test_trail_never_holds_password_or_child_details(client, caplog):
    caplog.set_level("INFO", logger="book")
    ref = post_book(client, name="Zebediah", favourites="unicorn-pancakes", about="secret-fort").json()["id"]
    wait_for(client, ref)
    saved = " ".join(f"{e.step} {e.event} {e.fields}" for e in run(rows(BookEvent, book_id=ref)))
    logged = " ".join(r.getMessage() for r in caplog.records)
    for private in (PASSWORD, "Zebediah", "unicorn-pancakes", "secret-fort"):
        assert private not in saved and private not in logged


def test_a_failed_page_fails_the_book_but_keeps_the_rest(client, monkeypatch):
    original = providers.MockImageProvider.edit

    async def flaky(self, label, refs, prompt, size):
        if label == "page 2":  # fails inside its step, the way the real provider's call would
            from app.book.log import step
            async with step(label):
                raise openai.APITimeoutError(request=httpx.Request("POST", "https://api.openai.com/v1/images/edits"))
        return await original(self, label, refs, prompt, size)

    monkeypatch.setattr(providers.MockImageProvider, "edit", flaky)
    ref = post_book(client).json()["id"]
    data = wait_for(client, ref)
    assert data["status"] == "failed" and "took too long" in data["error"]
    status = {(i["kind"], i["page"]): i["status"] for i in data["images"]}
    assert status[("page", 2)] == "failed" and status[("page", 1)] == "done" and status[("page", 3)] == "done"
    failed = [e for e in run(rows(BookEvent, book_id=ref)) if e.event == "failed" and e.step == "page 2"]
    assert failed and failed[0].fields["error"] == "APITimeoutError"


def test_interrupted_book_resumes_without_redrawing(client, monkeypatch):
    """After a restart, finished images are reused and only the missing ones are drawn."""
    ref = post_book(client).json()["id"]
    wait_for(client, ref)

    async def interrupt():
        async with db.session() as s:
            (await s.get(Book, ref)).status = "running"
            for img in (await s.execute(select(BookImage).where(BookImage.book_id == ref))).scalars():
                if img.kind == "page" and img.page_number == 3:
                    img.status, img.image = "drawing", None
            await s.commit()
    run(interrupt())

    drawn = []
    original = providers.MockImageProvider.edit

    async def counting(self, label, refs, prompt, size):
        drawn.append(label)
        return await original(self, label, refs, prompt, size)

    monkeypatch.setattr(providers.MockImageProvider, "edit", counting)
    client.portal.call(jobs.resume_unfinished)
    assert wait_for(client, ref)["status"] == "done"
    assert drawn == ["page 3"]


def test_page_errors_get_a_ref_and_a_row(client):
    r = client.post("/api/client-error", content=b'{"message":"boom"}', headers={"user-agent": "Safari 15"})
    ref = r.json()["ref"]
    saved = run(rows(RequestError, id=ref))[0]
    assert saved.path == "page-script" and "boom" in saved.message and saved.browser == "Safari 15"


# --- the page -------------------------------------------------------------------------------------

def test_page_links_versioned_assets_and_is_not_cached(client):
    r = client.get("/")
    assert r.headers["cache-control"] == "no-cache"
    assert f"/static/app.js?v={app.main.ASSET_VERSION}" in r.text
    assert client.get("/static/app.js").headers["cache-control"] == "no-cache"


def test_form_without_script_lands_on_a_message(client):
    assert 'method="post" action="/no-script"' in client.get("/").text
    r = client.post("/no-script", data={"password": "x"})
    assert r.status_code == 400 and "reload" in r.text


def test_openai_client_has_no_hidden_retries(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-real")
    c = providers.OpenAIImageProvider().client
    assert c.max_retries == 0 and c.timeout == 120


# --- the magic word, photos, the themed page --------------------------------------------------------

def test_unlock_accepts_the_password(client):
    assert client.post("/api/unlock", headers={"X-App-Password": PASSWORD}).status_code == 204


def test_wrong_unlock_gets_a_ref_and_a_row(client):
    r = client.post("/api/unlock", headers={"X-App-Password": "nope"})
    assert r.status_code == 401
    ref = r.json()["detail"]["ref"]
    saved = run(rows(RequestError, id=ref))[0]
    assert saved.path == "/api/unlock" and saved.error_type == "wrong_password"


def test_heic_photo_is_converted_for_the_preview(client):
    # A real iPhone-format file, made once (encoding HEIC inside the test process crashes libheif).
    heic = (Path(__file__).parent / "fixtures" / "photo.heic").read_bytes()
    r = client.post("/api/photo-preview", files={"photo": ("photo.heic", heic, "image/heic")})
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
    img = Image.open(io.BytesIO(r.content))
    assert img.format == "JPEG" and max(img.size) == 1600


def test_unreadable_photo_preview_is_refused_with_a_ref(client):
    r = client.post("/api/photo-preview", files={"photo": ("x.txt", b"not a photo", "text/plain")})
    assert r.status_code == 422 and r.json()["detail"]["ref"]


def test_page_wears_the_story_theme(client):
    html = client.get("/").text
    assert "/static/themes/jack/theme.css?v=" in html
    assert 'class="scene"' in html and "<!--SCENE-->" not in html


def test_finished_book_has_flipbook_pages(client):
    ref = post_book(client, gender="girl").json()["id"]
    data = wait_for(client, ref)
    book = data["book"]
    assert book["hero"] == "Jane" and book["child_name"] == "Sam"
    assert [p["kind"] for p in book["pages"]] == ["illustrated", "illustrated", "illustrated", "about_me"]
    assert book["pages"][1]["text_zone"] == "top" and "Five magic beans" in book["pages"][1]["text"]
