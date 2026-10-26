"""Reference sheets: the hero's (made per upload) and everyone else's (made once, kept in the repo)."""
from pathlib import Path

from .story import HERO, ROOT

SHEETS_DIR = ROOT / "assets" / "characters"


class MissingSheetError(RuntimeError):
    pass


class CastSheets:
    """Looks up the reference image for each cast key. The hero's sheet is set per book."""

    def __init__(self, hero_sheet: bytes, sheets_dir: Path = SHEETS_DIR, fallback=None):
        self.hero_sheet = hero_sheet
        self.sheets_dir = sheets_dir
        self.fallback = fallback  # callable(key) -> bytes, used by mock mode when a sheet is missing

    def path(self, key: str) -> Path:
        return self.sheets_dir / f"{key}.png"

    def get(self, key: str) -> bytes:
        if key == HERO:
            return self.hero_sheet
        path = self.path(key)
        if path.exists():
            return path.read_bytes()
        if self.fallback:
            return self.fallback(key)
        raise MissingSheetError(f"No character sheet for {key!r} at {path}. "
                                "Run `python -m scripts.make_character_sheets` once and commit the result.")

    def refs(self, cast: tuple[str, ...]) -> list[tuple[str, bytes]]:
        return [(f"{key}.png", self.get(key)) for key in cast]
