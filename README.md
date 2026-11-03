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

## Database
Postgres on Railway; SQLite locally and in tests. Every request gets a ref, and every ref has a row.
Look a ref up in `books` (or `request_errors`), then read `book_events` in order: a `start` with no
`done` is where it stopped. Full design: [docs/schema.md](docs/schema.md). Migrations (Alembic) run on
each deploy before the app starts.

A book request returns at once. The pictures are drawn in the background, each with its own progress
bar on the page, and saved as they finish, so a dropped connection or a restart doesn't lose a paid book.

## Sign-in and limits
Making a book needs both the magic word (`APP_PASSWORD`, so only the class can use it) and a Google
sign-in (so each person's books are kept together). Everyone can make 3 books per UTC day
(`DAILY_BOOK_LIMIT`). Refused books never count, and a failed book counts only if a picture was drawn.
Admins (`ADMIN_EMAILS`) and the emails on the admin site's unlimited list have no limit.

## Reviews (real user feedback)
When a book finishes, its owner sees four questions under the flip book: Does this look like me? Does
the story ring true? Does it look professional? What isn't good? They can open the whole PDF from
there. Only the book's owner can answer, and it's one review per person: answering again, even on another of their books, replaces their earlier answers. For a crowd
study (e.g. CloudResearch Connect), link to `https://jack.graydates.com/?pid={participant ID}`: the ID
is kept through the Google sign-in and saved with the review, so each answer matches a payment.

## Admin site
`admin.jack.graydates.com` (locally `http://localhost:8000/admin`), for `ADMIN_EMAILS` only:
- **Books:** every book, filterable by status, reason, provider, date, slow pictures and failures, and
  searchable by ref, email or child's name. Click a book for its photo, every picture with its prompt,
  cost and provider request ID, and the step-by-step timeline (a step that never finished is flagged).
- **Reviews:** how many reviews there are, the average and spread for each 1–5 question, every
  "what isn't good" comment with its book, and a QR code for handing out the site.
- **Days:** books, failures, people and spend per day.
- **Errors:** everything in `request_errors` (wrong passwords, sign-in failures, page script errors, crashes).
- **Settings:** which provider and model draws *your own* books (OpenAI Flare, Agnes or mock; everyone
  else always gets OpenAI Flare), and the unlimited list.

## Run locally
Copy `.env.example` to `.env` and set `OPENAI_API_KEY` and `APP_PASSWORD`. `.env` is gitignored.
Without Google credentials, add `DEV_LOGIN=1` to sign in locally with no Google (it only works on
localhost, and turns itself off once `GOOGLE_CLIENT_ID` is set). Then:
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
- `DATABASE_URL`: add it as a reference to the Postgres service (Variables → Add Reference → Postgres → `DATABASE_URL`).
- `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`: from a Google Cloud OAuth client (Web application) with
  redirect URIs `https://jack.graydates.com/auth/callback`, `https://admin.jack.graydates.com/auth/callback`
  and `http://localhost:8000/auth/callback`.
- `SESSION_SECRET`: a long random string that signs the sign-in cookie.
- `ADMIN_EMAILS`: comma-separated emails allowed on the admin site.
- `COOKIE_DOMAIN=jack.graydates.com`, so one sign-in works on both the book site and the admin site.
- `AGNES_API_KEY` (optional): lets an admin pick Agnes for their own test books.

The admin site needs `admin.jack.graydates.com` added as a custom domain in Railway, plus a CNAME for
`admin.jack` at the DNS host.

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
