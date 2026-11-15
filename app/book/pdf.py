"""PDF layout, laid out like a real book: the front cover, a title page, the copyright page, the story (full-bleed
art with the words drawn on top, never by the image model), The End, and About Me on the back cover.

The same layouts make two things: the PDF people download and read on screen (one 3:2 page per side, the shape
of the art), and the two files a printer needs (print_files): the inside pages with bleed, and one wraparound
cover (back, spine, front). The flip book on the site shows the same order."""
import io
from dataclasses import dataclass

import numpy as np
from PIL import Image

from reportlab.lib.colors import Color, HexColor
from reportlab.lib.utils import ImageReader, simpleSplit
from reportlab.pdfgen.canvas import Canvas

from .pages import RenderedPage

PUBLISHER = "YWolfpublishing"
INCH = 72
W, H = 792, 528  # the screen PDF: 11 x 7.33 in, the 3:2 shape of the 1536x1024 art
STORY_FONT, STORY_SIZE, STORY_LEADING = "Times-Bold", 30, 36
CREAM, INK, GREEN, GOLD = HexColor("#f6efe0"), HexColor("#2b2418"), HexColor("#2c7a1f"), HexColor("#b07a05")

# The printed book: Lulu hardcover (casewrap), US Letter Landscape. Inside pages are the trim plus 0.125 in of
# bleed on every side; words and faces stay 0.5 in inside the trim. A hardcover needs at least 24 inside pages.
TRIM_W, TRIM_H, BLEED, SAFE = 11 * INCH, 8.5 * INCH, 0.125 * INCH, 0.5 * INCH
MIN_PRINT_PAGES = 24
COVER_SAFE = 1 * INCH  # Lulu asks 0.75 in on a hardcover (the casewrap folds round the board); a little more

# Where text sits, as (band bottom, band top) in fractions of page height, and which edge the scrim
# darkens from. The story file names the zone per page; its prompt keeps that part of the art plain.
ZONES = {
    "bottom": (0.0, 1 / 3, "bottom", 0.55),
    "top": (2 / 3, 1.0, "top", 0.45),
    "bottom-dark": (0.0, 0.25, "bottom", 0.30),
    "top-small": (0.8, 1.0, "top", 0.45),  # faces at both ends: smaller words in a thin strip (faces.py)
    "bottom-small": (0.0, 0.2, "bottom", 0.55),
}
SMALL_SIZE, SMALL_LEADING = 21, 25


@dataclass
class Box:
    """Where to draw on the canvas, in points: a whole page, or one panel of the wraparound cover. `inset` is
    how far in from the box's edge words must stay (bleed plus safety margin for print, a little for screen)."""
    x: float
    y: float
    w: float
    h: float
    inset: float = 0.04 * W

    @property
    def mid_x(self):
        return self.x + self.w / 2


@dataclass
class BookInfo:
    title: str
    child_name: str
    year: int


def build_pdf(pages: list[RenderedPage], title: str, cover: RenderedPage | None = None, year: int = 2026) -> bytes:
    """The PDF to download and read on screen: every side of the book in order, one per page."""
    buf = io.BytesIO()
    c = Canvas(buf, pagesize=(W, H))
    c.setTitle(title)
    page = Box(0, 0, W, H)
    story, about = _split(pages)
    if cover is None:  # a bare list of pages (tests, a page preview): no book around it
        for p in pages:
            (_about_me if p.kind == "about_me" else _illustrated)(c, p, page)
            c.showPage()
    else:
        info = BookInfo(title, cover.child.name if cover.child else "", year)
        _front(c, cover, info, page)
        c.showPage()
        for draw in _inside(story, info):
            draw(c, page)
            c.showPage()
        if about:
            _about_me(c, about, page)
            c.showPage()
    c.save()
    return buf.getvalue()


def print_files(pages: list[RenderedPage], title: str, cover: RenderedPage, year: int,
                cover_size: tuple[float, float] | None = None) -> tuple[bytes, bytes]:
    """The two files the printer takes: the inside pages (with bleed) and the wraparound cover. `cover_size` is
    the cover's width and height in points from the printer (it depends on the spine); without it, an estimate."""
    story, about = _split(pages)
    info = BookInfo(title, cover.child.name if cover.child else "", year)

    pw, ph = TRIM_W + 2 * BLEED, TRIM_H + 2 * BLEED
    inside = _inside(story, info)
    inside += [_blank] * (max(MIN_PRINT_PAGES, len(inside) + len(inside) % 2) - len(inside))  # an even count, 24+
    buf = io.BytesIO()
    c = Canvas(buf, pagesize=(pw, ph))
    c.setTitle(f"{title} (inside pages)")
    page = Box(0, 0, pw, ph, inset=BLEED + SAFE)
    for draw in inside:
        draw(c, page)
        c.showPage()
    c.save()
    interior = buf.getvalue()

    cw, ch = cover_size or estimated_cover_size(len(inside))
    buf = io.BytesIO()
    c = Canvas(buf, pagesize=(cw, ch))
    c.setTitle(f"{title} (cover)")
    c.setFillColor(CREAM)
    c.rect(0, 0, cw, ch, stroke=0, fill=1)
    spine = spine_width(len(inside))
    panel_w = (cw - spine) / 2  # back on the left, front on the right, the spine between
    c.setFillColor(GREEN)
    c.rect(panel_w, 0, spine, ch, stroke=0, fill=1)
    if about:
        _about_me(c, about, Box(0, 0, panel_w, ch, inset=COVER_SAFE), fill=False)
    _front(c, cover, info, Box(panel_w + spine, 0, panel_w, ch, inset=COVER_SAFE), fill=False)
    c.showPage()
    c.save()
    return interior, buf.getvalue()


def spine_width(inside_pages: int) -> float:
    """Lulu's hardcover spine for this many inside pages (from its Book Creation Guide's table), in points."""
    steps = [(84, 0.25), (140, 0.5), (168, 0.625), (194, 0.688), (222, 0.75)]
    return next((inches for most, inches in steps if inside_pages <= most), 0.813) * INCH


def estimated_cover_size(inside_pages: int) -> tuple[float, float]:
    """A stand-in for the printer's own numbers (its cover-dimensions endpoint), for previews and tests: two
    trims and the spine, plus the board wrap and bleed round the edge."""
    wrap = 0.75 * INCH
    return 2 * TRIM_W + spine_width(inside_pages) + 2 * wrap, TRIM_H + 2 * wrap


def _split(pages: list[RenderedPage]) -> tuple[list[RenderedPage], RenderedPage | None]:
    """The story's pages, and About Me (which goes on the back cover)."""
    return [p for p in pages if p.kind != "about_me"], next((p for p in pages if p.kind == "about_me"), None)


def _inside(story: list[RenderedPage], info: BookInfo) -> list:
    """Every inside page as a drawing function, in order: the story starts on the page after the copyright."""
    def illustrated(p):
        return lambda c, box: _illustrated(c, p, box)
    return ([lambda c, box: _title_page(c, info, box), lambda c, box: _copyright(c, info, box)]
            + [illustrated(p) for p in story] + [_the_end])


def _paper(c: Canvas, box: Box) -> None:
    c.setFillColor(CREAM)
    c.rect(box.x, box.y, box.w, box.h, stroke=0, fill=1)


def _lines(c: Canvas, lines: list[str], font: str, size: float, x: float, y: float, leading: float) -> float:
    """Centred lines from y downwards; returns where the next line would go."""
    c.setFont(font, size)
    for line in lines:
        c.drawCentredString(x, y, line)
        y -= leading
    return y


def _front(c: Canvas, page: RenderedPage, info: BookInfo, box: Box, fill: bool = True) -> None:
    """The child's cartoon in a round frame, the title, and "starring <name>"."""
    if fill:
        _paper(c, box)
    inner_h = box.h - 2 * box.inset
    side = min(inner_h * 0.86, (box.w - 2 * box.inset) * 0.48)
    x0, y0 = box.x + box.inset + box.w * 0.02, box.y + (box.h - side) / 2
    c.saveState()
    path = c.beginPath()
    path.circle(x0 + side / 2, y0 + side / 2, side / 2)
    c.clipPath(path, stroke=0, fill=0)
    c.drawImage(ImageReader(io.BytesIO(page.image)), x0, y0, side, side)
    c.restoreState()
    c.setStrokeColor(HexColor("#ffffff"))
    c.setLineWidth(8)
    c.circle(x0 + side / 2, y0 + side / 2, side / 2, stroke=1, fill=0)

    tx = x0 + side + box.w * 0.05
    width = box.x + box.w - box.inset - tx
    size = 46 if box.w > 700 else 40
    lines = simpleSplit(info.title, "Times-Bold", size, width)
    y = box.y + box.h / 2 + len(lines) * size * 1.13 / 2
    c.setFillColor(GREEN)
    c.setFont("Times-Bold", size)
    for line in lines:
        y -= size * 1.13
        c.drawString(tx, y, line)
    if info.child_name:
        c.setFillColor(GOLD)
        c.setFont("Times-Italic", 24)
        for line in simpleSplit(f"starring {info.child_name}", "Times-Italic", 24, width):
            y -= 34
            c.drawString(tx, y, line)


def _title_page(c: Canvas, info: BookInfo, box: Box) -> None:
    _paper(c, box)
    width = box.w - 2 * box.inset
    c.setFillColor(GREEN)
    y = _lines(c, simpleSplit(info.title, "Times-Bold", 50, width), "Times-Bold", 50, box.mid_x, box.y + box.h * 0.62, 58)
    if info.child_name:
        c.setFillColor(GOLD)
        _lines(c, simpleSplit(f"starring {info.child_name}", "Times-Italic", 28, width), "Times-Italic", 28,
               box.mid_x, y - 6, 34)
    c.setFillColor(INK)
    c.setFont("Times-Roman", 16)
    c.drawCentredString(box.mid_x, box.y + box.inset + 10, PUBLISHER)


def _copyright(c: Canvas, info: BookInfo, box: Box) -> None:
    """The copyright notice and the publisher, small and centred low on the page, as in a printed book."""
    _paper(c, box)
    starring = f", starring {info.child_name}" if info.child_name else ""
    notice = [
        f"{info.title}{starring}",
        "",
        f"Text and illustrations copyright © {info.year} {PUBLISHER}.",
        "All rights reserved. No part of this book may be reproduced in any form",
        "without written permission from the publisher.",
        "",
        "Retold from the traditional fairy tale, with pictures made for this reader.",
        "",
        f"Published by {PUBLISHER}",
        f"First edition, {info.year}",
    ]
    c.setFillColor(INK)
    width = box.w - 2 * box.inset
    lines = [part for line in notice for part in (simpleSplit(line, "Times-Roman", 13, width) or [""])]
    _lines(c, lines, "Times-Roman", 13, box.mid_x, box.y + box.inset + 17 * len(lines), 17)


def _the_end(c: Canvas, box: Box) -> None:
    _paper(c, box)
    c.setFillColor(GREEN)
    c.setFont("Times-Bold", 60)
    c.drawCentredString(box.mid_x, box.y + box.h / 2 - 20, "The End")


def _blank(c: Canvas, box: Box) -> None:
    """A plain page at the back, so the printed book has the page count the binding needs."""
    _paper(c, box)


def shaded(image: bytes, zone: str, aspect: float | None = None) -> Image.Image:
    """The page's picture with a smooth dark gradient behind where the words go: strongest at the page edge,
    fading to clear, and darker over bright sky or flowers so white words stay readable. Drawn into the picture
    in one piece (thin strips drawn one by one showed as stripes). With `aspect` (width / height), the picture is
    first cropped evenly at the sides to fit a page of that shape."""
    img = Image.open(io.BytesIO(image)).convert("RGB")
    if aspect and img.width / img.height > aspect:
        keep = round(img.height * aspect)
        left = (img.width - keep) // 2
        img = img.crop((left, 0, left + keep, img.height))
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


def _words(c: Canvas, text: str, box: Box, middle: float, size: int, leading: int) -> None:
    """The story's words, white with a soft shadow, centred on `middle` (points from the bottom of the box)."""
    width = min(box.w * (0.86 if size < STORY_SIZE else 0.78), box.w - 2 * box.inset)
    lines = simpleSplit(text, STORY_FONT, size, width)
    top = box.y + box.h - box.inset - size * 0.8  # never above the safe area
    bottom = box.y + box.inset + (len(lines) - 1) * leading  # nor below it
    y = min(top, max(bottom, box.y + middle + len(lines) * leading / 2 - size * 0.8))
    c.setFont(STORY_FONT, size)
    for line in lines:
        c.setFillColor(Color(0, 0, 0, alpha=0.6))
        c.drawCentredString(box.mid_x + 1.5, y - 1.5, line)
        c.setFillColor(Color(1, 1, 1))
        c.drawCentredString(box.mid_x, y, line)
        y -= leading


def _illustrated(c: Canvas, page: RenderedPage, box: Box) -> None:
    buf = io.BytesIO()
    shaded(page.image, page.text_zone, box.w / box.h).save(buf, "JPEG", quality=88)  # JPEG keeps the PDF small
    c.drawImage(ImageReader(io.BytesIO(buf.getvalue())), box.x, box.y, box.w, box.h)
    lo, hi, edge, strength = ZONES[page.text_zone]
    small = page.text_zone.endswith("-small")
    _words(c, page.text, box, (lo + hi) / 2 * box.h,
           *((SMALL_SIZE, SMALL_LEADING) if small else (STORY_SIZE, STORY_LEADING)))


def _about_me(c: Canvas, page: RenderedPage, box: Box, fill: bool = True) -> None:
    if fill:
        _paper(c, box)
    side = min((box.h - 2 * box.inset) * 0.8, box.w * 0.4)
    x0, y0 = box.x + box.inset + box.w * 0.02, box.y + (box.h - side) / 2
    c.drawImage(ImageReader(io.BytesIO(page.image)), x0, y0, side, side)
    c.setStrokeColor(INK)
    c.setLineWidth(2)
    c.rect(x0, y0, side, side, stroke=1, fill=0)

    tx = x0 + side + box.w * 0.05
    width = box.x + box.w - box.inset - tx
    y = box.y + box.h * 0.78
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
