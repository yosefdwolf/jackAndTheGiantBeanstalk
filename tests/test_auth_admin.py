"""Sign-in, the daily limit, and the admin site. Free and offline, like test_books."""
import asyncio

from sqlalchemy import select

from app import admin, auth
from app.book import jobs
from app.db import session as db
from app.db.models import Book, BookImage, RequestError
from tests.test_books import ADMIN, PARENT, client, post_book, rows, run, sign_in, wait_for  # noqa: F401


# --- signing in -----------------------------------------------------------------------------------

def test_book_needs_sign_in(client):
    client.cookies.clear()
    r = post_book(client)
    assert r.status_code == 401 and r.json()["detail"]["reason"] == "not_signed_in"
    assert run(rows(Book, id=r.json()["detail"]["ref"]))[0].status == "refused"


def test_magic_word_is_still_needed_when_signed_in(client):
    assert post_book(client, password="nope").json()["detail"]["reason"] == "wrong_password"


def test_tampered_cookie_is_ignored(client):
    value = client.cookies.get(auth.COOKIE)
    client.cookies.set(auth.COOKIE, value[:-1] + ("0" if value[-1] != "0" else "1"))
    assert client.get("/api/me").json()["signed_in"] is False


def test_me_reports_books_left(client):
    me = client.get("/api/me").json()
    assert me["signed_in"] and me["email"] == PARENT and me["left"] == 3 and not me["admin"]
    wait_for(client, post_book(client).json()["id"])
    assert client.get("/api/me").json()["left"] == 2


def test_book_is_linked_to_the_user(client):
    ref = post_book(client).json()["id"]
    wait_for(client, ref)
    book = run(rows(Book, id=ref))[0]
    assert book.user_id is not None


def test_same_email_from_a_new_sign_in_is_the_same_person(client):
    first = run(auth.upsert_user("google-1", "Same@Example.com"))
    assert run(auth.upsert_user("dev:same@example.com", "same@example.com")).id == first.id
    assert run(auth.upsert_user("google-1", "same@example.com")).id == first.id


def test_next_only_allows_same_site_paths():
    assert auth._safe_next("/admin") == "/admin"
    for bad in ("https://evil.example", "//evil.example", "/\\evil", "", None):
        assert auth._safe_next(bad) == "/"


def test_login_without_google_is_explained(client):
    r = client.get("/auth/login", follow_redirects=False)
    assert r.status_code == 503 and r.json()["detail"]["reason"] == "no_google"


def test_dev_login_only_when_asked_for_and_google_is_off(client, monkeypatch):
    monkeypatch.setenv("DEV_LOGIN", "1")
    client.cookies.clear()
    r = client.get("/auth/login?next=/admin&email=someone@example.com", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/admin"
    assert client.get("/api/me").json()["email"] == "someone@example.com"
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "x")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "y")
    r = client.get("/auth/login", follow_redirects=False)
    assert r.headers["location"].startswith("https://accounts.google.com/")


def test_callback_with_bad_state_is_refused_and_recorded(client, monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "x")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "y")
    r = client.get("/auth/callback?code=abc&state=forged")
    assert r.status_code == 400
    ref = r.json()["detail"]["ref"]
    assert run(rows(RequestError, id=ref))[0].error_type == "bad_state"


# --- three books a day ----------------------------------------------------------------------------

def test_fourth_book_in_a_day_is_refused(client):
    for _ in range(3):
        assert post_book(client).status_code == 202
    r = post_book(client)
    assert r.status_code == 429 and r.json()["detail"]["reason"] == "daily_limit"


def test_refused_and_undrawn_failures_dont_count(client):
    for _ in range(3):
        post_book(client, name=" ")  # refused: no name
    ref = post_book(client).json()["id"]
    wait_for(client, ref)

    async def fail_without_images():
        async with db.session() as s:
            (await s.get(Book, ref)).status = "failed"
            for i in (await s.execute(select(BookImage).where(BookImage.book_id == ref))).scalars():
                i.status = "failed"
            await s.commit()
    run(fail_without_images())
    assert run(jobs.books_today(run(rows(Book, id=ref))[0].user_id)) == 0


def test_unlimited_list_and_admins_skip_the_limit(client):
    sign_in(client, ADMIN)
    r = client.post("/admin/api/unlimited", json={"email": "Friend@Example.com"})
    assert r.status_code == 200 and r.json()["emails"][0]["email"] == "friend@example.com"
    for email in ("friend@example.com", ADMIN):
        sign_in(client, email)
        for _ in range(4):
            assert post_book(client).status_code == 202
        assert client.get("/api/me").json()["left"] is None


# --- the admin site -------------------------------------------------------------------------------

def test_admin_api_is_for_admins_only(client):
    assert client.get("/admin/api/books").status_code == 403
    client.cookies.clear()
    assert client.get("/admin/api/books").status_code == 401
    assert client.get("/admin", follow_redirects=False).headers["location"] == "/auth/login?next=/admin"


def test_admin_host_serves_the_dashboard_at_the_root(client):
    sign_in(client, ADMIN)
    r = client.get("/", headers={"host": "admin.jack.graydates.com"})
    assert r.status_code == 200 and ADMIN in r.text and "admin.js" in r.text
    assert client.get("/api/options", headers={"host": "admin.jack.graydates.com"}).status_code == 200
    client.cookies.clear()
    r = client.get("/", headers={"host": "admin.jack.graydates.com"}, follow_redirects=False)
    assert r.headers["location"] == "/auth/login?next=/"


def test_admin_lists_and_filters_books(client):
    good = post_book(client).json()["id"]
    wait_for(client, good)
    refused = post_book(client, password="nope").json()["detail"]["ref"]
    sign_in(client, ADMIN)
    data = client.get("/admin/api/books").json()
    assert {i["id"] for i in data["items"]} == {good, refused}
    assert data["summary"]["by_status"] == {"done": 1, "refused": 1}
    assert "wrong_password" in data["filters"]["reasons"]
    assert [i["id"] for i in client.get("/admin/api/books?status=refused").json()["items"]] == [refused]
    assert [i["id"] for i in client.get("/admin/api/books?reason=wrong_password").json()["items"]] == [refused]
    assert [i["id"] for i in client.get(f"/admin/api/books?q={good[:4]}").json()["items"]] == [good]
    assert [i["email"] for i in client.get("/admin/api/books?q=parent").json()["items"]] == [PARENT, PARENT]
    assert client.get("/admin/api/days").json()[0]["books"] == 2


def test_admin_book_page_has_timeline_prompts_and_photo(client):
    ref = post_book(client).json()["id"]
    wait_for(client, ref)
    sign_in(client, ADMIN)
    data = client.get(f"/admin/api/books/{ref}").json()
    assert data["book"]["email"] == PARENT and data["upload"]["mime"] == "image/jpeg"
    assert all(i["prompt"] for i in data["images"])
    steps = [(e["step"], e["event"]) for e in data["events"]]
    assert ("book", "start") in steps and ("book", "done") in steps
    assert not any(e["stuck"] for e in data["events"])
    assert client.get(data["photo_url"]).headers["content-type"] == "image/webp"


def test_admin_flags_a_step_that_never_finished(client):
    ref = post_book(client).json()["id"]
    wait_for(client, ref)
    run(jobs.save_event(ref, "INFO", "page 9", "start", None, None))
    sign_in(client, ADMIN)
    stuck = [e for e in client.get(f"/admin/api/books/{ref}").json()["events"] if e["stuck"]]
    assert [e["step"] for e in stuck] == ["page 9"]


def test_admin_sees_errors(client):
    client.post("/api/unlock", headers={"X-App-Password": "nope"})
    sign_in(client, ADMIN)
    data = client.get("/admin/api/errors").json()
    assert data["items"][0]["type"] == "wrong_password" and "wrong_password" in data["types"]


def test_model_switch_applies_to_the_admins_own_books_only(client, monkeypatch):
    sign_in(client, ADMIN)
    r = client.put("/admin/api/settings", json={"provider": "agnes", "model": "agnes-image-2.1-flash"})
    assert r.status_code == 200 and r.json()["quality"] == "1K"
    assert client.put("/admin/api/settings", json={"provider": "agnes", "model": "dall-e"}).status_code == 400
    monkeypatch.delenv("MOCK")
    admin_user = run(auth.upsert_user(f"sub-{ADMIN}", ADMIN))
    parent = run(auth.upsert_user(f"sub-{PARENT}", PARENT))
    assert run(admin.provider_for(admin_user)) == ("agnes", "agnes-image-2.1-flash", "1K")
    assert run(admin.provider_for(parent)) == ("openai", None, None)
    monkeypatch.setenv("MOCK", "1")  # the safety switch wins
    assert run(admin.provider_for(admin_user))[0] == "mock"


def test_privacy_page_names_who_to_contact(client):
    r = client.get("/privacy")
    assert r.status_code == 200 and f"mailto:{ADMIN}" in r.text and "OpenAI" in r.text and "{{" not in r.text


# --- reviews --------------------------------------------------------------------------------------

ANSWERS = {"looks_like_me": 4, "story_rings_true": 5, "looks_professional": 3, "not_good": "Page 2 hands look odd"}


def finished_book(client):
    ref = post_book(client).json()["id"]
    wait_for(client, ref)
    return ref


def test_owner_reviews_their_book_and_can_change_it(client):
    ref = finished_book(client)
    assert client.get(f"/api/books/{ref}/review").json() == {"review": None}
    assert client.put(f"/api/books/{ref}/review", json=ANSWERS).status_code == 200
    r = client.put(f"/api/books/{ref}/review", json={**ANSWERS, "looks_like_me": 2})
    assert r.json()["review"]["looks_like_me"] == 2
    assert client.get(f"/api/books/{ref}/review").json()["review"]["not_good"] == "Page 2 hands look odd"
    sign_in(client, ADMIN)
    data = client.get("/admin/api/reviews").json()
    assert data["count"] == 1 and data["people"] == 1  # updated, not counted twice
    assert data["questions"][0]["counts"] == [0, 1, 0, 0, 0] and data["questions"][1]["average"] == 5
    assert data["items"][0]["email"] == PARENT
    assert client.get(f"/admin/api/books/{ref}").json()["reviews"][0]["looks_like_me"] == 2


def test_only_the_owner_can_review(client):
    ref = finished_book(client)
    sign_in(client, "stranger@example.com")
    assert client.put(f"/api/books/{ref}/review", json=ANSWERS).status_code == 404
    client.cookies.clear()
    assert client.put(f"/api/books/{ref}/review", json=ANSWERS).status_code == 401


def test_scores_must_be_one_to_five(client):
    ref = finished_book(client)
    assert client.put(f"/api/books/{ref}/review", json={**ANSWERS, "looks_like_me": 6}).status_code == 422
    assert client.put(f"/api/books/{ref}/review", json={**ANSWERS, "participant_id": "a b<"}).status_code == 422


def test_every_review_question_is_required(client):
    ref = finished_book(client)
    for missing in ("looks_like_me", "story_rings_true", "looks_professional", "not_good"):
        answers = {k: v for k, v in ANSWERS.items() if k != missing}
        assert client.put(f"/api/books/{ref}/review", json=answers).status_code == 422, missing
    r = client.put(f"/api/books/{ref}/review", json={**ANSWERS, "not_good": "   "})
    assert r.status_code == 422 and r.json()["detail"]["reason"] == "missing_answer"


def test_crowd_participant_id_is_saved(client):
    ref = finished_book(client)
    client.put(f"/api/books/{ref}/review", json={**ANSWERS, "participant_id": "CR-12345"})
    sign_in(client, ADMIN)
    item = client.get("/admin/api/reviews").json()["items"][0]
    assert item["participant_id"] == "CR-12345" and item["source"] == "connect"


def test_admin_qr_code(client):
    sign_in(client, ADMIN)
    r = client.get("/admin/api/qr.svg?url=https://jack.graydates.com/")
    assert r.status_code == 200 and r.headers["content-type"].startswith("image/svg") and b"<svg" in r.content


def test_pdf_can_open_in_the_browser(client):
    ref = finished_book(client)
    assert client.get(f"/api/books/{ref}/pdf?inline=1").headers["content-disposition"].startswith("inline")


def test_one_review_per_person_across_their_books(client):
    first, second = finished_book(client), finished_book(client)
    client.put(f"/api/books/{first}/review", json=ANSWERS)
    shown = client.get(f"/api/books/{second}/review").json()["review"]
    assert shown["book_id"] == first  # the card on the second book shows what they already said
    client.put(f"/api/books/{second}/review", json={**ANSWERS, "looks_like_me": 1})
    sign_in(client, ADMIN)
    data = client.get("/admin/api/reviews").json()
    assert data["count"] == 1 and data["items"][0]["book_id"] == second and data["items"][0]["looks_like_me"] == 1


# --- the bookshelf --------------------------------------------------------------------------------

def test_bookshelf_lists_only_my_books_newest_first(client):
    older, newer = finished_book(client), finished_book(client)
    post_book(client, name=" ")  # refused: not a book, not on the shelf
    shelf = client.get("/api/my-books").json()["books"]
    assert [b["id"] for b in shelf] == [newer, older]
    assert shelf[0]["status"] == "done" and shelf[0]["cover_url"] and shelf[0]["child_name"] == "Sam"
    sign_in(client, "stranger@example.com")
    assert client.get("/api/my-books").json()["books"] == []
    client.cookies.clear()
    assert client.get("/api/my-books").status_code == 401
