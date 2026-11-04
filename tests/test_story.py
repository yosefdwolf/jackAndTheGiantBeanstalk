"""Story, prompt and character-sheet tests. Pure functions: no server, no database, no API calls."""
import io

import pytest
from PIL import Image

from app.book.cast import CastSheets, MissingSheetError
from app.book.pages import PAGE_TYPES, make_page
from app.book.prompts import PromptBuilder
from app.book.story import HERO, Casting, PageSpec, load_story
from app.book.styles import STYLES, Animated3DStyle, ArtStyle, get_style

STORY = load_story()


def png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (512, 512), "tan").save(buf, "PNG")
    return buf.getvalue()


def prompts(gender="boy", style=None):
    return PromptBuilder(style or get_style(STORY.style), STORY, Casting(STORY, gender))


# --- story file ---------------------------------------------------------------------------------

def test_story_has_twenty_story_pages_then_about_me():
    assert [p.type for p in STORY.pages] == ["illustrated"] * 20 + ["about_me"]


def test_every_cast_member_has_a_sheet_and_no_name_hides_inside_another():
    """A hen-only page must not read as if the giant were in it ("the giant's golden hen")."""
    names = [Casting(STORY).fill(c.name) for c in STORY.characters.values()]
    assert not [(a, b) for a in names for b in names if a != b and a in b]
    used = {k for p in STORY.pages for k in p.cast} - {"hero"}
    assert used <= set(STORY.characters)


def test_storyboard_text_is_exact():
    texts = [Casting(STORY).fill(p.text) for p in STORY.pages[:3]]
    assert texts == [
        "Jack and his mother had nothing left to sell but Milky-White.",
        "“Five magic beans,” said the old man. “For one cow.”",
        "“Beans!” she cried. And out the window they went.",
    ]


def test_every_page_type_in_the_story_is_registered():
    assert all(p.type in PAGE_TYPES for p in STORY.pages)


def test_unknown_page_type_is_rejected():
    with pytest.raises(ValueError):
        make_page(PageSpec(number=9, type="pop-up"))


def test_unknown_cast_member_is_rejected(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("title: T\nstyle: animated3d\nworld: w\nhero: {names: {boy: Jack, girl: Jane}, outfit: o}\n"
                   "characters: {}\npages: [{type: illustrated, cast: [giant]}]\n")
    with pytest.raises(ValueError, match="giant"):
        load_story(bad)


def test_jane_fills_name_and_pronouns():
    assert Casting(STORY, "girl").fill(STORY.pages[0].text) == \
        "Jane and her mother had nothing left to sell but Milky-White."


# --- prompts: one style, one hero sheet, only the cast --------------------------------------------

def test_style_wording_is_identical_in_every_call():
    pb, style = prompts(), get_style(STORY.style)
    calls = [pb.hero_sheet()] + [pb.page(p) for p in STORY.pages if p.type == "illustrated"] + \
            [pb.character_sheet(c) for c in STORY.characters.values()]
    assert all(style.description in c for c in calls)


def test_book_style_is_the_assignment_style():
    assert get_style(STORY.style).description == \
        "Modern 3D animated feature — rounded forms, large expressive eyes, soft rim light."


@pytest.mark.parametrize("spec", [p for p in STORY.pages if p.type == "illustrated"], ids=lambda p: f"page{p.number}")
def test_page_prompt_names_exactly_its_cast(spec):
    p = prompts().page(spec)
    only = p.split("Only these characters appear:")[1]
    for key, char in STORY.characters.items():
        name = Casting(STORY).fill(char.name)
        assert (name in only) == (key in spec.cast)
    assert "No other people or animals" in p


def test_page_three_has_no_cow():
    assert "milky_white" not in STORY.pages[2].cast
    assert "Milky-White" not in prompts().page(STORY.pages[2]).split("Only these characters appear:")[1]


def test_style_is_swappable():
    class Watercolour(ArtStyle):
        key = "watercolour"
        description = "Loose watercolour washes on rough paper."
        sheet_notes = "Soft edges."

    pb = prompts(style=Watercolour())
    assert "Loose watercolour washes" in pb.page(STORY.pages[0])
    assert Animated3DStyle().description not in pb.page(STORY.pages[0])
    assert isinstance(STYLES["animated3d"], ArtStyle)


# --- character sheets -----------------------------------------------------------------------------

def test_sheets_are_sent_in_cast_order(tmp_path):
    for key in ("mother", "milky_white"):
        (tmp_path / f"{key}.png").write_bytes(png())
    refs = CastSheets(b"hero", sheets_dir=tmp_path).refs((HERO, "mother", "milky_white"))
    assert [name for name, _ in refs] == ["hero.png", "mother.png", "milky_white.png"]
    assert refs[0][1] == b"hero"


def test_missing_sheet_fails_loudly_without_mock(tmp_path):
    with pytest.raises(MissingSheetError):
        CastSheets(b"hero", sheets_dir=tmp_path).get("mother")
