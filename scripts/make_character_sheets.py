"""Draw the supporting characters' reference sheets ONCE and save them to assets/characters/.

    python -m scripts.make_character_sheets            # only sheets that don't exist yet
    python -m scripts.make_character_sheets mother     # redo just these keys

They are the same in every book, so commit them. Costs about $0.02 per sheet. You can also save a sheet
you made in the OpenAI Playground to assets/characters/<key>.png instead.
"""
import asyncio
import sys

from dotenv import load_dotenv

load_dotenv()

from app.book.cast import SHEETS_DIR  # noqa: E402
from app.book.prompts import PromptBuilder  # noqa: E402
from app.book.providers import SHEET_SIZE, get_provider  # noqa: E402
from app.book.story import Casting, load_story  # noqa: E402
from app.book.styles import get_style  # noqa: E402


async def main(keys: list[str]) -> None:
    story = load_story()
    prompts = PromptBuilder(get_style(story.style), story, Casting(story))
    provider = get_provider()
    SHEETS_DIR.mkdir(parents=True, exist_ok=True)
    for key, character in story.characters.items():
        path = SHEETS_DIR / f"{key}.png"
        if (keys and key not in keys) or (not keys and path.exists()):
            continue
        print(f"drawing {key} …")
        path.write_bytes(await provider.generate(f"{key} sheet", prompts.character_sheet(character), SHEET_SIZE))
        print(f"saved {path}")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
