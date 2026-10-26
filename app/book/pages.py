"""Page types. The story file names a type per page; PAGE_TYPES maps it to a class.

To add a page type: subclass Page, implement render(), register it in PAGE_TYPES.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from .cast import CastSheets
from .prompts import PromptBuilder
from .providers import PAGE_SIZE, ImageProvider
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


@dataclass
class RenderedPage:
    number: int
    kind: str
    image: bytes | None = None
    text: str = ""
    text_zone: str = "bottom"
    child: ChildInfo | None = None


class Page(ABC):
    def __init__(self, spec: PageSpec):
        self.spec = spec

    @abstractmethod
    async def render(self, ctx: BookContext) -> RenderedPage:
        ...


class IllustratedPage(Page):
    """Art from the cast's reference sheets, story text drawn on top later by the PDF layer."""

    async def render(self, ctx: BookContext) -> RenderedPage:
        image = await ctx.provider.edit(
            label=f"page {self.spec.number}",
            refs=ctx.sheets.refs(self.spec.cast),
            prompt=ctx.prompts.page(self.spec),
            size=PAGE_SIZE,
        )
        return RenderedPage(self.spec.number, "illustrated", image=image,
                            text=ctx.casting.fill(self.spec.text), text_zone=self.spec.text_zone)


class AboutMePage(Page):
    """Last page: the child's cartoon portrait, name and the details the uploader typed in. No API call."""

    async def render(self, ctx: BookContext) -> RenderedPage:
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
