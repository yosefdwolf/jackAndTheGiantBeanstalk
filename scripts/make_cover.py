"""Draw a story's library cover from the `cover:` section of its story file. One paid call (about 5 cents):

    python -m scripts.make_cover little_red_riding_hood     # writes static/themes/<theme>/art/cover.webp

The library shows it with the title set on top (the picture itself has no words). Commit the file.
"""
import asyncio
import io
import sys

from dotenv import load_dotenv

load_dotenv()

from PIL import Image  # noqa: E402

from app.book.prompts import NO_TEXT  # noqa: E402
from app.book.providers import OpenAIImageProvider  # noqa: E402
from app.book.story import ROOT, story_for  # noqa: E402
from app.book.styles import get_style  # noqa: E402


def cover_prompt(story) -> str:
    c = story.cover
    return "\n".join([
        f"Style: {get_style(story.style).description}",
        f"World: {story.world}",
        f"The front cover of a picture book, tall. {NO_TEXT}",
        f"Scene: {c['scene']} The hero wears {story.hero_outfit}.",
        f"Mood and light: {c.get('mood', '')}",
        f"Composition: {c.get('composition', '')}",
    ])


async def main(story_key: str) -> None:
    story = story_for(story_key)
    if story.key != story_key or not story.cover.get("scene"):
        raise SystemExit(f"stories/{story_key}.yaml needs a cover: section with a scene")
    result = await OpenAIImageProvider().generate("library cover", cover_prompt(story), "1024x1536")
    out = ROOT / "static" / "themes" / story.theme / "art" / "cover.webp"
    out.parent.mkdir(parents=True, exist_ok=True)
    img = Image.open(io.BytesIO(result.png)).convert("RGB")
    img.thumbnail((1600, 1600))
    img.save(out, "WEBP", quality=88, method=6)
    print(f"saved {out.relative_to(ROOT)}, ${result.cost:.3f}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    asyncio.run(main(sys.argv[1]))
