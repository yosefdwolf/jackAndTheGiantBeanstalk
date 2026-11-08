"""Draw a story's supporting characters' reference sheets ONCE and save them to assets/characters/<story>/.

    python -m scripts.make_character_sheets little_red_riding_hood          # only sheets that don't exist yet
    python -m scripts.make_character_sheets little_red_riding_hood wolf     # redo just these keys

They are the same in every book, so commit them. Costs about $0.04 per sheet. You can also save a sheet
you made in the OpenAI Playground to assets/characters/<story>/<key>.png instead.
"""
import asyncio
import sys

from dotenv import load_dotenv

load_dotenv()

from app.book.cast import SHEETS_DIR  # noqa: E402
from app.book.prompts import PromptBuilder  # noqa: E402
from app.book.providers import SHEET_SIZE, get_provider  # noqa: E402
from app.book.story import Casting, story_for  # noqa: E402
from app.book.styles import get_style  # noqa: E402


async def main(story_key: str, keys: list[str]) -> None:
    story = story_for(story_key)
    if story.key != story_key:
        raise SystemExit(f"No story file stories/{story_key}.yaml")
    prompts = PromptBuilder(get_style(story.style), story, Casting(story))
    provider = get_provider()
    folder = SHEETS_DIR / story.key
    folder.mkdir(parents=True, exist_ok=True)
    for key, character in story.characters.items():
        path = folder / f"{key}.png"
        if (keys and key not in keys) or (not keys and path.exists()):
            continue
        print(f"drawing {key} …")
        result = await provider.generate(f"{key} sheet", prompts.character_sheet(character), SHEET_SIZE)
        path.write_bytes(result.png)
        print(f"saved {path}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    asyncio.run(main(sys.argv[1], sys.argv[2:]))
