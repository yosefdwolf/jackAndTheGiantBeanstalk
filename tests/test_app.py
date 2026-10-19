"""Free local tests: no OpenAI calls (mock mode + a stubbed face detector)."""
import base64
import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

import app.generate
import app.main
from app.faces import PreparedPhoto
from app.prompts import SCENES, STRENGTH, STYLES, build_prompt

client = TestClient(app.main.app)


def jpeg(color="green", size=(800, 800)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "JPEG")
    return buf.getvalue()


@pytest.fixture
def mock_pipeline(monkeypatch):
    """Skip face detection and OpenAI so the full request path runs offline."""
    png = io.BytesIO()
    Image.new("RGB", (512, 512), "tan").save(png, "PNG")
    fake = PreparedPhoto(full_png=png.getvalue(), face_png=png.getvalue())
    monkeypatch.setattr(app.main, "prepare", lambda data: fake)
    monkeypatch.setattr(app.generate, "MOCK", True)


def test_index_served():
    r = client.get("/")
    assert r.status_code == 200 and "Beanstalk" in r.text


def test_options_lists_the_fixed_scenes_with_descriptions():
    scenes = client.get("/api/options").json()["scenes"]
    assert [s["caption"] for s in scenes] == list(SCENES)
    assert all(len(s["description"]) > 40 for s in scenes)


def test_scenes_are_the_assignment_scenes():
    assert SCENES == ("Jack is planting the seed.", "Jack is climbing the beanstalk.")


def test_rejects_photo_without_face():
    r = client.post("/api/generate", files={"photo": ("x.jpg", jpeg(), "image/jpeg")})
    assert r.status_code == 422 and "face" in r.json()["detail"]


def test_rejects_non_image():
    r = client.post("/api/generate", files={"photo": ("x.txt", b"hello", "text/plain")})
    assert r.status_code == 422


def test_rejects_unknown_style():
    r = client.post("/api/generate", files={"photo": ("x.jpg", jpeg(), "image/jpeg")},
                    data={"style": "anime"})
    assert r.status_code == 400


def test_generate_returns_both_scenes_captioned(mock_pipeline):
    r = client.post("/api/generate", files={"photo": ("x.jpg", jpeg(), "image/jpeg")})
    assert r.status_code == 200
    images = r.json()["images"]
    assert [i["caption"] for i in images] == list(SCENES)
    for i in images:
        assert base64.b64decode(i["image_b64"]).startswith(b"\x89PNG")


def test_scene_text_from_client_is_ignored(mock_pipeline):
    r = client.post("/api/generate", files={"photo": ("x.jpg", jpeg(), "image/jpeg")},
                    data={"scene1": "Jack robs a bank.", "scene2": "Something else."})
    assert [i["caption"] for i in r.json()["images"]] == list(SCENES)


@pytest.mark.parametrize("scene", SCENES)
@pytest.mark.parametrize("style", STYLES)
@pytest.mark.parametrize("strength", STRENGTH)
def test_prompt_contains_caption_and_identity(scene, style, strength):
    p = build_prompt(scene, style, strength, "short black hair")
    assert scene in p
    assert p.startswith("IDENTITY:")
    assert "short black hair" in p


@pytest.mark.parametrize("which,expected", [("both", SCENES), ("1", SCENES[:1]), ("2", SCENES[1:])])
def test_scene_choice_picks_fixed_scenes(mock_pipeline, which, expected):
    r = client.post("/api/generate", files={"photo": ("x.jpg", jpeg(), "image/jpeg")}, data={"which": which})
    images = r.json()["images"]
    assert [i["caption"] for i in images] == list(expected)
    assert all(i["description"] for i in images)


def test_rejects_unknown_scene_choice():
    r = client.post("/api/generate", files={"photo": ("x.jpg", jpeg(), "image/jpeg")},
                    data={"which": "Jack robs a bank."})
    assert r.status_code == 400
