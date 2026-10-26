"""PDF layout: full-bleed art with the story text drawn on top (never by the image model), About Me last."""
import io

from reportlab.lib.colors import Color, HexColor
from reportlab.lib.utils import ImageReader, simpleSplit
from reportlab.pdfgen.canvas import Canvas

from .pages import RenderedPage

W, H = 792, 528  # 11 x 7.33 in: the 3:2 shape of the 1536x1024 art
STORY_FONT, STORY_SIZE, STORY_LEADING = "Times-Bold", 30, 36
CREAM, INK = HexColor("#f6efe0"), HexColor("#2b2418")

# Where text sits, as (band bottom, band top) in fractions of page height, and which edge the scrim
# darkens from. The story file names the zone per page; its prompt keeps that part of the art plain.
ZONES = {
    "bottom": (0.0, 1 / 3, "bottom", 0.55),
    "top": (2 / 3, 1.0, "top", 0.45),
    "bottom-dark": (0.0, 0.25, "bottom", 0.30),
}


def build_pdf(pages: list[RenderedPage], title: str) -> bytes:
    buf = io.BytesIO()
    c = Canvas(buf, pagesize=(W, H))
    c.setTitle(title)
    for page in pages:
        if page.kind == "about_me":
            _about_me(c, page)
        else:
            _illustrated(c, page)
        c.showPage()
    c.save()
    return buf.getvalue()


def _illustrated(c: Canvas, page: RenderedPage) -> None:
    c.drawImage(ImageReader(io.BytesIO(page.image)), 0, 0, W, H)
    lo, hi, edge, strength = ZONES[page.text_zone]
    _scrim(c, lo * H, hi * H, edge, strength)
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


def _scrim(c: Canvas, y0: float, y1: float, edge: str, strength: float, steps: int = 160) -> None:
    """A soft dark gradient behind the text, strongest at the page edge, fading to clear."""
    c.saveState()
    step = (y1 - y0) / steps
    for i in range(steps):
        t = i / steps  # 0 at the edge, 1 at the far side of the band
        alpha = strength * (1 - t) ** 1.5
        y = y0 + i * step if edge == "bottom" else y1 - (i + 1) * step
        c.setFillColor(Color(0, 0, 0, alpha=alpha))
        c.rect(0, y, W, step, stroke=0, fill=1)
    c.restoreState()


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
