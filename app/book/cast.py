"""Reference sheets for one book: the hero's (made per upload) and the story's characters' (from the
character bible, app/book/bible.py)."""
from pathlib import Path

from .story import HERO, ROOT

SHEETS_DIR = ROOT / "assets" / "characters"  # optional hand-made sheets: assets/characters/<story key>/<key>.png


class MissingSheetError(RuntimeError):
    pass


class CastSheets:
    """Looks up the reference image for each cast key. The hero's sheet is set per book."""

    def __init__(self, hero_sheet: bytes, sheets: dict[str, bytes] | None = None):
        self.hero_sheet = hero_sheet
        self.sheets = sheets or {}

    def get(self, key: str) -> bytes:
        if key == HERO:
            return self.hero_sheet
        if key in self.sheets:
            return self.sheets[key]
        raise MissingSheetError(f"No character sheet for {key!r}.")

    def refs(self, cast: tuple[str, ...]) -> list[tuple[str, bytes]]:
        return [(f"{key}.png", self.get(key)) for key in cast]


def repo_sheet(story_key: str, key: str) -> Path:
    return SHEETS_DIR / story_key / f"{key}.png"
