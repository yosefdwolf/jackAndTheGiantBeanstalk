from pathlib import Path

from dotenv import load_dotenv

load_dotenv()  # local dev only; on Railway the key comes from service variables

import openai  # noqa: E402
from fastapi import FastAPI, File, Form, HTTPException, UploadFile  # noqa: E402
from fastapi.responses import FileResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from .faces import UploadError, prepare  # noqa: E402
from .generate import MOCK, generate  # noqa: E402
from .prompts import SCENE_DESCRIPTIONS, SCENES, STRENGTH, STYLES  # noqa: E402

STATIC = Path(__file__).resolve().parent.parent / "static"
MAX_UPLOAD_BYTES = 25 * 1024 * 1024  # phone photos can be large; they are downscaled on arrival

app = FastAPI(title="You and the Beanstalk")
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/options")
def options():
    return {
        "scenes": [{"caption": s, "description": SCENE_DESCRIPTIONS[s]} for s in SCENES],
        "styles": list(STYLES), "strengths": list(STRENGTH), "mock": MOCK,
    }


# Users pick scenes by number only; the scene text itself is never accepted from the client.
SCENE_CHOICES = {"both": SCENES, "1": SCENES[:1], "2": SCENES[1:]}


@app.post("/api/generate")
async def generate_route(
    photo: UploadFile = File(...),
    style: str = Form("storybook"),
    strength: int = Form(2),
    which: str = Form("both"),
):
    data = await photo.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "That photo is too large (max 25 MB).")
    if style not in STYLES or strength not in STRENGTH:
        raise HTTPException(400, "Unknown style or strength.")
    if which not in SCENE_CHOICES:
        raise HTTPException(400, "Unknown scene choice.")

    try:
        prepared = prepare(data)
    except UploadError as e:
        raise HTTPException(422, str(e))

    try:
        return await generate(prepared, style, strength, SCENE_CHOICES[which])
    except openai.BadRequestError as e:
        # A content-policy rejection of the photo, or a setting the model doesn't support.
        raise HTTPException(400, f"The image service rejected this request: {e.message}")
    except openai.OpenAIError:
        raise HTTPException(502, "The image service failed. Please try again in a moment.")
