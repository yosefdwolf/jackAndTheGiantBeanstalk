"""Page and click tracking (static/track.js -> /api/e) and the admin's Funnel tab."""
from app.db.models import PageEvent
from tests.test_books import ADMIN, PARENT, client, rows, run, sign_in  # noqa: F401


def send(client, name, visitor="v1visitor", session="s1session", path="/", headers=None, **props):
    r = client.post("/api/e", json={"name": name, "visitor": visitor, "session": session, "path": path,
                                     "props": props}, headers=headers or {})
    assert r.status_code == 204


def test_events_are_saved_without_anything_extra(client):
    client.cookies.clear()
    send(client, "click", path="/stories/jack?x=1#book=abc", target="download", name_typed="Alice")
    [e] = run(rows(PageEvent))
    assert (e.name, e.path, e.props, e.user_id) == ("click", "/stories/jack", {"target": "download"}, None)


def test_unknown_events_bots_and_do_not_track_are_dropped(client):
    send(client, "anything_else")
    send(client, "page_view", visitor="bad id!")
    send(client, "page_view", headers={"DNT": "1"})
    send(client, "page_view", headers={"Sec-GPC": "1"})
    send(client, "page_view", headers={"User-Agent": "Googlebot/2.1"})
    assert client.post("/api/e", content=b"not json").status_code == 204
    assert run(rows(PageEvent)) == []


def test_the_funnel_counts_people_through_each_step_in_order(client):
    client.cookies.clear()
    # Two visitors open a story; one adds a photo and gets a book; a third adds a photo before ever seeing a page.
    for v in ("aaaaaaaa1", "bbbbbbbb2"):
        send(client, "page_view", visitor=v)
        send(client, "page_view", visitor=v, path="/stories/jack")
    send(client, "photo_added", visitor="aaaaaaaa1", path="/stories/jack")
    send(client, "book_requested", visitor="aaaaaaaa1", path="/stories/jack")
    send(client, "book_ready", visitor="aaaaaaaa1", path="/stories/jack", fresh="1")
    send(client, "click", visitor="aaaaaaaa1", path="/stories/jack", target="download")
    send(client, "photo_added", visitor="cccccccc3", path="/stories/jack")
    send(client, "no_money", visitor="bbbbbbbb2", path="/stories/jack")

    sign_in(client, PARENT)
    assert client.get("/admin/api/funnel").status_code == 403
    sign_in(client, ADMIN)
    send(client, "page_view", visitor="dddddddd4")  # the admin's own visit is left out
    d = client.get("/admin/api/funnel").json()
    steps = {s["step"]: s["visitors"] for s in d["book_funnel"]}
    assert steps["Came to the site"] == 2 and steps["Opened a story"] == 2 and steps["Added a photo"] == 1
    assert steps["Got their book"] == 1 and steps["Read to the end"] == 0
    assert d["book_funnel"][2]["of_previous"] == 0.5
    assert d["visitors"] == 3 and d["new_visitors"] == 3 and d["signed_in"] == 0
    assert d["days"][0]["people"] == 3 and d["days"][0]["visits"] == 1  # every test event shares one session
    assert {"what": "Not enough money for a book", "times": 1} in d["blocked"]
    assert d["clicks"][0] == {"target": "download", "clicks": 1, "visitors": 1}
    assert client.get("/admin/api/funnel?admins=true").json()["visitors"] == 4


def test_the_admin_page_asks_for_the_latest_script(client):
    sign_in(client, ADMIN)
    html = client.get("/admin").text
    assert "/static/admin/admin.js?v=" in html and "/static/admin/admin.css?v=" in html
