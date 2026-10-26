"""Image providers. The book only talks to ImageProvider, so a new provider is one new class.

MOCK=1 selects MockImageProvider: placeholder images, no API calls, no cost.
"""
import base64
import io
import os
from abc import ABC, abstractmethod

from PIL import Image, ImageDraw, ImageOps

Ref = tuple[str, bytes]  # (filename, png bytes)

PAGE_SIZE = os.getenv("PAGE_SIZE", "1536x1024")  # wide picture-book pages
SHEET_SIZE = "1024x1024"


class ImageProvider(ABC):
    @abstractmethod
    async def edit(self, label: str, refs: list[Ref], prompt: str, size: str) -> bytes:
        """Draw a new image guided by the reference images. Returns PNG bytes."""

    @abstractmethod
    async def generate(self, label: str, prompt: str, size: str) -> bytes:
        """Draw an image from the prompt alone. Returns PNG bytes."""

    async def describe_face(self, face_png: bytes) -> str:
        """Short text description of a face, added to the hero sheet prompt. Optional."""
        return ""


class OpenAIImageProvider(ImageProvider):
    # List prices, USD per 1M tokens (text in, image in, image out). Check OpenAI's pricing page.
    PRICES = {
        "gpt-image-1": (5.0, 10.0, 40.0),
        "gpt-image-1-mini": (2.0, 2.5, 8.0),
        "gpt-image-2.5-flare": (5.0, 8.0, 30.0),
        "gpt-image-2.5-sunburst": (5.0, 8.0, 30.0),
    }

    def __init__(self):
        from openai import AsyncOpenAI
        self.client = AsyncOpenAI()  # reads OPENAI_API_KEY from the environment
        self.model = os.getenv("IMAGE_MODEL", "gpt-image-2.5-flare")
        self.quality = os.getenv("IMAGE_QUALITY", "medium")
        self.vision_model = os.getenv("VISION_MODEL", "gpt-4.1-mini")

    async def edit(self, label, refs, prompt, size):
        resp = await self.client.images.edit(model=self.model, image=[(n, b, "image/png") for n, b in refs],
                                             prompt=prompt, quality=self.quality, size=size)
        self._log_cost(label, resp.usage)
        return base64.b64decode(resp.data[0].b64_json)

    async def generate(self, label, prompt, size):
        resp = await self.client.images.generate(model=self.model, prompt=prompt, quality=self.quality, size=size)
        self._log_cost(label, resp.usage)
        return base64.b64decode(resp.data[0].b64_json)

    async def describe_face(self, face_png):
        from .prompts import DESCRIBE_FACE
        b64 = base64.b64encode(face_png).decode()
        resp = await self.client.chat.completions.create(
            model=self.vision_model, max_tokens=200,
            messages=[{"role": "user", "content": [
                {"type": "text", "text": DESCRIBE_FACE},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
            ]}],
        )
        return (resp.choices[0].message.content or "").strip()

    def _log_cost(self, label, usage):
        details = getattr(usage, "input_tokens_details", None)
        if details is None:
            return
        text_in, image_in, out = self.PRICES.get(self.model, self.PRICES["gpt-image-1"])
        cost = (details.text_tokens * text_in + details.image_tokens * image_in + usage.output_tokens * out) / 1e6
        print(f"[cost] {label}: text_in={details.text_tokens} image_in={details.image_tokens} "
              f"out={usage.output_tokens} ≈ ${cost:.3f}", flush=True)


class MockImageProvider(ImageProvider):
    """Free placeholder art: the first reference (if any) posterized, under a red MOCK banner."""

    async def edit(self, label, refs, prompt, size):
        return self._draw(label, size, refs[0][1] if refs else None, len(refs))

    async def generate(self, label, prompt, size):
        return self._draw(label, size, None, 0)

    @staticmethod
    def _draw(label: str, size: str, ref: bytes | None, n_refs: int) -> bytes:
        w, h = (int(x) for x in size.split("x"))
        canvas = Image.new("RGB", (w, h), "#8a7f6a")
        if ref:
            face = Image.open(io.BytesIO(ref)).convert("RGB")
            side = int(h * 0.55)
            canvas.paste(ImageOps.posterize(ImageOps.fit(face, (side, side)), 3), ((w - side) // 2, int(h * 0.18)))
        draw = ImageDraw.Draw(canvas)
        draw.rectangle((0, 30, w, 110), fill="#c0392b")
        draw.text((w // 2, 70), "MOCK · not a real image", fill="white", font_size=48, anchor="mm")
        draw.text((w // 2, int(h * 0.8)), f"{label} · {n_refs} reference image(s)", fill="#1d1d1d",
                  font_size=36, anchor="mm")
        buf = io.BytesIO()
        canvas.save(buf, "PNG")
        return buf.getvalue()


def is_mock() -> bool:
    return os.getenv("MOCK", "").lower() in {"1", "true", "yes"}


def get_provider() -> ImageProvider:
    return MockImageProvider() if is_mock() else OpenAIImageProvider()
