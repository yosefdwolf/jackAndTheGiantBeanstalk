"""Paint a story theme's website art ONCE, in the book's own style, and save it to static/themes/<theme>/art/.

    python -m scripts.make_theme_art              # only images that don't exist yet
    python -m scripts.make_theme_art cloud beans  # redo just these

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

from app.book.story import load_story  # noqa: E402
from app.book.styles import get_style  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]

# (name, size, transparent background, what to paint)
ART = [
    ("scene-wide", "1536x1024", False,
     "A wide, cheerful storybook landscape for a children's website background. A bright soft daytime sky with "
     "a few fluffy clouds. Rolling bright green hills along the bottom with wildflowers. A small cosy thatched "
     "cottage with a red door on the lower left. A giant magic beanstalk curls up the far left edge into the "
     "clouds. A tiny fairy-tale castle sits on a cloud at the top right. Keep the whole centre of the picture "
     "as calm open sky with nothing in it, for text and cards to sit on."),
    ("scene-tall", "1024x1536", False,
     "A tall, cheerful storybook landscape for a phone background. A bright soft daytime sky with a few fluffy "
     "clouds. Rolling bright green hills along the bottom with wildflowers and a small cosy thatched cottage. "
     "A giant magic beanstalk curls up the left edge into the clouds, a tiny fairy-tale castle on a cloud at the "
     "top. Keep the middle as calm open sky with nothing in it."),
    ("cloud", "1024x1024", True, "One big, soft, fluffy white storybook cloud, round and friendly. Nothing else."),
    ("beans", "1024x1024", True,
     "Five plump magic beans in a little pile: one deep red, one purple, one cream with red speckles, one green, "
     "one mottled brown, each with a faint golden magical glow and a few tiny sparkles. Nothing else."),
    ("icon-camera", "1024x1024", True, "A cute, chunky toy camera icon, rounded, cream and leaf-green. Nothing else."),
    ("icon-key", "1024x1024", True, "A cute golden storybook key with a little leaf on its bow, rounded and chunky. Nothing else."),
    ("icon-book", "1024x1024", True,
     "A cute open storybook icon with a tiny beanstalk sprouting from its pages, rounded and chunky. Nothing else."),
]


def to_webp(png: bytes, transparent: bool, max_side: int) -> bytes:
    img = Image.open(io.BytesIO(png))
    img = img.convert("RGBA" if transparent else "RGB")
    img.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    img.save(buf, "WEBP", quality=88, method=6)
    return buf.getvalue()


async def main(names: list[str]) -> None:
    story = load_story()
    style = get_style(story.style)
    out = ROOT / "static" / "themes" / story.theme / "art"
    out.mkdir(parents=True, exist_ok=True)
    client = AsyncOpenAI(max_retries=0, timeout=180)
    model = os.getenv("IMAGE_MODEL", "gpt-image-2.5-flare")
    for name, size, transparent, what in ART:
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
        path.write_bytes(to_webp(png, transparent, 1600 if name.startswith("scene") else 900))
        has_alpha = Image.open(io.BytesIO(png)).mode in ("RGBA", "LA")
        print(f"saved {path.name} ({path.stat().st_size // 1024} KB, transparent={has_alpha})", flush=True)


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
