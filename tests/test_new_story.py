"""Adding a story is adding a file: the template check, the library, and the character bible."""
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
    text = (STORIES / "little_red_riding_hood.yaml").read_text().replace("\ndraft: true", "\n# not a draft here")
    (tmp_path / "little_red_riding_hood.yaml").write_text(text)
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


def test_a_kept_picture_is_imported_instead_of_drawing(client, monkeypatch):
    monkeypatch.setattr(bible, "MockImageProvider", type("NotThis", (), {}))
    story = story_for("jack_and_the_beanstalk")  # its six sheets are kept in assets/characters/
    provider = CountingProvider()
    sheets = run(bible.sheets_for(story, builder(story), provider))
    assert provider.drawn == [] and sheets["mother"].startswith(b"\x89PNG")


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


def test_jacks_kept_pictures_are_imported_on_startup(client):
    run(bible.sync_stories())
    names = saved_names("jack_and_the_beanstalk")
    assert sorted(names) == ["giant-1", "golden_harp-1", "golden_hen-1", "milky_white-1", "mother-1", "old_man-1"]
    run(bible.sync_stories())  # only once
    assert len(saved_names("jack_and_the_beanstalk")) == 6


def test_a_draft_story_is_only_for_admins(client):
    from tests.test_books import ADMIN, PARENT, post_book, sign_in
    assert story_for("little_red_riding_hood").draft
    sign_in(client, PARENT)
    shelf = client.get("/").text
    assert "Little Red Riding Hood, still wrapped" in shelf and "/stories/little-red-riding-hood" not in shelf
    assert client.get("/stories/little-red-riding-hood").status_code == 404
    assert post_book(client, story="little-red-riding-hood").json()["detail"]["reason"] == "unknown_story"
    sign_in(client, ADMIN)
    assert "Draft: only admins see this" in client.get("/").text
    assert client.get("/stories/little-red-riding-hood").status_code == 200
