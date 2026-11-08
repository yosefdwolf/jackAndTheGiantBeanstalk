"""Paint a story's website art ONCE (its backdrop and extras, described in its story file's look: section), or
the library's, in the books' own style, and save it to static/themes/<theme>/art/.

    python -m scripts.make_theme_art little_red_riding_hood            # a story's look: section, only missing images
    python -m scripts.make_theme_art jack_and_the_beanstalk cloud      # redo just these
    python -m scripts.make_theme_art library                           # the shared pages (library, bookshelf, wallet)

The art is the same for every visitor, so commit it. About $0.02–0.04 per image with gpt-image-2.5-flare.
"""
import asyncio
import base64
import io
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from openai import AsyncOpenAI  # noqa: E402
from PIL import Image  # noqa: E402

from app.book.story import load_story, story_for  # noqa: E402
from app.book.styles import get_style  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]

# Per theme: (name, size, transparent background, what to paint). Stories' art comes from their story files.
# The shared pages belong to every story: a cosy library that holds a hint of each one.
LIBRARY = [
    ("room-wide", "1536x1024", False,
     "A cosy, magical children's storybook library, as a wide website background. Tall warm wooden bookshelves "
     "full of colourful picture books run up the far left and far right edges. A big round window at the top "
     "centre shows a bright blue sky with a fluffy cloud. A soft red armchair with a knitted blanket in the "
     "lower left corner, a round rug, a little reading lamp glowing. Hints of fairy tales tucked on the "
     "shelves: a small glass jar of glowing magic beans, a tiny red hooded cape hanging from a hook, a little "
     "golden harp. Warm, golden afternoon light. Keep the whole middle of the picture as a calm, plain, softly "
     "lit cream wall with nothing on it, for cards to sit on."),
    ("room-tall", "1024x1536", False,
     "A cosy, magical children's storybook library, as a tall phone background. Warm wooden bookshelves full of "
     "colourful picture books along the left and right edges, a round window at the top showing blue sky and a "
     "cloud, a soft red armchair and a glowing reading lamp at the bottom. A small jar of glowing magic beans and "
     "a tiny red hooded cape on a hook tucked on the shelves. Warm golden light. Keep the whole middle as a "
     "calm, plain, softly lit cream wall with nothing on it."),
    ("purse", "1024x1024", True,
     "A cute, chunky storybook coin purse made of soft red leather with a golden clasp, slightly open, with a "
     "few shiny gold coins spilling out. Nothing else."),
    ("icon-stories", "1024x1024", True,
     "A cute little stack of three colourful storybooks, rounded and chunky, a small golden star on top. "
     "Nothing else."),
    ("icon-flip", "1024x1024", True,
     "A cute open picture book with its pages fanning as if being turned, rounded and chunky, a few tiny "
     "golden sparkles. Nothing else."),
]

def story_art(story) -> list[tuple[str, str, bool, str]]:
    """A story's art, from its story file's look: section: the backdrop (wide and tall), then any extras."""
    look = story.look or {}
    backdrop = look.get("backdrop") or {}
    art = [(f"scene-{shape}", size, False, backdrop[shape])
           for shape, size in (("wide", "1536x1024"), ("tall", "1024x1536")) if backdrop.get(shape)]
    art += [(a["name"], "1024x1024", bool(a.get("transparent")), " ".join(str(a["prompt"]).split()))
            for a in look.get("art") or []]
    return art


def to_webp(png: bytes, transparent: bool, max_side: int) -> bytes:
    img = Image.open(io.BytesIO(png))
    img = img.convert("RGBA" if transparent else "RGB")
    img.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    img.save(buf, "WEBP", quality=88, method=6)
    return buf.getvalue()


async def main(target: str, names: list[str]) -> None:
    if target == "library":
        style, theme, art = get_style(load_story().style), "library", LIBRARY  # every story shares the book style
    else:
        story = story_for(target)
        if story.key != target:
            raise SystemExit(f"No story file stories/{target}.yaml (or say `library`)")
        style, theme, art = get_style(story.style), story.theme, story_art(story)
    out = ROOT / "static" / "themes" / theme / "art"
    out.mkdir(parents=True, exist_ok=True)
    client = AsyncOpenAI(max_retries=0, timeout=180)
    model = os.getenv("IMAGE_MODEL", "gpt-image-2.5-flare")
    for name, size, transparent, what in art:
        path = out / f"{name}.webp"
        if (names and name not in names) or (not names and path.exists()):
            continue
        prompt = (f"{what}\nStyle: {style.description} Bright, warm, joyful colours for young children. "
                  "No text, letters or numbers anywhere.")
        if transparent:  # without this the model paints sky or a glow behind the object
            prompt += ("\nThe object is isolated on a fully transparent background: no sky, no clouds, no glow, "
                       "no shadow, no backdrop of any kind behind it.")
        extra = {"background": "transparent", "output_format": "png"} if transparent else {}
        print(f"painting {name} …", flush=True)
        resp = await client.images.generate(model=model, prompt=prompt, size=size, quality="medium", **extra)
        png = base64.b64decode(resp.data[0].b64_json)
        big = name.startswith(("scene", "room", "cover"))
        path.write_bytes(to_webp(png, transparent, 1600 if big else 900))
        has_alpha = Image.open(io.BytesIO(png)).mode in ("RGBA", "LA")
        print(f"saved {path.name} ({path.stat().st_size // 1024} KB, transparent={has_alpha})", flush=True)


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], sys.argv[2:]))
