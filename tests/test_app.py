"""Free offline tests: mock image provider, stubbed face detection, no OpenAI calls."""
import io
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from pypdf import PdfReader

import app.main
from app.book.cast import CastSheets, MissingSheetError
from app.book.pages import PAGE_TYPES, make_page
from app.book.prompts import PromptBuilder
from app.book.story import HERO, Casting, PageSpec, load_story
from app.book.styles import STYLES, Animated3DStyle, ArtStyle, get_style
from app.faces import PreparedPhoto

client = TestClient(app.main.app)
STORY = load_story()
PASSWORD = "test-password"


def jpeg(color="green", size=(800, 800)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "JPEG")
    return buf.getvalue()


def png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (512, 512), "tan").save(buf, "PNG")
    return buf.getvalue()


def prompts(gender="boy", style=None):
    return PromptBuilder(style or get_style(STORY.style), STORY, Casting(STORY, gender))


@pytest.fixture
def mock_book(monkeypatch):
    """Mock images, a fixed password, and a stubbed face check so the whole request runs offline."""
    monkeypatch.setenv("MOCK", "1")
    monkeypatch.setenv("APP_PASSWORD", PASSWORD)
    monkeypatch.setattr(app.main, "prepare", lambda data: PreparedPhoto(full_png=png(), face_png=png()))


def post_book(password=PASSWORD, **form):
    data = {"name": "Sam", "age": "7", "favourites": "dinosaurs", **form}
    headers = {"X-App-Password": password} if password else {}
    return client.post("/api/book", files={"photo": ("x.jpg", jpeg(), "image/jpeg")}, data=data, headers=headers)


# --- story file ---------------------------------------------------------------------------------

def test_story_has_three_illustrated_pages_then_about_me():
    assert [p.type for p in STORY.pages] == ["illustrated", "illustrated", "illustrated", "about_me"]


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


# --- password -------------------------------------------------------------------------------------

def test_wrong_password_is_refused(mock_book):
    assert post_book(password="nope").status_code == 401


def test_missing_password_is_refused(mock_book):
    assert post_book(password=None).status_code == 401


def test_real_mode_without_app_password_refuses(monkeypatch):
    monkeypatch.delenv("MOCK", raising=False)
    monkeypatch.delenv("APP_PASSWORD", raising=False)
    assert post_book(password="anything").status_code == 503


# --- the whole book -------------------------------------------------------------------------------

def test_book_is_a_pdf_with_story_text_and_about_me(mock_book):
    r = post_book(favourites="dinosaurs, pancakes", about="Loves climbing trees")
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    assert 'filename="JackAndTheBeanstalk.pdf"' in r.headers["content-disposition"]
    pages = PdfReader(io.BytesIO(r.content)).pages
    assert len(pages) == 4
    assert "nothing left to sell" in pages[0].extract_text()
    about = pages[-1].extract_text()
    assert "About Me" in about and "Sam" in about and "dinosaurs, pancakes" in about and "Loves climbing trees" in about


def test_jane_book_uses_jane(mock_book):
    r = post_book(gender="girl")
    assert "Jane and her mother" in PdfReader(io.BytesIO(r.content)).pages[0].extract_text()


def test_name_is_required(mock_book):
    assert post_book(name="  ").status_code == 400


def test_unknown_gender_is_rejected(mock_book):
    assert post_book(gender="dragon").status_code == 400


def test_rejects_photo_without_face(monkeypatch):
    monkeypatch.setenv("MOCK", "1")
    monkeypatch.setenv("APP_PASSWORD", PASSWORD)
    r = post_book()
    assert r.status_code == 422 and "face" in r.json()["detail"]


def test_adding_a_page_needs_no_code(mock_book, monkeypatch):
    extra = replace(STORY.pages[0], number=4, text="Page four.", text_zone="top")
    longer = replace(STORY, pages=STORY.pages[:3] + (extra,) + STORY.pages[3:])
    monkeypatch.setattr("app.book.builder.load_story", lambda: longer)
    assert len(PdfReader(io.BytesIO(post_book().content)).pages) == 5


def test_index_served():
    assert client.get("/").status_code == 200
