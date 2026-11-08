"""Image providers. The book only talks to ImageProvider, so a new provider is one new class.

Each book records which provider drew it (books.provider). MOCK=1 makes "mock" the default:
placeholder images, no API calls, no cost. MOCK_DELAY=seconds makes mock images take time, so the
progress bars can be watched locally.
"""
import asyncio
import base64
import io
import json
import os
import random
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from PIL import Image, ImageDraw, ImageOps

from .log import add_cost, record, step

Ref = tuple[str, bytes]  # (filename, png bytes)

PAGE_SIZE = os.getenv("PAGE_SIZE", "1536x1024")  # wide picture-book pages
SHEET_SIZE = "1024x1024"


@dataclass
class ImageResult:
    png: bytes
    cost: float = 0.0
    tokens: dict = field(default_factory=dict)
    request_id: str | None = None


class ImageProvider(ABC):
    name: str
    model: str | None = None
    quality: str | None = None

    @abstractmethod
    async def edit(self, label: str, refs: list[Ref], prompt: str, size: str) -> ImageResult:
        """Draw a new image guided by the reference images."""

    @abstractmethod
    async def generate(self, label: str, prompt: str, size: str) -> ImageResult:
        """Draw an image from the prompt alone."""

    async def describe_face(self, face_png: bytes) -> str:
        """Short text description of a face, added to the hero sheet prompt. Optional."""
        return ""

    async def look_at_page(self, png: bytes) -> dict:
        """What's on a finished page, for the picture check (jobs.check_page): every face's place as fractions
        of the picture ({"top", "bottom", "left", "right"}, 0 = top/left edge) and how many children are in it.
        Without a vision model: nothing found, so the check passes and the words stay in the template's place."""
        return {"faces": [], "children": None}


class OpenAIImageProvider(ImageProvider):
    name = "openai"
    # List prices, USD per 1M tokens (text in, image in, image out). Check OpenAI's pricing page.
    PRICES = {
        "gpt-image-1": (5.0, 10.0, 40.0),
        "gpt-image-1-mini": (2.0, 2.5, 8.0),
        "gpt-image-2.5-flare": (5.0, 8.0, 30.0),
        "gpt-image-2.5-sunburst": (5.0, 8.0, 30.0),
    }

    def __init__(self, model: str | None = None, quality: str | None = None):
        from openai import AsyncOpenAI
        # Reads OPENAI_API_KEY from the environment. One attempt per call: the SDK's default of 2
        # silent retries and a 10-minute timeout turned one stuck call into a 30-minute hang.
        self.client = AsyncOpenAI(max_retries=0, timeout=float(os.getenv("IMAGE_TIMEOUT_SECONDS", "120")))
        self.model = model or os.getenv("IMAGE_MODEL", "gpt-image-2.5-flare")
        self.quality = quality or os.getenv("IMAGE_QUALITY", "medium")
        self.vision_model = os.getenv("VISION_MODEL", "gpt-4.1-mini")

    async def edit(self, label, refs, prompt, size):
        async with step(label, call="images.edit", model=self.model, quality=self.quality, size=size,
                        refs=",".join(n for n, _ in refs)):
            resp = await self.client.images.edit(model=self.model, image=[(n, b, "image/png") for n, b in refs],
                                                 prompt=prompt, quality=self.quality, size=size)
            return await self._result(label, resp)

    async def generate(self, label, prompt, size):
        async with step(label, call="images.generate", model=self.model, quality=self.quality, size=size):
            resp = await self.client.images.generate(model=self.model, prompt=prompt, quality=self.quality, size=size)
            return await self._result(label, resp)

    async def describe_face(self, face_png):
        from .prompts import DESCRIBE_FACE
        b64 = base64.b64encode(face_png).decode()
        async with step("face description", call="chat.completions", model=self.vision_model):
            resp = await self.client.chat.completions.create(
                model=self.vision_model, max_tokens=200,
                messages=[{"role": "user", "content": [
                    {"type": "text", "text": DESCRIBE_FACE},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                ]}],
            )
            await record("INFO", "face description", "usage", tokens_in=resp.usage.prompt_tokens,
                         tokens_out=resp.usage.completion_tokens, provider_request=resp._request_id)
        return (resp.choices[0].message.content or "").strip()

    async def look_at_page(self, png):
        img = Image.open(io.BytesIO(png)).convert("RGB")
        img.thumbnail((768, 768))  # plenty to place faces, and a fraction of a cent
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=85)
        b64 = base64.b64encode(buf.getvalue()).decode()
        async with step("picture check", call="chat.completions", model=self.vision_model):
            resp = await self.client.chat.completions.create(
                model=self.vision_model, max_tokens=400, response_format={"type": "json_object"},
                messages=[{"role": "user", "content": [
                    {"type": "text", "text": LOOK_AT_PAGE},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                ]}],
            )
            tokens_in, tokens_out = resp.usage.prompt_tokens, resp.usage.completion_tokens
            cost = (tokens_in * 0.40 + tokens_out * 1.60) / 1e6  # gpt-4.1-mini list prices per 1M tokens
            add_cost(cost)
            await record("INFO", "picture check", "usage", tokens_in=tokens_in, tokens_out=tokens_out,
                         cost=f"${cost:.4f}", provider_request=resp._request_id)
        try:
            found = json.loads(resp.choices[0].message.content or "{}")
        except ValueError:
            return {"faces": [], "children": None}
        faces = [{k: min(1.0, max(0.0, float(f.get(k, 0)))) for k in ("top", "bottom", "left", "right")}
                 for f in found.get("faces") or [] if isinstance(f, dict)]
        children = found.get("children")
        return {"faces": faces, "children": int(children) if isinstance(children, (int, float)) else None}

    async def _result(self, label, resp) -> ImageResult:
        png = base64.b64decode(resp.data[0].b64_json)
        details = getattr(resp.usage, "input_tokens_details", None)
        if details is None:
            await record("INFO", label, "usage", provider_request=resp._request_id)
            return ImageResult(png, request_id=resp._request_id)
        text_in, image_in, out = self.PRICES.get(self.model, self.PRICES["gpt-image-1"])
        tokens = {"text_in": details.text_tokens, "image_in": details.image_tokens, "out": resp.usage.output_tokens}
        cost = (tokens["text_in"] * text_in + tokens["image_in"] * image_in + tokens["out"] * out) / 1e6
        add_cost(cost)
        await record("INFO", label, "usage", **tokens, cost=f"${cost:.3f}", provider_request=resp._request_id)
        return ImageResult(png, cost, tokens, resp._request_id)


LOOK_AT_PAGE = (
    "This is one page of a children's picture book. Answer in JSON only: "
    '{"faces": [{"who": "short label", "top": 0.0, "bottom": 0.0, "left": 0.0, "right": 0.0}], "children": 0}. '
    "faces: every face in the picture (people and animal characters), each as the box around the face only, in "
    "fractions of the picture (0 = top or left edge, 1 = bottom or right edge). children: how many human children "
    "are in the picture (count every child, even small, partly hidden or in the background)."
)


class MockImageProvider(ImageProvider):
    """Free placeholder art: the first reference (if any) posterized, under a red MOCK banner."""
    name = "mock"
    model = "mock"

    def __init__(self, *_, **__):
        self.delay = float(os.getenv("MOCK_DELAY", "0"))

    async def edit(self, label, refs, prompt, size):
        async with step(label, call="mock.edit", size=size, refs=",".join(n for n, _ in refs)):
            if self.delay:
                await asyncio.sleep(self.delay * random.uniform(0.6, 1.4))
            return ImageResult(self._draw(label, size, refs[0][1] if refs else None, len(refs)))

    async def generate(self, label, prompt, size):
        return ImageResult(self._draw(label, size, None, 0))

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


class AgnesImageProvider(ImageProvider):
    """Agnes AI (free at the time of writing). Admin test books only: Agnes may train on what it's sent.

    OpenAI-style JSON API; reference images go in extra_body.image as data URIs, and the size is a
    tier ("1K", "2K") plus a ratio ("3:2", "1:1").
    """
    name = "agnes"
    URL = "https://apihub.agnes-ai.com/v1/images/generations"
    RATIOS = {"1536x1024": "3:2", "1024x1536": "2:3", "1024x1024": "1:1"}

    def __init__(self, model: str | None = None, quality: str | None = None):
        self.model = model or "agnes-image-2.1-flash"
        self.quality = quality or "1K"  # the size tier
        self.timeout = float(os.getenv("IMAGE_TIMEOUT_SECONDS", "120"))

    async def edit(self, label, refs, prompt, size):
        async with step(label, call="agnes.images", model=self.model, tier=self.quality, size=size,
                        refs=",".join(n for n, _ in refs)):
            images = [f"data:image/png;base64,{base64.b64encode(b).decode()}" for _, b in refs]
            return await self._call(label, prompt, size, images)

    async def generate(self, label, prompt, size):
        async with step(label, call="agnes.images", model=self.model, tier=self.quality, size=size):
            return await self._call(label, prompt, size, [])

    async def _call(self, label, prompt, size, images):
        import httpx
        key = os.getenv("AGNES_API_KEY", "")
        if not key:
            raise RuntimeError("AGNES_API_KEY is not set")
        body = {"model": self.model, "prompt": prompt, "size": self.quality,
                "ratio": self.RATIOS.get(size, "1:1"), "return_base64": True}
        if images:
            body["extra_body"] = {"image": images}
        async with httpx.AsyncClient(timeout=self.timeout) as http:
            resp = await http.post(self.URL, json=body, headers={"Authorization": f"Bearer {key}"})
            if resp.status_code != 200:
                raise RuntimeError(f"Agnes returned {resp.status_code}: {resp.text[:300]}")
            item = resp.json()["data"][0]
            if item.get("b64_json"):
                data = base64.b64decode(item["b64_json"])
            else:
                data = (await http.get(item["url"])).content
        request_id = resp.headers.get("x-request-id")
        await record("INFO", label, "usage", provider_request=request_id, cost="$0.000")
        # Agnes may not return the size asked for; pages are laid out for the exact size.
        img = Image.open(io.BytesIO(data)).convert("RGB")
        w, h = (int(x) for x in size.split("x"))
        if img.size != (w, h):
            img = ImageOps.fit(img, (w, h))
        buf = io.BytesIO()
        img.save(buf, "PNG")
        return ImageResult(buf.getvalue(), request_id=request_id)


PROVIDERS: dict[str, type[ImageProvider]] = {
    "openai": OpenAIImageProvider,
    "agnes": AgnesImageProvider,
    "mock": MockImageProvider,
}

# What the admin's model switch offers: provider -> models, and the quality (or size tier) choices.
CHOICES = {
    "openai": {"models": ["gpt-image-2.5-flare", "gpt-image-2.5-sunburst", "gpt-image-1", "gpt-image-1-mini"],
               "qualities": ["low", "medium", "high"], "default_quality": "medium"},
    "agnes": {"models": ["agnes-image-2.1-flash", "agnes-image-2.0-flash"],
              "qualities": ["1K", "2K"], "default_quality": "1K"},
    "mock": {"models": ["mock"], "qualities": [""], "default_quality": ""},
}


def is_mock() -> bool:
    return os.getenv("MOCK", "").lower() in {"1", "true", "yes"}


def default_provider_name() -> str:
    return "mock" if is_mock() else "openai"


def get_provider(name: str | None = None, model: str | None = None, quality: str | None = None) -> ImageProvider:
    return PROVIDERS[name or default_provider_name()](model, quality)
