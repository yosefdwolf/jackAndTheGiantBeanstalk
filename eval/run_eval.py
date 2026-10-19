"""Offline check that both production requirements hold. Not part of the web app.

Put test photos (several different people, with consent) in eval/photos/, then:
    pip install -r requirements-eval.txt
    python -m eval.run_eval

For each photo it generates the two default scenes (one call per scene, same as the app), then:
  * Likeness: ArcFace embeddings (InsightFace). Each output must match its own upload better
    than every other upload, and its similarity is reported next to the best wrong match.
  * Scene: a vision model checks each image against its caption, element by element.
Results go to eval/out/<timestamp>/results.md with the images, so prompt versions can be compared.
"""
import asyncio
import base64
import hashlib
import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np
from dotenv import load_dotenv

load_dotenv()

from app.faces import UploadError, prepare  # noqa: E402
from app.generate import VISION_MODEL, client, generate  # noqa: E402
from app.prompts import SCENES, build_prompt  # noqa: E402

ROOT = Path(__file__).resolve().parent
PHOTOS = ROOT / "photos"
STYLE, STRENGTH = "storybook", 2

JUDGE_PROMPT = """You are checking whether a Jack and the Beanstalk illustration faithfully shows its caption.
Caption: "{scene}"
The main character in the picture is Jack, whatever their age or gender; do not look for a name.
List the concrete visual elements the caption requires (action, key objects, setting),
then check each against the image. Also report whether any words or letters appear in the image.
Reply as JSON:
{{"elements": [{{"element": str, "present": bool}}], "has_text": bool, "faithful": bool, "notes": str}}
"faithful" is true only if every required element is clearly present and there is no text."""


def face_app():
    from insightface.app import FaceAnalysis
    fa = FaceAnalysis(name="buffalo_l", providers=["CPUExecutionProvider"])
    fa.prepare(ctx_id=-1, det_size=(640, 640), det_thresh=0.3)  # low threshold: cartoon faces
    return fa


def embed(fa, png: bytes):
    img = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_COLOR)
    faces = fa.get(img)
    if not faces:
        return None
    biggest = max(faces, key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]))
    return biggest.normed_embedding


async def judge(scene: str, png: bytes) -> dict:
    b64 = base64.b64encode(png).decode()
    resp = await client().chat.completions.create(
        model=VISION_MODEL,
        response_format={"type": "json_object"},
        messages=[{"role": "user", "content": [
            {"type": "text", "text": JUDGE_PROMPT.format(scene=scene)},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
        ]}],
    )
    return json.loads(resp.choices[0].message.content)


async def main():
    paths = sorted(p for p in PHOTOS.iterdir() if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"})
    if len(paths) < 2:
        sys.exit("Put at least 2 photos of different people in eval/photos/ (more is better).")

    prompt_version = hashlib.sha1("".join(build_prompt(s, STYLE, STRENGTH) for s in SCENES).encode()).hexdigest()[:8]
    out = ROOT / "out" / time.strftime("%Y%m%d-%H%M%S")
    out.mkdir(parents=True)
    fa = face_app()

    people = []
    for p in paths:
        try:
            prepared = prepare(p.read_bytes())
        except UploadError as e:
            print(f"skip {p.name}: {e}")
            continue
        print(f"generating {p.name} …")
        result = await generate(prepared, STYLE, STRENGTH)
        outputs = []
        for i, img in enumerate(result["images"], 1):
            png = base64.b64decode(img["image_b64"])
            (out / f"{p.stem}_scene{i}.png").write_bytes(png)
            outputs.append({"scene": img["caption"], "png": png, "file": f"{p.stem}_scene{i}.png"})
        people.append({"name": p.stem, "ref": embed(fa, prepared.full_png), "outputs": outputs,
                       "description": result["face_description"]})

    rows, passes = [], {"likeness": 0, "scene": 0, "total": 0}
    for person in people:
        for o in person["outputs"]:
            passes["total"] += 1
            e = embed(fa, o["png"])
            sims = {q["name"]: float(np.dot(e, q["ref"])) for q in people
                    if e is not None and q["ref"] is not None}
            own = sims.get(person["name"])
            others = [v for k, v in sims.items() if k != person["name"]]
            best_other = max(others) if others else None
            likeness_ok = own is not None and (best_other is None or own > best_other)
            verdict = await judge(o["scene"], o["png"])
            passes["likeness"] += likeness_ok
            passes["scene"] += bool(verdict.get("faithful"))
            missing = [el["element"] for el in verdict.get("elements", []) if not el.get("present")]
            rows.append(
                f"| {person['name']} | {o['scene']} | ![]({o['file']}) | "
                f"{'—' if own is None else f'{own:.2f}'} | "
                f"{'—' if best_other is None else f'{best_other:.2f}'} | "
                f"{'✅' if likeness_ok else '❌'} | {'✅' if verdict.get('faithful') else '❌'} | "
                f"{', '.join(missing) or '—'} |"
            )

    t = passes["total"]
    report = "\n".join([
        f"# Eval run {out.name}",
        f"Prompt version `{prompt_version}` · style `{STYLE}` · strength `{STRENGTH}` · {len(people)} people",
        "",
        f"**Likeness:** {passes['likeness']}/{t} outputs match their own upload best  ",
        f"**Scene:** {passes['scene']}/{t} outputs judged faithful to the caption",
        "",
        "| Person | Caption | Image | Sim to own | Best other | Likeness | Scene | Missing |",
        "|---|---|---|---|---|---|---|---|",
        *rows,
    ])
    (out / "results.md").write_text(report)
    print(report.split("| Person")[0])
    print(f"Full report: {out / 'results.md'}")


if __name__ == "__main__":
    asyncio.run(main())
