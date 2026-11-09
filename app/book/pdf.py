"""PDF layout: a cover, full-bleed art with the story text drawn on top (never by the image model),
About Me, and The End. The same order as the flip book on the site."""
import io

import numpy as np
from PIL import Image

from reportlab.lib.colors import Color, HexColor
from reportlab.lib.utils import ImageReader, simpleSplit
from reportlab.pdfgen.canvas import Canvas

from .pages import RenderedPage

W, H = 792, 528  # 11 x 7.33 in: the 3:2 shape of the 1536x1024 art
STORY_FONT, STORY_SIZE, STORY_LEADING = "Times-Bold", 30, 36
CREAM, INK, GREEN, GOLD = HexColor("#f6efe0"), HexColor("#2b2418"), HexColor("#2c7a1f"), HexColor("#b07a05")

# Where text sits, as (band bottom, band top) in fractions of page height, and which edge the scrim
# darkens from. The story file names the zone per page; its prompt keeps that part of the art plain.
ZONES = {
    "bottom": (0.0, 1 / 3, "bottom", 0.55),
    "top": (2 / 3, 1.0, "top", 0.45),
    "bottom-dark": (0.0, 0.25, "bottom", 0.30),
}


def build_pdf(pages: list[RenderedPage], title: str, cover: RenderedPage | None = None) -> bytes:
    buf = io.BytesIO()
    c = Canvas(buf, pagesize=(W, H))
    c.setTitle(title)
    if cover is not None:
        _cover(c, cover, title)
        c.showPage()
    for page in pages:
        if page.kind == "about_me":
            _about_me(c, page)
        else:
            _illustrated(c, page)
        c.showPage()
    if cover is not None:
        _the_end(c)
        c.showPage()
    c.save()
    return buf.getvalue()


def _cover(c: Canvas, page: RenderedPage, title: str) -> None:
    """The child's cartoon in a round frame, the title, and "starring <name>"."""
    c.setFillColor(CREAM)
    c.rect(0, 0, W, H, stroke=0, fill=1)
    side = H * 0.66
    x0, y0 = W * 0.07, (H - side) / 2
    c.saveState()
    path = c.beginPath()
    path.circle(x0 + side / 2, y0 + side / 2, side / 2)
    c.clipPath(path, stroke=0, fill=0)
    c.drawImage(ImageReader(io.BytesIO(page.image)), x0, y0, side, side)
    c.restoreState()
    c.setStrokeColor(HexColor("#ffffff"))
    c.setLineWidth(8)
    c.circle(x0 + side / 2, y0 + side / 2, side / 2, stroke=1, fill=0)

    tx = x0 + side + W * 0.05
    width = W - tx - W * 0.05
    lines = simpleSplit(title, "Times-Bold", 46, width)
    y = H / 2 + len(lines) * 52 / 2
    c.setFillColor(GREEN)
    c.setFont("Times-Bold", 46)
    for line in lines:
        y -= 52
        c.drawString(tx, y, line)
    if page.child and page.child.name:
        c.setFillColor(GOLD)
        c.setFont("Times-Italic", 24)
        for line in simpleSplit(f"starring {page.child.name}", "Times-Italic", 24, width):
            y -= 34
            c.drawString(tx, y, line)


def _the_end(c: Canvas) -> None:
    c.setFillColor(CREAM)
    c.rect(0, 0, W, H, stroke=0, fill=1)
    c.setFillColor(GREEN)
    c.setFont("Times-Bold", 60)
    c.drawCentredString(W / 2, H / 2 - 20, "The End")


def shaded(image: bytes, zone: str) -> Image.Image:
    """The page's picture with a smooth dark gradient behind where the words go: strongest at the page edge,
    fading to clear, and darker over bright sky or flowers so white words stay readable. Drawn into the picture
    in one piece (thin strips drawn one by one showed as stripes)."""
    img = Image.open(io.BytesIO(image)).convert("RGB")
    lo, hi, edge, strength = ZONES[zone]
    top, bottom = int((1 - hi) * img.height), int((1 - lo) * img.height)  # the band, top to bottom in pixels
    band = np.asarray(img.crop((0, top, img.width, bottom)).convert("L"), dtype=np.float32) / 255
    brightness = float(band.mean()) if band.size else 0.0
    strength = min(0.8, strength * (1 + 0.9 * max(0.0, brightness - 0.45) / 0.55))
    t = np.linspace(0, 1, bottom - top, dtype=np.float32)  # 0 at the band's edge of the page, 1 at its far side
    if edge == "bottom":
        t = t[::-1]
    alpha = (strength * (1 - t) ** 1.5 * 255).astype(np.uint8)
    mask = Image.fromarray(np.repeat(alpha[:, None], img.width, axis=1), "L")
    img.paste(Image.new("RGB", (img.width, bottom - top), (0, 0, 0)), (0, top), mask)
    return img


PAPER_BAND = 0.27  # the share of the page under the picture when the words can't go on it


def _on_paper(c: Canvas, page: RenderedPage) -> None:
    """Faces at both ends of the picture: it shrinks, framed on cream, and the words go on the paper below."""
    c.setFillColor(CREAM)
    c.rect(0, 0, W, H, stroke=0, fill=1)
    margin = H * 0.04
    art_h = H * (1 - PAPER_BAND) - margin
    art_w = art_h * W / H  # the art keeps its shape
    x0, y0 = (W - art_w) / 2, H - margin - art_h
    buf = io.BytesIO()
    Image.open(io.BytesIO(page.image)).convert("RGB").save(buf, "JPEG", quality=88)
    c.drawImage(ImageReader(io.BytesIO(buf.getvalue())), x0, y0, art_w, art_h)
    c.setStrokeColor(HexColor("#ffffff"))
    c.setLineWidth(5)
    c.rect(x0, y0, art_w, art_h, stroke=1, fill=0)
    size, leading = STORY_SIZE - 6, STORY_LEADING - 7
    lines = simpleSplit(page.text, STORY_FONT, size, W * 0.84)
    y = y0 / 2 + len(lines) * leading / 2 - size * 0.8
    c.setFillColor(INK)
    c.setFont(STORY_FONT, size)
    for line in lines:
        c.drawCentredString(W / 2, y, line)
        y -= leading


def _illustrated(c: Canvas, page: RenderedPage) -> None:
    if page.text_zone == "paper":
        return _on_paper(c, page)
    buf = io.BytesIO()
    shaded(page.image, page.text_zone).save(buf, "JPEG", quality=88)  # JPEG keeps the PDF small
    c.drawImage(ImageReader(io.BytesIO(buf.getvalue())), 0, 0, W, H)
    lo, hi, edge, strength = ZONES[page.text_zone]
    lines = simpleSplit(page.text, STORY_FONT, STORY_SIZE, W * 0.78)
    block = len(lines) * STORY_LEADING
    y = (lo + hi) / 2 * H + block / 2 - STORY_SIZE * 0.8
    c.setFont(STORY_FONT, STORY_SIZE)
    for line in lines:
        c.setFillColor(Color(0, 0, 0, alpha=0.6))
        c.drawCentredString(W / 2 + 1.5, y - 1.5, line)
        c.setFillColor(Color(1, 1, 1))
        c.drawCentredString(W / 2, y, line)
        y -= STORY_LEADING


def _about_me(c: Canvas, page: RenderedPage) -> None:
    c.setFillColor(CREAM)
    c.rect(0, 0, W, H, stroke=0, fill=1)
    side = H * 0.62
    x0, y0 = W * 0.07, (H - side) / 2
    c.drawImage(ImageReader(io.BytesIO(page.image)), x0, y0, side, side)
    c.setStrokeColor(INK)
    c.setLineWidth(2)
    c.rect(x0, y0, side, side, stroke=1, fill=0)

    tx, width = x0 + side + W * 0.05, W - (x0 + side + W * 0.05) - W * 0.06
    y = H * 0.78
    c.setFillColor(INK)
    c.setFont("Times-Bold", 40)
    c.drawString(tx, y, "About Me")
    y -= 46
    c.setFont("Times-Bold", 26)
    for line in simpleSplit(page.child.name, "Times-Bold", 26, width):
        c.drawString(tx, y, line)
        y -= 30
    y -= 10
    for label, value in page.child.details:
        c.setFont("Helvetica-Bold", 13)
        c.drawString(tx, y, label.upper())
        y -= 18
        c.setFont("Helvetica", 15)
        for line in simpleSplit(value, "Helvetica", 15, width):
            c.drawString(tx, y, line)
            y -= 19
        y -= 10
