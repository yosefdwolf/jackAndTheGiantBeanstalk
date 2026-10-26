# Jack and the Beanstalk — a picture book starring your child

Upload a child's photo, add their name and a few details, and download `JackAndTheBeanstalk.pdf`: a
cartoon picture book where the child is Jack (or Jane), with an About Me page at the end. This build
makes the first three pages of the storyboard.

## How it's built
The book is data; the code is generic. To add a page, add an entry to the story file. A new style, page
type or image provider is one new class.

| Piece | File | What it does |
|---|---|---|
| Story | `stories/jack_and_the_beanstalk.yaml` | The storyboard. Per page: text, cast, scene, mood, composition, and where the text goes. |
| Style | `app/book/styles.py` | `ArtStyle` abstract class. `Animated3DStyle` is the book's style; its wording is sent unchanged in every call. |
| Cast | `app/book/cast.py` | Reference sheets. The child's is drawn from the upload. The mother's, Milky-White's and the old man's are drawn once and kept in `assets/characters/`. |
| Prompts | `app/book/prompts.py` | Builds every prompt: reference images, style, world, scene, mood, composition, then "only these characters appear." |
| Pages | `app/book/pages.py` | `Page` abstract class. `IllustratedPage` and `AboutMePage` are registered by type name. |
| Providers | `app/book/providers.py` | `ImageProvider` abstract class. OpenAI (`gpt-image-2.5-flare`) and a free mock. |
| PDF | `app/book/pdf.py` | Full-bleed art, with the story text drawn on top in a real font. The image model never draws text. About Me is last. |
| Builder | `app/book/builder.py` | Makes the hero sheet, renders every page in parallel (one call each, no retries), then builds the PDF. |

**Keeping the child the same on every page:** one hero sheet and one style string, reused on every
call. Each page sends only the sheets for the characters in it, so nobody shows up who shouldn't (for
example, the cow on page 3, after she's been sold).

Prompts were developed by hand in the OpenAI Playground first, then moved into the story file.

## Run locally
Copy `.env.example` to `.env` and set `OPENAI_API_KEY` and `APP_PASSWORD`. `.env` is gitignored. Then:
```bash
./scripts/run.sh          # macOS / Linux, real images
./scripts/run.sh --mock   # free placeholder images
```
```powershell
.\scripts\run.ps1 -Mock   # Windows
```
Open http://localhost:8000.

**Tests** (free, offline): `pip install -r requirements-dev.txt && python -m pytest`

**Supporting character sheets** (once, then commit them): `python -m scripts.make_character_sheets`

## Deploy (Railway)
The `Procfile` sets the start command and `.python-version` pins Python 3.12. Under **Variables**, set:
- `OPENAI_API_KEY`
- `APP_PASSWORD`: the password people must enter. Without it, the site refuses to make real books.

Leave `MOCK` unset.

## Logs (for post-mortems)
Every book gets a short ID. It's on every log line, in the `X-Book-Id` response header, and in any error
message the user sees ("… (ref 3f9a1c2e)"). Search Railway's logs for that ID. Each step logs when it
starts and when it ends, so a stuck call shows a `start` with no `done`:
```
INFO book=3f9a1c2e book requested ip=… gender=girl details=2
INFO book=3f9a1c2e start hero sheet call=images.edit model=gpt-image-2.5-flare size=1024x1024 refs=photo.png
INFO book=3f9a1c2e usage hero sheet text_in=238 image_in=480 out=439 cost=$0.018 openai_request=req_…
INFO book=3f9a1c2e done hero sheet 21.4s
INFO book=3f9a1c2e start page 1 … refs=hero.png,mother.png,milky_white.png
ERROR book=3f9a1c2e failed page 2 120.0s APITimeoutError
WARNING book=3f9a1c2e refused status=504 reason=timeout
```
Never logged: the password, the API key, the photo, or the child's name and details. `LOG_LEVEL` sets
the level (default `INFO`).

## Cost
About $0.12 per book (measured): the hero sheet plus three wide pages at medium quality. Each call's
cost is in the logs, and each book's total is on its `book done` line.

See [to-do.md](to-do.md) for what still needs work.
