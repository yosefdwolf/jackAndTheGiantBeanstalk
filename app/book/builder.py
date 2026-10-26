"""Builds a whole book: hero sheet from the photo, every page in parallel, then the PDF.

One call per image and no retries. The hero sheet and the style wording are reused on every page,
which is what keeps the child (and the look) the same from page 1 to the last.
"""
import asyncio

from ..faces import PreparedPhoto
from .cast import CastSheets
from .pages import BookContext, ChildInfo, make_page
from .pdf import build_pdf
from .prompts import PromptBuilder
from .providers import SHEET_SIZE, ImageProvider, MockImageProvider, get_provider
from .story import Casting, Story, load_story
from .styles import get_style

PDF_NAME = "JackAndTheBeanstalk.pdf"


async def build_book(photo: PreparedPhoto, child: ChildInfo, gender: str = "boy",
                     story: Story | None = None, provider: ImageProvider | None = None) -> bytes:
    story = story or load_story()
    provider = provider or get_provider()
    casting = Casting(story, gender)
    prompts = PromptBuilder(get_style(story.style), story, casting)

    face_description = await provider.describe_face(photo.face_png)
    hero_sheet = await provider.edit("hero sheet", [("photo.png", photo.full_png)],
                                     prompts.hero_sheet(face_description), SHEET_SIZE)

    fallback = None
    if isinstance(provider, MockImageProvider):  # mock books work before the real sheets exist
        def fallback(key):
            return MockImageProvider._draw(f"{key} sheet", SHEET_SIZE, None, 0)
    ctx = BookContext(casting, prompts, provider, CastSheets(hero_sheet, fallback=fallback), child)

    pages = await asyncio.gather(*(make_page(spec).render(ctx) for spec in story.pages))
    return build_pdf(list(pages), story.title)
