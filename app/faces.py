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
EYES = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_eye.xml")


class UploadError(ValueError):
    """Upload is unusable; message is safe to show the user."""


@dataclass
class PreparedPhoto:
    full_png: bytes
    face_png: bytes


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
    faces = CASCADE.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=6, minSize=(60, 60))

    if len(faces) == 0:
        raise UploadError("We couldn't find a face. Use a clear, front-facing photo with good light.")
    faces = sorted(faces, key=lambda f: f[2] * f[3], reverse=True)
    x, y, w, h = faces[0]
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
    return PreparedPhoto(full_png=_to_png(img), face_png=_to_png(face))
