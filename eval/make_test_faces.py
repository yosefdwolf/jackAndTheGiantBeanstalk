"""Make photorealistic portraits of FICTIONAL people for eval/photos/ (no real faces, no consent issues).

    python -m eval.make_test_faces

Varied on purpose: age, skin tone, gender, glasses, facial hair, hair texture. Skips files that exist.
"""
import base64
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

PHOTOS = Path(__file__).resolve().parent / "photos"

PEOPLE = {
    "synthetic_a": "a woman in her late 20s of West African descent, dark skin, short natural coily hair",
    "synthetic_b": "a man in his 60s of East Asian descent, gray hair, thin rectangular glasses",
    "synthetic_c": "a man in his 30s of South Asian descent, full black beard, wavy hair",
    "synthetic_d": "a teenage girl of Northern European descent, pale freckled skin, long straight red hair",
    "synthetic_e": "a woman in her 50s of Latin American descent, medium-brown skin, shoulder-length curly dark hair, round glasses",
}


def main():
    client = OpenAI()
    PHOTOS.mkdir(exist_ok=True)
    for name, who in PEOPLE.items():
        path = PHOTOS / f"{name}.png"
        if path.exists():
            continue
        print(f"making {name} …")
        resp = client.images.generate(
            model="gpt-image-1-mini",
            quality="medium",
            size="1024x1024",
            prompt=(
                f"A casual smartphone selfie photo of {who}. Head and shoulders, facing the camera, "
                "neutral friendly expression, natural indoor daylight, plain background. "
                "Photorealistic, an ordinary everyday person, not a celebrity."
            ),
        )
        path.write_bytes(base64.b64decode(resp.data[0].b64_json))


if __name__ == "__main__":
    main()
