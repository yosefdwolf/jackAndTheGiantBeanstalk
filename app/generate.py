"""OpenAI calls, no retries: describe the face, cartoonify the photo once, then one call per scene.

The scenes are drawn from the cartoon portrait, not the photo, so they can't copy the real face.
Set MOCK=1 to skip OpenAI entirely and return placeholder images (free local UI testing).
"""
import asyncio
import base64
import io
import os

from openai import AsyncOpenAI
from PIL import Image, ImageDraw, ImageOps

from .faces import PreparedPhoto
from .prompts import (DESCRIBE_FACE_PROMPT, SCENE_DESCRIPTIONS, SCENES, build_portrait_prompt,
                      build_prompt, cast)

IMAGE_MODEL = os.getenv("IMAGE_MODEL", "gpt-image-2.5-flare")
IMAGE_QUALITY = os.getenv("IMAGE_QUALITY", "medium")
IMAGE_SIZE = os.getenv("IMAGE_SIZE", "1024x1024")  # 1024x1536 costs ~50% more output tokens
VISION_MODEL = os.getenv("VISION_MODEL", "gpt-4.1-mini")
# input_fidelity="high" keeps faces close on gpt-image-1; mini rejects it; the 2.5 docs don't list it.
HIGH_FIDELITY = os.getenv("INPUT_FIDELITY", "high" if IMAGE_MODEL == "gpt-image-1" else "") == "high"
# A second, face close-up reference for the portrait. Cheap on mini; elsewhere check the [cost] log.
FACE_CLOSEUP = os.getenv("FACE_CLOSEUP", "1" if IMAGE_MODEL == "gpt-image-1-mini" else "0") == "1"
MOCK = os.getenv("MOCK", "").lower() in {"1", "true", "yes"}

_client: AsyncOpenAI | None = None


def client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI()  # reads OPENAI_API_KEY from the environment
    return _client


async def describe_face(photo: PreparedPhoto) -> str:
    b64 = base64.b64encode(photo.face_png).decode()
    resp = await client().chat.completions.create(
        model=VISION_MODEL,
        max_tokens=200,
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": DESCRIBE_FACE_PROMPT},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
            ],
        }],
    )
    return (resp.choices[0].message.content or "").strip()


async def _edit(label: str, images: list, prompt: str) -> str:
    resp = await client().images.edit(
        model=IMAGE_MODEL,
        image=images,
        prompt=prompt,
        **({"input_fidelity": "high"} if HIGH_FIDELITY else {}),
        quality=IMAGE_QUALITY,
        size=IMAGE_SIZE,
    )
    log_cost(label, resp.usage)
    return resp.data[0].b64_json


async def cartoonify(photo: PreparedPhoto, style: str, strength: int, face_description: str,
                     hero: str) -> str:
    images = [("photo.png", photo.full_png, "image/png")]
    if FACE_CLOSEUP:
        images.append(("face.png", photo.face_png, "image/png"))
    prompt = build_portrait_prompt(style, strength, face_description, FACE_CLOSEUP, hero)
    return await _edit("portrait", images, prompt)


async def render_scene(portrait_png: bytes, scene: str, style: str, strength: int, hero: str) -> dict:
    b64 = await _edit(scene, [("character.png", portrait_png, "image/png")],
                      build_prompt(scene, style, strength, hero))
    return {**_caption(scene, hero), "image_b64": b64}


# List prices, USD per 1M tokens (text in, image in, image out). Check OpenAI's pricing page.
PRICES = {
    "gpt-image-1": (5.0, 10.0, 40.0),
    "gpt-image-1-mini": (2.0, 2.5, 8.0),
    "gpt-image-2.5-flare": (5.0, 8.0, 30.0),
    "gpt-image-2.5-sunburst": (5.0, 8.0, 30.0),
}
PRICE_TEXT_IN, PRICE_IMAGE_IN, PRICE_OUT = PRICES.get(IMAGE_MODEL, PRICES["gpt-image-1"])


def log_cost(label: str, usage) -> None:
    if usage is None:
        return
    details = usage.input_tokens_details
    if details is None:
        return
    cost = (details.text_tokens * PRICE_TEXT_IN + details.image_tokens * PRICE_IMAGE_IN
            + usage.output_tokens * PRICE_OUT) / 1e6
    print(f"[cost] {label!r}: text_in={details.text_tokens} image_in={details.image_tokens} "
          f"out={usage.output_tokens} ≈ ${cost:.3f}", flush=True)


def _caption(scene: str, hero: str) -> dict:
    return {"caption": cast(scene, hero), "description": cast(SCENE_DESCRIPTIONS[scene], hero)}


def _mock_image(photo: PreparedPhoto, color: str, label: str) -> str:
    face = Image.open(io.BytesIO(photo.face_png)).convert("RGB")
    canvas = Image.new("RGB", (1024, 1024), color)
    canvas.paste(ImageOps.posterize(ImageOps.fit(face, (560, 560)), 3), (232, 200))
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((0, 40, 1024, 150), fill="#c0392b")
    draw.text((512, 95), "MOCK · not a real image", fill="white", font_size=56, anchor="mm")
    draw.text((512, 860), label, fill="#22301f", font_size=40, anchor="mm")
    buf = io.BytesIO()
    canvas.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


async def generate(photo: PreparedPhoto, style: str, strength: int, scenes=SCENES,
                   hero: str = "jack") -> dict:
    if MOCK:
        await asyncio.sleep(1.5)
        return {
            "face_description": "mock",
            "images": [{**_caption(s, hero),
                        "image_b64": _mock_image(photo, ("#cfe3b8", "#f2d9a6")[SCENES.index(s)], cast(s, hero))}
                       for s in scenes],
        }

    face_description = await describe_face(photo)
    portrait_b64 = await cartoonify(photo, style, strength, face_description, hero)
    portrait_png = base64.b64decode(portrait_b64)
    # The scenes are independent, so they run in parallel: one call each, both from the same cartoon.
    results = await asyncio.gather(
        *(render_scene(portrait_png, s, style, strength, hero) for s in scenes)
    )
    # The portrait is only the scenes' character reference; the page shows just the scenes.
    return {"face_description": face_description, "images": list(results)}
