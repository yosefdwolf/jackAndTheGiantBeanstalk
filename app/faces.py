"""Upload checks: fix orientation, find exactly one usable face, make a face crop.

Runs before any API call so bad uploads never cost money.
"""
import io
from dataclasses import dataclass

import cv2
import numpy as np
from PIL import Image, ImageOps
from pillow_heif import register_heif_opener

register_heif_opener()  # iPhone photos arrive as HEIC when sent from the Files app

MAX_SIDE = 1024
MIN_FACE_FRACTION = 0.12  # face width must be at least this share of image width
CASCADE = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
CASCADE_ALT = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_alt2.xml")
EYES = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_eye.xml")


class UploadError(ValueError):
    """Upload is unusable; message is safe to show the user."""


@dataclass
class PreparedPhoto:
    full_png: bytes
    face_png: bytes
    face_box: list[int] | None = None  # [x, y, w, h] in full_png, saved so the book never re-detects


def _to_png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _overlaps(a, b) -> bool:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah


def _is_second_person(gray, main, other) -> bool:
    x, y, w, h = other
    if w * h < 0.6 * main[2] * main[3] or _overlaps(main, other):
        return False
    eyes = EYES.detectMultiScale(gray[y:y + h // 2 + h // 6, x:x + w], scaleFactor=1.1, minNeighbors=8)
    return len(eyes) > 0


def prepare(upload: bytes) -> PreparedPhoto:
    try:
        img = Image.open(io.BytesIO(upload))
        img = ImageOps.exif_transpose(img).convert("RGB")
    except Exception as e:
        raise UploadError("That file isn't an image we can read. Try a JPG, PNG or HEIC photo.") from e

    img.thumbnail((MAX_SIDE, MAX_SIDE))
    gray = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2GRAY)
    faces = _find_faces(gray)

    if len(faces) == 0:
        raise UploadError("We couldn't find a face. Use a clear, front-facing photo with good light.")
    faces = sorted(faces, key=lambda f: f[2] * f[3], reverse=True)
    x, y, w, h = (int(v) for v in faces[0])
    # Haar often "sees" faces in shirts, posters or shadows, so a second detection only counts
    # as another person when it is nearly as big, separate from the main face, and has an eye.
    if any(_is_second_person(gray, faces[0], f) for f in faces[1:]):
        raise UploadError("We found more than one face. Upload a photo with just you in it.")
    if w < MIN_FACE_FRACTION * img.width:
        raise UploadError("Your face is too small in this photo. Use a closer shot, like a selfie.")

    # Generous crop around the face (hair, ears, chin) so the model sees the whole head.
    cx, cy = x + w / 2, y + h / 2
    half = max(w, h) * 0.9
    box = (
        int(max(0, cx - half)),
        int(max(0, cy - half * 1.1)),
        int(min(img.width, cx + half)),
        int(min(img.height, cy + half * 0.9)),
    )
    face = img.crop(box)
    face.thumbnail((512, 512))
    return PreparedPhoto(full_png=_to_png(img), face_png=_to_png(face), face_box=[x, y, w, h])


def _find_faces(gray):
    """Strict first (few false faces); if that finds nothing, a gentler pass with evened-out light and a
    second detector, since real phone photos in dim rooms or at an angle were being turned away."""
    faces = CASCADE.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=6, minSize=(60, 60))
    if len(faces):
        return faces
    even = cv2.equalizeHist(gray)
    for cascade in (CASCADE, CASCADE_ALT):
        faces = cascade.detectMultiScale(even, scaleFactor=1.05, minNeighbors=4, minSize=(48, 48))
        if len(faces):
            return faces
    return faces


def drawn_face_x(img: Image.Image) -> float | None:
    """Where the hero's face is across a drawn page (0 to 1), or None if unsure. The photo finder also
    "finds" faces in leaves and clouds, so only a face with eyes found inside it counts; the biggest wins."""
    gray = cv2.cvtColor(np.array(img.convert("RGB")), cv2.COLOR_RGB2GRAY)
    best = None
    for (x, y, w, h) in _find_faces(gray):
        eyes = EYES.detectMultiScale(gray[y:y + h * 2 // 3, x:x + w], 1.1, 3, minSize=(w // 10, w // 10))
        if len(eyes) and (best is None or w > best[2]):
            best = (x, y, w, h)
    return None if best is None else (best[0] + best[2] / 2) / img.width


# Where each text zone sits on a page, top to bottom (0 = top edge). Matches ZONES in app/book/pdf.py.
ZONE_BANDS = {"top": (0.0, 1 / 3), "bottom": (2 / 3, 1.0), "bottom-dark": (0.75, 1.0)}
OTHER_ZONE = {"top": "bottom", "bottom": "top", "bottom-dark": "top"}


def drawn_faces(img: Image.Image) -> list[tuple[int, int, int, int]]:
    """Faces on a drawn page (x, y, w, h), counting only those with eyes found inside (leaves and clouds can
    look like faces to the detector)."""
    gray = cv2.cvtColor(np.array(img.convert("RGB")), cv2.COLOR_RGB2GRAY)
    found = []
    for (x, y, w, h) in _find_faces(gray):
        eyes = EYES.detectMultiScale(gray[y:y + h * 2 // 3, x:x + w], 1.1, 3, minSize=(w // 10, w // 10))
        if len(eyes):
            found.append((int(x), int(y), int(w), int(h)))
    return found


def _covered(faces: list[dict], zone: str) -> float:
    """How much face is inside a text band: each face's share of its height that's in the band, added up."""
    top, bottom = ZONE_BANDS[zone]
    return sum(max(0.0, min(f["bottom"], bottom) - max(f["top"], top)) / max(0.01, f["bottom"] - f["top"])
               for f in faces)


CLEAR = 0.15  # a band with less face in it than this counts as clear (a chin's edge, not a face)


def clear_zone(faces: list[dict], zone: str) -> str | None:
    """The template's place for the words if no face is in it, else the other end of the page if that's
    clear, else None (faces at both ends: the page should be drawn again)."""
    if _covered(faces, zone) <= CLEAR:
        return zone
    return OTHER_ZONE[zone] if _covered(faces, OTHER_ZONE[zone]) <= CLEAR else None


PAPER = "paper"  # neither end is clear: the picture shrinks and the words go on paper below it (pdf.py)


def zone_clear_of(faces: list[dict], zone: str, things: list[dict] = ()) -> str:
    """Where a page's words go, given where faces are ({"top", "bottom"} as fractions, 0 = top edge): the clear
    end of the page, or if neither is clear, PAPER, below the picture, so words never sit on a face. `things`
    (what the page is about, like the axe biting the stalk) are kept clear too, when an end clear of both exists."""
    for end in (zone, OTHER_ZONE[zone]):
        if things and _covered(faces, end) <= CLEAR and _covered(list(things), end) <= CLEAR:
            return end
    return clear_zone(faces, zone) or PAPER


def choose_zone(png: bytes, zone: str) -> str:
    """Where a page's words go: the template's place, unless a face landed there and the other end of the page
    is clear of faces; then the words move there instead. Free: no redrawing, just a different place."""
    img = Image.open(io.BytesIO(png))
    faces = drawn_faces(img)

    def covers(band_zone):
        top, bottom = (v * img.height for v in ZONE_BANDS[band_zone])
        return any(min(y + h, bottom) - max(y, top) > h * 0.25 for (x, y, w, h) in faces)

    other = OTHER_ZONE[zone]
    return other if covers(zone) and not covers(other) else zone


def from_saved(full: bytes, face_box: list[int] | None) -> PreparedPhoto:
    """Rebuild the photo the book was accepted with, from the saved copy, without detecting again
    (the saved copy is recompressed, and a second check on it failed books that had passed)."""
    img = Image.open(io.BytesIO(full)).convert("RGB")
    if face_box:
        x, y, w, h = face_box
        cx, cy, half = x + w / 2, y + h / 2, max(w, h) * 0.9
        face = img.crop((int(max(0, cx - half)), int(max(0, cy - half * 1.1)),
                         int(min(img.width, cx + half)), int(min(img.height, cy + half * 0.9))))
    else:  # books accepted before boxes were saved
        face = img.copy()
    face.thumbnail((512, 512))
    return PreparedPhoto(full_png=_to_png(img), face_png=_to_png(face), face_box=face_box)
