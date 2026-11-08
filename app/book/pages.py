"""Page types. The story file names a type per page; PAGE_TYPES maps it to a class.

A page works in two steps, so drawn images can be saved and reused (resume after a restart, rebuild
the PDF on download) without paying for them again:
  draw(ctx)            -> the image this page needs, or None if it needs no API call
  layout(ctx, image)   -> what the PDF puts on the page

To add a page type: subclass Page, implement both, register it in PAGE_TYPES.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from .cast import CastSheets
from .prompts import PromptBuilder
from .providers import PAGE_SIZE, ImageProvider, ImageResult
from .story import Casting, PageSpec


@dataclass
class ChildInfo:
    """What the uploader typed in, for the About Me page."""
    name: str
    details: list[tuple[str, str]] = field(default_factory=list)  # (label, value), in form order


@dataclass
class BookContext:
    casting: Casting
    prompts: PromptBuilder
    provider: ImageProvider
    sheets: CastSheets
    child: ChildInfo
    scenes: dict[int, bytes] = field(default_factory=dict)  # page -> its scene from the scene bible (scenes.py)


@dataclass
class RenderedPage:
    number: int
    kind: str
    image: bytes | None = None
    text: str = ""
    text_zone: str = "bottom"
    child: ChildInfo | None = None


class Page(ABC):
    needs_image = False

    def __init__(self, spec: PageSpec):
        self.spec = spec

    @property
    def label(self) -> str:
        return f"page {self.spec.number}"

    def prompt(self, ctx: BookContext) -> str | None:
        return None

    async def draw(self, ctx: BookContext) -> ImageResult | None:
        return None

    @abstractmethod
    def layout(self, ctx: BookContext, image: bytes | None) -> RenderedPage:
        ...


class IllustratedPage(Page):
    """Art from the cast's reference sheets, story text drawn on top by the PDF layer."""
    needs_image = True

    def on_scene(self, ctx) -> bool:
        """Drawn as the child added into the page's saved scene (every page with the hero on it)."""
        return self.spec.number in ctx.scenes

    def prompt(self, ctx):
        return ctx.prompts.on_scene(self.spec) if self.on_scene(ctx) else ctx.prompts.page(self.spec)

    def refs(self, ctx) -> list[tuple[str, bytes]]:
        if self.on_scene(ctx):
            return [("hero.png", ctx.sheets.hero_sheet), (f"scene-{self.spec.number}.png", ctx.scenes[self.spec.number])]
        return ctx.sheets.refs(self.spec.cast)

    async def draw(self, ctx):
        return await ctx.provider.edit(label=self.label, refs=self.refs(ctx), prompt=self.prompt(ctx), size=PAGE_SIZE)

    def layout(self, ctx, image):
        return RenderedPage(self.spec.number, "illustrated", image=image,
                            text=ctx.casting.fill(self.spec.text), text_zone=self.spec.text_zone)


class AboutMePage(Page):
    """Last page: the child's cartoon portrait, name and the details the uploader typed in. No API call."""

    def layout(self, ctx, image):
        return RenderedPage(self.spec.number, "about_me", image=ctx.sheets.hero_sheet, child=ctx.child)


PAGE_TYPES: dict[str, type[Page]] = {
    "illustrated": IllustratedPage,
    "about_me": AboutMePage,
}


def make_page(spec: PageSpec) -> Page:
    try:
        return PAGE_TYPES[spec.type](spec)
    except KeyError:
        raise ValueError(f"Page {spec.number} has unknown type {spec.type!r}. Known: {', '.join(PAGE_TYPES)}") from None
