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

## How it works
1. **Upload checks before any API call** (`app/faces.py`): fix orientation, convert HEIC, require one clear face (a background pattern isn't counted as a second person), make a face close-up.
2. **Cartoonify once**: `gpt-image-2.5-flare` redraws the photo from scratch as a cartoon portrait in the chosen style and strength. A cheap vision model first writes a short description of the face, which goes into the prompt.
3. **Scenes from the cartoon, not the photo**: each scene is one call that uses the cartoon portrait as the character, so it can't copy the realistic face, and both scenes show the same character. The scenes run in parallel, with no retry loops.
4. **Fully art-directed scenes** (`app/prompts.py`): action, setting, props, wardrobe, pose, camera, lighting, and what to avoid. A medium close shot keeps the face large.
5. **Jack or Jane**: the toggle swaps the name in the captions and prompts. The story title stays "Jack and the Beanstalk."

Models tried: `gpt-image-1-mini` lost the face; `gpt-image-1` at low quality was blurry and cost more. Editing the photo directly kept the face too photographic, which is why the app cartoonifies first.

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

Cost: about $0.02 per image at `gpt-image-2.5-flare` medium (measured), so about $0.06 for the cartoon portrait plus both scenes. Every call prints its token cost in the server log as `[cost] …`.
