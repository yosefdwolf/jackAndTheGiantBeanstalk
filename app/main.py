import hmac
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()  # local dev only; on Railway the key comes from service variables

import openai  # noqa: E402
from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile  # noqa: E402
from fastapi.responses import FileResponse, Response  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from .book.builder import PDF_NAME, build_book  # noqa: E402
from .book.cast import MissingSheetError  # noqa: E402
from .book.pages import ChildInfo  # noqa: E402
from .book.providers import is_mock  # noqa: E402
from .book.story import PRONOUNS, load_story  # noqa: E402
from .faces import UploadError, prepare  # noqa: E402

STATIC = Path(__file__).resolve().parent.parent / "static"
MAX_UPLOAD_BYTES = 25 * 1024 * 1024  # phone photos can be large; they are downscaled on arrival
MAX_FIELD = 300

app = FastAPI(title="Jack and the Beanstalk")
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/options")
def options():
    story = load_story()
    return {
        "title": story.title,
        "heroes": story.hero_names,
        "pages": len(story.pages),
        "mock": is_mock(),
    }


def check_password(given: str | None) -> None:
    """Every paid request needs APP_PASSWORD. If it isn't set, real books are refused (fail closed)."""
    expected = os.getenv("APP_PASSWORD", "")
    if not expected:
        if is_mock():
            return  # mock books cost nothing
        raise HTTPException(503, "The server has no APP_PASSWORD set, so it won't make books.")
    if not given or not hmac.compare_digest(given.encode(), expected.encode()):
        raise HTTPException(401, "Wrong password.")


@app.post("/api/book")
async def book_route(
    x_app_password: str | None = Header(None),
    photo: UploadFile = File(...),
    name: str = Form(...),
    gender: str = Form("boy"),
    age: str = Form(""),
    favourites: str = Form(""),
    about: str = Form(""),
):
    check_password(x_app_password)
    data = await photo.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "That photo is too large (max 25 MB).")
    if gender not in PRONOUNS:
        raise HTTPException(400, "Choose Jack or Jane.")
    name = name.strip()
    if not name:
        raise HTTPException(400, "Please enter the child's name.")
    if any(len(v) > MAX_FIELD for v in (name, age, favourites, about)):
        raise HTTPException(400, f"Each answer can be up to {MAX_FIELD} characters.")
    details = [(label, value.strip()) for label, value in
               (("Age", age), ("Favourite things", favourites), ("More about me", about)) if value.strip()]

    try:
        prepared = prepare(data)
    except UploadError as e:
        raise HTTPException(422, str(e))

    try:
        pdf = await build_book(prepared, ChildInfo(name, details), gender)
    except MissingSheetError as e:
        raise HTTPException(500, str(e))
    except openai.BadRequestError as e:
        raise HTTPException(400, f"The image service rejected this request: {e.message}")
    except openai.OpenAIError:
        raise HTTPException(502, "The image service failed. Please try again in a moment.")

    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{PDF_NAME}"'})
