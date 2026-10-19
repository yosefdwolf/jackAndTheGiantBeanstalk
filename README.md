# You and the Beanstalk

Upload a photo and get cartoonified into the two fixed scenes from Jack and the Beanstalk, each captioned with its scene:

1. *Jack is planting the seed.*
2. *Jack is climbing the beanstalk.*

The scenes live only in `app/prompts.py`. The API accepts no scene text, so users can't change them.

Works in Safari on iPhone/iPad (including HEIC photos, selfie camera, and saving to Photos through the share sheet) and in Chrome/Edge/Firefox on Windows and Mac.

## Run locally

Put your key in `.env` (copied from `.env.example`; it's gitignored). Then:

**macOS / Linux**
```bash
./scripts/run.sh          # real images
./scripts/run.sh --mock   # free: placeholder images, no OpenAI calls
```

**Windows (PowerShell)**
```powershell
.\scripts\run.ps1
.\scripts\run.ps1 -Mock
```

Open http://localhost:8000. To test on your phone, join the same Wi-Fi and open `http://<your computer's IP>:8000`.

**Tests** (free, offline):
```bash
pip install -r requirements-dev.txt
python -m pytest
```

## How likeness is kept
1. **Upload checks before any API call** (`app/faces.py`): fix orientation, convert HEIC, require exactly one large face, make a face close-up.
2. **One call per scene, always from the original photo**: never chained, run in parallel, no retry loops.
3. **`gpt-image-2.5-flare` edit at medium quality**, from the original photo. We tried other models: `gpt-image-1-mini` lost the face entirely, and `gpt-image-1` at low quality was blurry and costlier. Flare looked clearly like the person.
4. **Written face description**: a cheap vision model describes the face, and that text goes into the prompt.
5. **Fully art-directed scenes** (`app/prompts.py`): identity first, then style, action, setting, props, wardrobe, pose, camera, lighting, and what to avoid. The medium close shot keeps the face large. Cartoon strength is capped.

## Deploy on Railway
Connect the repo. The `Procfile` provides the start command and `.python-version` pins Python 3.12. Under **Variables**, set `OPENAI_API_KEY` (and optionally `IMAGE_MODEL`, `IMAGE_QUALITY`, `VISION_MODEL`). Leave `MOCK` unset.

## Proving both requirements hold
```bash
pip install -r requirements-eval.txt
python -m eval.run_eval
```
Put photos of several different people (with consent) in `eval/photos/`. That folder is gitignored. The report in `eval/out/<timestamp>/results.md` contains:
- **Likeness**: the ArcFace similarity between each output and its own upload, compared with its best match among the other uploads. It passes when the output matches its own person best.
- **Scene**: a vision model checks each image against its caption, element by element.

Edit `app/prompts.py`, re-run, and compare reports until both requirements pass for everyone.

Cost: about $0.02 per scene at `gpt-image-2.5-flare` medium (measured), so about $0.04 for both scenes. Every call prints its token cost in the server log as `[cost] …`.
