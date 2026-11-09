"""Adding a story is adding a file: the template check, the library, and the character bible."""
import shutil
import pytest
from sqlalchemy import select

from app.book import bible, story as story_mod
from app.book.prompts import PromptBuilder
from app.book.providers import ImageResult, MockImageProvider
from app.book.story import STORIES, Casting, all_stories, check_story, load_story, story_for
from app.book.styles import get_style
from app.db import session as db
from app.db.models import Book, CharacterPicture, StoryCharacter, StoryRow
from tests.test_books import client, run  # noqa: F401


@pytest.mark.parametrize("path", sorted(STORIES.glob("*.yaml")), ids=lambda p: p.stem)
def test_every_story_file_fits_the_template(path):
    assert check_story(load_story(path)) == []


@pytest.fixture
def stories(tmp_path, monkeypatch):
    """A stories folder of our own, starting with a copy of Little Red."""
    shutil.copy(STORIES / "little_red_riding_hood.yaml", tmp_path / "little_red_riding_hood.yaml")
    monkeypatch.setattr(story_mod, "STORIES", tmp_path)
    return tmp_path


def test_a_new_file_is_a_new_story_in_the_library(stories, client):
    text = (stories / "little_red_riding_hood.yaml").read_text().replace("title: Little Red Riding Hood",
                                                                         "title: The Brave Little Tailor")
    (stories / "brave_little_tailor.yaml").write_text(text)
    assert [s.title for s in all_stories()] == ["Little Red Riding Hood", "The Brave Little Tailor"]
    html = client.get("/").text
    assert "The Brave Little Tailor" in html and "/stories/brave-little-tailor" in html
    page = client.get("/stories/brave-little-tailor")
    assert page.status_code == 200 and "Are you a boy or a girl?" in page.text  # its own pronouns section


def test_a_broken_file_is_left_out_not_fatal(stories, client):
    (stories / "broken.yaml").write_text("title: [unclosed\n")
    text = (stories / "little_red_riding_hood.yaml").read_text().replace("text_zone: bottom-dark", "text_zone: top")
    (stories / "wrong_layout.yaml").write_text(text.replace("Little Red Riding Hood", "Wrong Layout"))
    assert [s.title for s in all_stories()] == ["Little Red Riding Hood"]
    assert client.get("/").status_code == 200


def test_jack_asks_jack_or_jane(client):
    assert "Jack or Jane?" in client.get("/stories/jack-and-the-beanstalk").text


class CountingProvider(MockImageProvider):
    """Draws like the mock, but counts as a real provider (so sheets are drawn and saved)."""
    name = "counting"

    def __init__(self):
        super().__init__()
        self.drawn = []

    async def generate(self, label, prompt, size):
        self.drawn.append(label)
        return ImageResult(f"PNG:{label}:{len(self.drawn)}".encode(), 0.04)  # every drawing is different


def builder(story):
    return PromptBuilder(get_style(story.style), story, Casting(story))


def test_characters_are_drawn_once_then_reused(client, monkeypatch):
    monkeypatch.setattr(bible, "MockImageProvider", type("NotThis", (), {}))  # treat CountingProvider as real
    story = story_for("little_red_riding_hood")
    provider = CountingProvider()
    first = run(bible.sheets_for(story, builder(story), provider))
    assert sorted(first) == ["grandmother", "mother", "wolf", "woodcutter"]
    assert sorted(provider.drawn) == ["grandmother sheet", "mother sheet", "wolf sheet", "woodcutter sheet"]
    again = run(bible.sheets_for(story, builder(story), provider))
    assert again == first and len(provider.drawn) == 4  # from the database, nothing new drawn

    async def saved():
        async with db.session() as s:
            return (await s.execute(select(CharacterPicture.source, CharacterPicture.name, StoryCharacter.key)
                                    .join(StoryCharacter, CharacterPicture.character_id == StoryCharacter.id)
                                    .join(StoryRow).where(StoryRow.key == story.key))).all()
    assert {r.key: r.source for r in run(saved())} == dict.fromkeys(first, "drawn")
    assert sorted(r.name for r in run(saved())) == ["grandmother-1", "mother-1", "wolf-1", "woodcutter-1"]


def with_wolf(story, **changes):
    """The story with the wolf's description or picture changed, as if the story file had been edited."""
    wolf = story.characters["wolf"]
    new = wolf.__class__(**{**wolf.__dict__, **changes})
    return story.__class__(**{**story.__dict__, "characters": {**story.characters, "wolf": new}})


def saved_names(story_key):
    async def go():
        async with db.session() as s:
            return (await s.execute(select(CharacterPicture.name)
                                    .join(StoryCharacter, CharacterPicture.character_id == StoryCharacter.id)
                                    .join(StoryRow).where(StoryRow.key == story_key)
                                    .order_by(CharacterPicture.id))).scalars().all()
    return run(go())


def test_changing_a_character_draws_a_new_version_and_keeps_the_old(client, monkeypatch):
    monkeypatch.setattr(bible, "MockImageProvider", type("NotThis", (), {}))
    story = story_for("little_red_riding_hood")
    provider = CountingProvider()
    run(bible.sheets_for(story, builder(story), provider))
    scarf = with_wolf(story, description=story.characters["wolf"].description + ", wearing a little blue scarf")
    sheets = run(bible.sheets_for(scarf, builder(scarf), provider))
    assert provider.drawn.count("wolf sheet") == 2 and provider.drawn.count("mother sheet") == 1
    assert "wolf-1" in saved_names(story.key) and "wolf-2" in saved_names(story.key)  # nothing replaced
    back = run(bible.sheets_for(story, builder(story), provider))  # the old description again: the old picture
    assert provider.drawn.count("wolf sheet") == 2 and back["wolf"] != sheets["wolf"]


def test_a_pinned_picture_wins_over_the_description(client, monkeypatch):
    monkeypatch.setattr(bible, "MockImageProvider", type("NotThis", (), {}))
    story = story_for("little_red_riding_hood")
    provider = CountingProvider()
    first = run(bible.sheets_for(story, builder(story), provider))
    scarf = with_wolf(story, description="a completely different wolf")
    run(bible.sheets_for(scarf, builder(scarf), provider))  # draws wolf-2
    pinned = with_wolf(scarf, picture="wolf-1")
    sheets = run(bible.sheets_for(pinned, builder(pinned), provider))
    assert sheets["wolf"] == first["wolf"] and provider.drawn.count("wolf sheet") == 2
    assert run(bible.choose(pinned, "wolf", builder(pinned))).why == "pinned"


def test_a_missing_pin_falls_back_to_the_description(client, monkeypatch):
    monkeypatch.setattr(bible, "MockImageProvider", type("NotThis", (), {}))
    story = with_wolf(story_for("little_red_riding_hood"), picture="wolf-99")
    provider = CountingProvider()
    run(bible.sheets_for(story, builder(story), provider))
    assert "wolf sheet" in provider.drawn


def test_the_admin_sees_every_version(client, monkeypatch):
    monkeypatch.setattr(bible, "MockImageProvider", type("NotThis", (), {}))
    story = story_for("little_red_riding_hood")
    run(bible.sheets_for(story, builder(story), CountingProvider()))
    from tests.test_books import ADMIN, sign_in
    sign_in(client, ADMIN)
    red = next(st for st in client.get("/admin/api/characters").json() if st["key"] == story.key)
    wolf = next(c for c in red["characters"] if c["key"] == "wolf")
    assert wolf["in_use"] == "wolf-1" and wolf["why"] == "matches the description"
    assert [v["name"] for v in wolf["versions"]] == ["wolf-1"]


@pytest.fixture
def kept(tmp_path, monkeypatch):
    """A folder of pictures someone put in the repo by hand: Jack's mother and giant."""
    from app.book import cast
    from tests.test_story import png
    folder = tmp_path / "characters" / "jack_and_the_beanstalk"
    folder.mkdir(parents=True)
    for key in ("mother", "giant"):
        (folder / f"{key}.png").write_bytes(png())
    monkeypatch.setattr(cast, "SHEETS_DIR", tmp_path / "characters")
    return folder


def test_a_kept_picture_is_imported_instead_of_drawing(client, monkeypatch, kept):
    monkeypatch.setattr(bible, "MockImageProvider", type("NotThis", (), {}))
    story = story_for("jack_and_the_beanstalk")
    provider = CountingProvider()
    sheets = run(bible.sheets_for(story, builder(story), provider))
    assert "mother sheet" not in provider.drawn and "giant sheet" not in provider.drawn
    assert sheets["mother"].startswith(b"\x89PNG") and "milky_white sheet" in provider.drawn


def test_startup_mirrors_the_story_files_into_the_tables(stories, client):
    from app.book.jobs import create_book
    run(create_book("oldbook1", story_key="little_red_riding_hood", gender="girl", child_name="Ann", details=[],
                    provider="mock", model=None, quality=None))
    async def unlink():  # as if made before books had a story_id
        async with db.session() as s:
            (await s.get(Book, "oldbook1")).story_id = None
            await s.commit()
    run(unlink())
    (stories / "brave_little_tailor.yaml").write_text(
        (stories / "little_red_riding_hood.yaml").read_text().replace("Little Red Riding Hood", "The Brave Little Tailor"))
    run(bible.sync_stories())

    async def rows():
        async with db.session() as s:
            st = {r.key: r for r in (await s.execute(select(StoryRow))).scalars()}
            cast = (await s.execute(select(StoryCharacter.key).join(StoryRow)
                                    .where(StoryRow.key == "brave_little_tailor"))).scalars().all()
            book = await s.get(Book, "oldbook1")
            return st, sorted(cast), book.story_id
    st, cast, book_story = run(rows())
    assert st["brave_little_tailor"].active and st["brave_little_tailor"].title == "The Brave Little Tailor"
    assert cast == ["grandmother", "mother", "wolf", "woodcutter"]
    assert book_story == st["little_red_riding_hood"].id

    (stories / "brave_little_tailor.yaml").unlink()  # the file is removed: its story stays, inactive
    run(bible.sync_stories())
    st, _, _ = run(rows())
    assert not st["brave_little_tailor"].active and st["little_red_riding_hood"].active


def test_kept_pictures_are_imported_on_startup(client, kept):
    run(bible.sync_stories())
    assert sorted(saved_names("jack_and_the_beanstalk")) == ["giant-1", "mother-1"]
    run(bible.sync_stories())  # only once
    assert len(saved_names("jack_and_the_beanstalk")) == 2


def upload(client, key="wolf", data=None):
    from tests.test_story import png
    return client.post(f"/admin/api/characters/little_red_riding_hood/{key}/picture",
                       files={"photo": ("wolf.jpg", data or png(), "image/png")})


def test_uploading_a_picture_adds_a_version_books_use(client, monkeypatch):
    from tests.test_books import ADMIN, PARENT, sign_in
    monkeypatch.setattr(bible, "MockImageProvider", type("NotThis", (), {}))
    story = story_for("little_red_riding_hood")
    run(bible.sheets_for(story, builder(story), CountingProvider()))  # wolf-1, drawn
    sign_in(client, PARENT)
    assert upload(client).status_code == 403
    sign_in(client, ADMIN)
    r = upload(client)
    assert r.status_code == 200 and r.json() == {"name": "wolf-2", "in_use": True, "note": None}
    assert saved_names(story.key).count("wolf-1") == 1  # the old one is kept
    provider = CountingProvider()
    sheets = run(bible.sheets_for(story, builder(story), provider))
    assert sheets["wolf"].startswith(b"\x89PNG") and provider.drawn == []  # the upload, nothing redrawn
    assert upload(client, data=b"not a picture").status_code == 400
    assert upload(client, key="dragon").status_code == 404


def test_an_upload_doesnt_beat_a_pin(client, monkeypatch, stories):
    from tests.test_books import ADMIN, sign_in
    monkeypatch.setattr(bible, "MockImageProvider", type("NotThis", (), {}))
    path = stories / "little_red_riding_hood.yaml"
    run(bible.sheets_for(story_for("little_red_riding_hood"), builder(story_for("little_red_riding_hood")),
                         CountingProvider()))
    path.write_text(path.read_text().replace("    name: the wolf\n", "    name: the wolf\n    picture: wolf-1\n"))
    sign_in(client, ADMIN)
    r = upload(client).json()
    assert r["in_use"] is False and "pins wolf-1" in r["note"]


def test_a_draft_story_is_only_for_admins(client, stories):
    from tests.test_books import ADMIN, PARENT, post_book, sign_in
    path = stories / "little_red_riding_hood.yaml"
    path.write_text(path.read_text().replace("title: Little Red Riding Hood\n", "title: Little Red Riding Hood\ndraft: true\n"))
    assert story_for("little_red_riding_hood").draft
    sign_in(client, PARENT)
    shelf = client.get("/").text
    assert "Little Red Riding Hood, still wrapped" in shelf and "/stories/little-red-riding-hood" not in shelf
    assert client.get("/stories/little-red-riding-hood").status_code == 404
    assert post_book(client, story="little-red-riding-hood").json()["detail"]["reason"] == "unknown_story"
    sign_in(client, ADMIN)
    assert "Draft: only admins see this" in client.get("/").text
    assert client.get("/stories/little-red-riding-hood").status_code == 200


def test_the_admin_can_draw_a_character_now(client):
    from tests.test_books import ADMIN, PARENT, sign_in
    sign_in(client, PARENT)
    assert client.post("/admin/api/characters/little_red_riding_hood/wolf/draw").status_code == 403
    sign_in(client, ADMIN)
    first = client.post("/admin/api/characters/little_red_riding_hood/wolf/draw").json()
    again = client.post("/admin/api/characters/little_red_riding_hood/wolf/draw").json()
    assert (first["name"], again["name"]) == ("wolf-1", "wolf-2") and again["in_use"]
    assert client.post("/admin/api/characters/little_red_riding_hood/dragon/draw").status_code == 404


def test_a_story_page_wears_its_look(client):
    red = client.get("/stories/little-red-riding-hood").text
    assert "/static/themes/story/theme.css" in red and "--accent: #d6322b;" in red
    assert '--scene-wide: url("/static/themes/red/art/scene-wide.webp");' in red
    assert '--bar-tip: url("/static/themes/red/art/bar-tip.webp");' in red
    jack = client.get("/stories/jack-and-the-beanstalk").text
    assert "/static/themes/jack/theme.css" in jack and "--scene-wide" not in jack


def test_a_bad_colour_is_caught(stories):
    path = stories / "little_red_riding_hood.yaml"
    path.write_text(path.read_text().replace('accent: "#d6322b"', 'accent: "red; } body { display: none"'))
    assert any("accent must be a colour" in p for p in check_story(load_story(path)))


@pytest.fixture
def scenes_on(monkeypatch):
    from app.book import jobs
    monkeypatch.setattr(jobs, "USE_SCENES", True)


def test_pages_are_drawn_on_their_scene_and_scenes_see_earlier_scenes(client, scenes_on):
    from tests.test_books import ADMIN, post_book, rows, sign_in, wait_for
    from app.db.models import BookImage, Scene
    sign_in(client, ADMIN)
    ref = post_book(client, story="little-red-riding-hood").json()["id"]
    assert wait_for(client, ref, timeout=30)["status"] == "done"
    pages = {i.page_number: i for i in run(rows(BookImage, book_id=ref)) if i.kind == "page"}
    assert pages[13].refs == ["hero", "scene-13"] and "Image 2 is this page's finished scene" in pages[13].prompt
    assert pages[8].refs == ["wolf"]  # no hero: the whole page, shared by every book
    saved = {r.page_number: r for r in run(rows(Scene, story_key="little_red_riding_hood"))}
    assert sorted(saved) == [n for n in range(1, 21) if n not in (8, 9, 10)]  # a scene for each page with the hero
    assert "Image 2 is the scene of page 12" in saved[13].prompt  # page 13's scene was drawn from page 12's
    assert "do NOT draw the hero" in saved[1].prompt and "Little Red" not in saved[1].prompt


def test_a_second_book_reuses_every_scene(client, scenes_on):
    from tests.test_books import ADMIN, post_book, rows, sign_in, wait_for
    from app.db.models import BookEvent, Scene
    sign_in(client, ADMIN)
    first = post_book(client, story="little-red-riding-hood").json()["id"]
    wait_for(client, first, timeout=30)
    second = post_book(client, story="little-red-riding-hood", gender="girl", name="Ann").json()["id"]
    assert wait_for(client, second, timeout=30)["status"] == "done"
    assert len(run(rows(Scene, story_key="little_red_riding_hood"))) == 17  # a girl's book drew no new scenes
    assert not [e for e in run(rows(BookEvent, book_id=second)) if e.step.startswith("scene")]


def test_seeing_a_later_page_is_caught(stories):
    path = stories / "little_red_riding_hood.yaml"
    path.write_text(path.read_text().replace("see_pages: [12]", "see_pages: [14]"))
    assert any("see_pages 14 must be an earlier" in p for p in check_story(load_story(path)))


def test_pages_without_the_hero_are_drawn_once_and_reused(client):
    from tests.test_books import ADMIN, post_book, rows, sign_in, wait_for
    from app.db.models import BookImage, SharedPage
    sign_in(client, ADMIN)
    first = post_book(client, story="little-red-riding-hood").json()["id"]
    assert wait_for(client, first, timeout=30)["status"] == "done"
    second = post_book(client, story="little-red-riding-hood", name="Ann", gender="girl").json()["id"]
    assert wait_for(client, second, timeout=30)["status"] == "done"
    assert sorted(r.page_number for r in run(rows(SharedPage))) == [8, 9, 10]  # the wolf and Grandmother alone
    a = {i.page_number: i for i in run(rows(BookImage, book_id=first)) if i.kind == "page"}
    b = {i.page_number: i for i in run(rows(BookImage, book_id=second)) if i.kind == "page"}
    assert all(b[n].image == a[n].image for n in (8, 9, 10))  # the very same pictures
    from app.db.models import BookEvent
    reused = sorted(e.step for e in run(rows(BookEvent, book_id=second)) if e.event == "reused")
    assert reused == ["page 10", "page 8", "page 9"]  # only those three; every page with the hero is drawn
    assert not [e for e in run(rows(BookEvent, book_id=first)) if e.event == "reused"]


def test_words_move_off_a_face(client):
    import io as _io
    from PIL import Image
    from pillow_heif import register_heif_opener
    from app.faces import choose_zone
    register_heif_opener()
    face = Image.open(STORIES.parent / "tests" / "fixtures" / "photo.heic").convert("RGB")
    face.thumbnail((340, 340))

    def page(at_bottom):
        img = Image.new("RGB", (1536, 1024), "#bfe0f5")
        img.paste(face, (600, 1024 - face.height - 20 if at_bottom else 20))
        buf = _io.BytesIO()
        img.save(buf, "PNG")
        return buf.getvalue()
    assert choose_zone(page(at_bottom=True), "bottom") == "top"     # a face where the words go: they move up
    assert choose_zone(page(at_bottom=False), "bottom") == "bottom"  # the face is up top: words stay
    assert choose_zone(page(at_bottom=False), "top") == "bottom"


def test_trying_a_page_keeps_each_try(client, scenes_on):
    from tests.test_books import ADMIN, PARENT, post_book, sign_in, wait_for
    sign_in(client, ADMIN)
    assert client.post("/admin/api/trials", json={"story": "little_red_riding_hood", "page": 12}).status_code == 400
    ref = post_book(client, story="little-red-riding-hood").json()["id"]  # a finished book gives the child
    wait_for(client, ref, timeout=30)
    for how in ("swap", "baseline"):
        r = client.post("/admin/api/trials", json={"story": "little_red_riding_hood", "page": 12, "how": how})
        assert r.status_code == 200 and client.get(r.json()["url"]).status_code == 200
    tries = client.get("/admin/api/trials?story=little_red_riding_hood").json()
    assert [t["how"] for t in tries] == ["baseline", "swap"] and all(t["book"] == ref for t in tries)
    sign_in(client, PARENT)
    assert client.post("/admin/api/trials", json={"story": "little_red_riding_hood", "page": 12}).status_code == 403



def test_without_scenes_pages_are_drawn_whole(client):
    from tests.test_books import ADMIN, post_book, rows, sign_in, wait_for
    from app.db.models import BookImage, Scene
    sign_in(client, ADMIN)
    ref = post_book(client, story="little-red-riding-hood").json()["id"]
    assert wait_for(client, ref, timeout=30)["status"] == "done"
    pages = {i.page_number: i for i in run(rows(BookImage, book_id=ref)) if i.kind == "page"}
    assert pages[12].refs == ["hero", "wolf"] and run(rows(Scene)) == []


def test_a_page_with_an_extra_child_is_drawn_again(client, monkeypatch):
    from tests.test_books import ADMIN, post_book, rows, sign_in, wait_for
    from app.book.providers import MockImageProvider
    from app.db.models import BookEvent, BookImage
    calls = []
    original = MockImageProvider.edit

    async def edit(self, label, refs, prompt, size):
        calls.append(label)
        return await original(self, label, refs, prompt, size)

    async def look_counting(self, png, who="", focus=""):  # page 5's first try shows two children
        label_tries = calls.count("page 5")
        two = calls and calls[-1] == "page 5" and label_tries == 1
        return {"faces": [{"top": 0.75, "bottom": 0.9, "left": 0.4, "right": 0.5}], "children": 2 if two else 1}
    monkeypatch.setattr(MockImageProvider, "edit", edit)
    monkeypatch.setattr(MockImageProvider, "look_at_page", look_counting)
    from app.book import jobs
    monkeypatch.setattr(jobs, "IMAGE_CONCURRENCY", 1)  # one at a time, so "the last picture" is page 5's
    sign_in(client, ADMIN)
    ref = post_book(client).json()["id"]
    assert wait_for(client, ref, timeout=30)["status"] == "done"
    assert calls.count("page 5") == 2  # redrawn once
    events = [e for e in run(rows(BookEvent, book_id=ref)) if e.event == "picture check failed"]
    assert [e.step for e in events] == ["page 5"] and events[0].fields["problem"] == "2 children, expected 1"
    pages = {i.page_number: i for i in run(rows(BookImage, book_id=ref)) if i.kind == "page"}
    assert pages[5].attempts == 2
    # a face low on the page sends the words up: page 1's words were at the bottom in the story file
    assert pages[1].text_zone == "top"


def test_words_go_where_no_face_is():
    from app.faces import zone_clear_of
    low = [{"top": 0.7, "bottom": 0.85, "left": 0.4, "right": 0.5}]
    high = [{"top": 0.1, "bottom": 0.25, "left": 0.4, "right": 0.5}]
    assert zone_clear_of(low, "bottom") == "top" and zone_clear_of(low, "top") == "top"
    assert zone_clear_of(high, "top") == "bottom" and zone_clear_of(high, "bottom") == "bottom"
    assert zone_clear_of(low + high, "bottom") == "bottom-small"  # neither end clear: the strip covering less face
    edges = [{"top": 0.3, "bottom": 0.45}, {"top": 0.55, "bottom": 0.75}]
    assert zone_clear_of(edges, "top") == "top-small"  # the thirds hold faces, but a thin strip misses them
    crowded = [{"top": 0.05, "bottom": 0.3}, {"top": 0.75, "bottom": 0.95}]
    assert zone_clear_of(crowded, "bottom") == "top-small"  # neither strip clear: the one covering less face
    assert zone_clear_of([], "bottom-dark") == "bottom-dark"


def test_a_rate_limit_is_waited_out_not_counted_as_a_try(client, monkeypatch):
    import httpx
    import openai
    from tests.test_books import ADMIN, post_book, rows, sign_in, wait_for
    from app.book import jobs
    from app.book.providers import MockImageProvider
    from app.db.models import BookImage
    original, refused = MockImageProvider.edit, []

    async def edit(self, label, refs, prompt, size):
        if label == "page 3" and not refused:
            refused.append(label)
            response = httpx.Response(429, headers={"retry-after": "1"}, request=httpx.Request("POST", "http://x"))
            raise openai.RateLimitError("slow down", response=response, body=None)
        return await original(self, label, refs, prompt, size)
    monkeypatch.setattr(MockImageProvider, "edit", edit)
    sign_in(client, ADMIN)
    ref = post_book(client).json()["id"]
    assert wait_for(client, ref, timeout=30)["status"] == "done" and refused == ["page 3"]
    page3 = next(i for i in run(rows(BookImage, book_id=ref)) if i.kind == "page" and i.page_number == 3)
    assert page3.attempts == 1  # waiting for the rate limit didn't use up a try


def test_faces_at_both_ends_draw_the_page_again(client, monkeypatch):
    from tests.test_books import ADMIN, post_book, rows, sign_in, wait_for
    from app.book import jobs
    from app.book.providers import MockImageProvider
    from app.db.models import BookEvent, BookImage
    prompts = []
    original = MockImageProvider.edit

    async def edit(self, label, refs, prompt, size):
        if label == "page 7":
            prompts.append(prompt)
        return await original(self, label, refs, prompt, size)

    async def look(self, png, who="", focus=""):  # page 7's first try has the giant's face up top and the hero's down low
        crowded = len(prompts) == 1 and self._last == "page 7"
        faces = [{"top": 0.05, "bottom": 0.25, "left": 0.2, "right": 0.4}]
        if crowded:
            faces.append({"top": 0.75, "bottom": 0.9, "left": 0.6, "right": 0.7})
        return {"faces": faces, "children": 1}
    original_edit = edit

    async def edit_tracking(self, label, refs, prompt, size):
        self._last = label
        return await original_edit(self, label, refs, prompt, size)
    monkeypatch.setattr(MockImageProvider, "edit", edit_tracking)
    monkeypatch.setattr(MockImageProvider, "look_at_page", look)
    monkeypatch.setattr(jobs, "IMAGE_CONCURRENCY", 1)
    sign_in(client, ADMIN)
    ref = post_book(client).json()["id"]
    assert wait_for(client, ref, timeout=30)["status"] == "done"
    assert len(prompts) == 2 and "Important: keep every face" not in prompts[0]
    assert "keep every face, of people and of animals, completely out of the top third" in prompts[1]
    failed = [e for e in run(rows(BookEvent, book_id=ref)) if e.event == "picture check failed"]
    assert [(e.step, e.fields["problem"]) for e in failed] == [("page 7", "faces at both ends of the page, where the words go")]
    page7 = next(i for i in run(rows(BookImage, book_id=ref)) if i.kind == "page" and i.page_number == 7)
    assert page7.text_zone == "bottom"  # the redraw's only face is up top, so the words go below
    looked = [e for e in run(rows(BookEvent, book_id=ref)) if e.event == "looked" and e.step == "page 7"]
    assert looked and looked[0].fields["faces"] == "0.05-0.25 0.75-0.90"


def test_words_stay_off_what_the_page_is_about():
    from app.faces import zone_clear_of
    from app.book.story import story_for
    axe = [{"top": 0.1, "bottom": 0.3, "left": 0.3, "right": 0.6}]  # up top, where page 19's words would go
    assert zone_clear_of([], "top", axe) == "bottom"
    assert zone_clear_of([{"top": 0.4, "bottom": 0.55}], "top", axe) == "bottom"
    tall = [{"top": 0.0, "bottom": 1.0, "left": 0.4, "right": 0.6}]  # the whole beanstalk: no end is clear of it
    assert zone_clear_of([{"top": 0.75, "bottom": 0.9}], "bottom", tall) == "top"  # faces still decide
    pages = {p.number: p for p in story_for("jack_and_the_beanstalk").pages}
    assert pages[19].focus == "the axe biting into the beanstalk"


def test_faces_at_both_ends_get_one_redraw_then_the_words_move(client, monkeypatch):
    from tests.test_books import ADMIN, post_book, rows, sign_in, wait_for
    from app.book.providers import MockImageProvider
    from app.db.models import BookEvent, BookImage
    both_ends = [{"top": 0.05, "bottom": 0.25, "left": 0.2, "right": 0.4},
                 {"top": 0.75, "bottom": 0.9, "left": 0.6, "right": 0.7}]

    async def look(self, png, who="", focus=""):  # every try of every page: faces up top and down low
        return {"faces": both_ends, "things": [], "children": None}
    monkeypatch.setattr(MockImageProvider, "look_at_page", look)
    sign_in(client, ADMIN)
    ref = post_book(client).json()["id"]
    assert wait_for(client, ref, timeout=30)["status"] == "done"
    page7 = next(i for i in run(rows(BookImage, book_id=ref)) if i.kind == "page" and i.page_number == 7)
    assert page7.attempts == 2  # one redraw, not two
    moved = [e for e in run(rows(BookEvent, book_id=ref)) if e.event == "words moved" and e.step == "page 7"]
    assert len(moved) == 1 and page7.text_zone == "bottom-small"  # less face in the bottom strip
    pdf = client.get(f"/api/books/{ref}/pdf")  # smaller words in a thin strip
    assert pdf.status_code == 200 and pdf.headers["content-type"] == "application/pdf"


def test_no_retry_starts_without_time_to_finish(client, monkeypatch):
    from tests.test_books import ADMIN, post_book, rows, sign_in, wait_for
    from app.book import jobs
    from app.book.providers import MockImageProvider
    from app.db.models import BookEvent, BookImage

    async def look(self, png, who="", focus=""):  # every page fails its check
        return {"faces": [], "things": [], "children": 3}
    monkeypatch.setattr(MockImageProvider, "look_at_page", look)
    monkeypatch.setattr(jobs, "PICTURES_DONE_BY", 0)  # the deadline has passed as soon as the book starts
    sign_in(client, ADMIN)
    ref = post_book(client).json()["id"]
    assert wait_for(client, ref, timeout=30)["status"] == "done"
    pages = [i for i in run(rows(BookImage, book_id=ref)) if i.kind == "page"]
    assert pages and all(i.attempts == 1 and i.image for i in pages)  # each kept its first try
    late = [e for e in run(rows(BookEvent, book_id=ref)) if e.event == "out of time"]
    assert len(late) == len(pages)


def test_a_second_look_can_find_a_clear_end_without_a_redraw(client, monkeypatch):
    from tests.test_books import ADMIN, post_book, rows, sign_in, wait_for
    from app.book import jobs
    from app.book.providers import MockImageProvider
    from app.db.models import BookEvent, BookImage
    looks = []

    async def look(self, png, who="", focus=""):  # page 8's first look boxes the giant's feet as a face
        looks.append(png)
        giant = {"who": "giant", "top": 0.15, "bottom": 0.3, "left": 0.4, "right": 0.6}
        feet = {"who": "giant", "top": 0.7, "bottom": 0.85, "left": 0.4, "right": 0.6}
        first = looks.count(png) == 1 and self._last == "page 8"
        return {"faces": [giant, feet] if first else [giant], "things": [], "children": 1}
    original = MockImageProvider.edit

    async def edit(self, label, refs, prompt, size):
        self._last = label
        return await original(self, label, refs, prompt, size)
    monkeypatch.setattr(MockImageProvider, "edit", edit)
    monkeypatch.setattr(MockImageProvider, "look_at_page", look)
    monkeypatch.setattr(jobs, "IMAGE_CONCURRENCY", 1)
    sign_in(client, ADMIN)
    ref = post_book(client).json()["id"]
    assert wait_for(client, ref, timeout=30)["status"] == "done"
    page8 = next(i for i in run(rows(BookImage, book_id=ref)) if i.kind == "page" and i.page_number == 8)
    assert page8.attempts == 1 and page8.text_zone == "bottom"  # no redraw; the words stay on the picture
    events = [e for e in run(rows(BookEvent, book_id=ref)) if e.step == "page 8"]
    assert [e.event for e in events if e.event.startswith("looked")] == ["looked", "looked again"]
    first = next(e for e in events if e.event == "looked")
    assert first.fields["faces"] == "giant 0.15-0.30 giant 0.70-0.85"  # each box says what it is


def test_a_page_saved_with_the_old_paper_layout_uses_the_story_files_place(client):
    from tests.test_books import ADMIN, post_book, rows, sign_in, wait_for
    from app.db.models import BookImage
    from app.db.session import session
    from sqlalchemy import update
    sign_in(client, ADMIN)
    ref = post_book(client).json()["id"]
    assert wait_for(client, ref, timeout=30)["status"] == "done"

    async def paper():
        async with session() as s:
            await s.execute(update(BookImage).where(BookImage.book_id == ref, BookImage.page_number == 8)
                            .values(text_zone="paper"))
            await s.commit()
    run(paper())
    pages = {p["number"]: p for p in client.get(f"/api/books/{ref}").json()["book"]["pages"] if p.get("number")}
    assert pages[8]["text_zone"] == "bottom"  # page 8's place in the story file
    assert client.get(f"/api/books/{ref}/pdf").status_code == 200


def test_an_admin_can_place_a_finished_books_words_again(client, monkeypatch):
    from tests.test_books import ADMIN, post_book, rows, sign_in, wait_for
    from app.book.providers import MockImageProvider
    from app.db.models import BookEvent, BookImage
    sign_in(client, ADMIN)
    ref = post_book(client).json()["id"]
    assert wait_for(client, ref, timeout=30)["status"] == "done"
    page20 = next(i for i in run(rows(BookImage, book_id=ref)) if i.kind == "page" and i.page_number == 20)
    assert page20.text_zone == "bottom"

    async def look(self, png, who="", focus=""):  # now the check sees a face low on every page
        assert "the hero" in who
        return {"faces": [{"who": "Jack", "top": 0.7, "bottom": 0.85}], "things": [], "children": 1}
    monkeypatch.setattr(MockImageProvider, "look_at_page", look)
    r = client.post(f"/admin/api/books/{ref}/words")
    assert r.status_code == 200
    body = r.json()
    p20 = next(p for p in body["pages"] if p["page"] == 20)
    assert p20 == {"page": 20, "was": "bottom", "now": "top"} and body["moved"] >= 1
    page20 = next(i for i in run(rows(BookImage, book_id=ref)) if i.kind == "page" and i.page_number == 20)
    assert page20.text_zone == "top"
    assert any(e.event == "words placed again" for e in run(rows(BookEvent, book_id=ref)))
    assert client.post("/admin/api/books/nope/words").status_code == 404
