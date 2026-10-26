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

## Cost
About $0.10 per book: the hero sheet plus three wide pages at medium quality. Every call prints its
cost in the server log as `[cost] …`.

See [to-do.md](to-do.md) for what still needs work.
