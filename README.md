# Jack and the Beanstalk — a picture book starring your child

Upload a child's photo, add their name and a few details, and download a picture book where the child is
the hero: Jack and the Beanstalk or Little Red Riding Hood. Each book is a real book of 25 pages: a cover
("Little Red Riding Hood, starring Sarah"), a title page, a copyright page from the publisher
(YWolfpublishing), 20 story pages, The End, and About Me on the back cover. A finished book can be ordered as
a printed hardcover, shipped to a US address (Lulu's sandbox: nothing is really printed).

## How it's built
The book is data; the code is generic. To add a page, add an entry to the story file. A new style, page
type or image provider is one new class.

| Piece | File | What it does |
|---|---|---|
| Story | `stories/jack_and_the_beanstalk.yaml` | The storyboard. Per page: text, cast, scene, mood, composition, where the text goes, and the line the progress card shows while it's drawn. Also everything on the site that belongs to the story (`site:`: the title, the button, the progress words, placeholders, the PDF name), its library blurb and cover, and which page becomes each book's cover on the bookshelf. |
| Style | `app/book/styles.py` | `ArtStyle` abstract class. `Animated3DStyle` is the book's style; its wording is sent unchanged in every call. |
| Cast | `app/book/cast.py`, `app/book/bible.py` | Reference sheets. The child's is drawn from the upload. Every story character's is drawn once from the story file and kept, with every version, in the database (the admin site's Characters tab). |
| Prompts | `app/book/prompts.py` | Builds every prompt: reference images, style, world, scene, mood, composition, then "only these characters appear." |
| Pages | `app/book/pages.py` | `Page` abstract class. `IllustratedPage` and `AboutMePage` are registered by type name. |
| Providers | `app/book/providers.py` | `ImageProvider` abstract class. OpenAI (`gpt-image-2.5-flare`) and a free mock. |
| PDF | `app/book/pdf.py` | Full-bleed art, with the story text drawn on top in a real font. The image model never draws text. About Me is last. |
| Jobs | `app/book/jobs.py` | Draws the hero sheet, then every page, 7 at a time: the child added into the page's saved scene (scene bible, `app/book/scenes.py`), or a page without the hero reused whole. Each picture gets up to 3 tries a short pause apart (a failed try isn't charged); if one still fails, the book stops and its owner can retry the missing pictures by hand. |
| Progress | `static/clothesline.js` | The pages "drying on a line" while a book is drawn: each fills with colour, the left-most takes each finished picture onto the stack, a failed try tears. Above it, one bar names the stage. |

**Keeping the child the same on every page:** one hero sheet and one style string, reused on every
call. Each page sends only the sheets for the characters in it, so nobody shows up who shouldn't (for
example, the cow on page 3, after she's been sold).

Prompts were developed by hand in the OpenAI Playground first, then moved into the story file.

**The library:** the front page (`/`) lists every story in `stories/`, each with its `blurb` and
`cover` from the story file. Each story has its own page at
`/stories/<name>` (e.g. `/stories/jack-and-the-beanstalk`), dressed in that story's theme. The pages
every story shares (the library, the bookshelf at `/bookshelf` with every book you've made, the wallet,
privacy) use the general `static/themes/library/` look: a reading room painted once by `python -m scripts.make_theme_art library`.
Every page has the same link bar (`static/nav.html`), which stays at the top while scrolling.

## Database
Postgres on Railway; SQLite locally and in tests. Every request gets a ref, and every ref has a row.
Look a ref up in `books` (or `request_errors`), then read `book_events` in order: a `start` with no
`done` is where it stopped. Full design: [docs/schema.md](docs/schema.md). Migrations (Alembic) run on
each deploy before the app starts.

A book request returns at once. The pictures are drawn in the background, each with its own progress
bar on the page, and saved as they finish, so a dropped connection or a restart doesn't lose a paid book.

## Sign-in and the wallet
Making a book needs both the magic word (`APP_PASSWORD`, so only the class can use it) and a Google
sign-in (so each person's books are kept together).

Each book costs $0.99 (`BOOK_PRICE_CENTS`), paid from the person's wallet at `/wallet`. They add $1,
$5, $10, $20 or any amount up to $100 on Stripe's checkout page (test mode only: `STRIPE_SECRET_KEY` must start with `sk_test_`).
A payment is credited once, after the server asks Stripe whether it was paid, so no webhook is needed.
The book is charged only once every check has passed, so a refused photo costs nothing, and retrying
a failed book's missing pictures is free. Every credit and debit is a row in `transactions`, which is
the history the wallet page shows.

Two kinds of money back:
- **Unspent money to the card, straight away.** No review: it was never used. Stripe refunds it
  across their top-ups, newest first.
- **A book that came out wrong, reviewed.** The person says what went wrong; the admin looks at the
  book in the Refunds tab, and approving puts its price back in their wallet (not the card).
  Reviewed, since otherwise anyone could get every book free. Each request emails the admins
  (`SMTP_*`, e.g. Gmail with an app password; without it the email is only logged).

Admins (`ADMIN_EMAILS`) and the emails on the admin site's unlimited list make books for free.

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

**Adding a story:** add one file to `stories/`; see [stories/README.md](stories/README.md). Its characters' pictures are
drawn by the first book and kept in the database.

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

## Printed books (Lulu)
"Order a printed copy" under a finished book opens `/print?book=<ref>` (`static/print.html`,
`app/printing.py`):
1. **Look it over.** The PDF shows in the page (and the flip book is a click away). Nothing can be priced or
   ordered until the reader ticks that it's ready to print.
2. **Address.** US only, checked field by field (state, ZIP, a 10-digit phone), each problem shown under its
   field.
3. **Price.** Lulu quotes printing, shipping and tax for that address. The price is that quote, plus Stripe's
   fee on the money added (2.9% + 30¢), plus `PRINT_PROFIT_CENTS` ($5), rounded up to the next .99. Pricing
   charges nothing.
4. **Place it.** The wallet is charged (with a one-click card top-up for just the difference if it's short),
   and Lulu gets a print job. If Lulu refuses it, the money goes straight back into the wallet.
5. **Status.** The order page asks Lulu for news at most once a minute and shows it in plain words
   (being checked, accepted, printing, shipped with tracking, delivered). Admin's **Printed** tab lists every
   order with what Lulu charged, what the book cost to draw, Stripe's fee and what we kept.

**The print files.** Lulu downloads two PDFs from signed links on this site (good for 14 days), built fresh
from the saved pictures: the inside pages (11.25 × 8.75 in with bleed, padded to Lulu's 24-page hardcover
minimum) and a wraparound cover (About Me on the back, a spine, the front cover), sized by Lulu's
cover-dimensions call. Every font is embedded (DejaVu Serif and Vera Sans; Lulu refuses PDFs that only name a
font), and a test checks it.

**The sandbox.** `LULU_API` is Lulu's sandbox: jobs go through Lulu's file checks but are never printed or
shipped. A sandbox job waits as "UNPAID" until it's paid in the sandbox developer portal with a test card. To
go live: production keys from developers.lulu.com, `LULU_API=https://api.lulu.com`, and a payment card on that
Lulu account.

**Names and About Me are checked before anything is charged or drawn** (`app/book/about_check.py`): OpenAI's
free moderation model, then a cheap question to gpt-4.1-mini (is the name a real-sounding name, not an insult
or keyboard mashing; is every answer fine to print in a child's book). If OpenAI can't be reached, a word list
does the job. A refusal names the field and says what to change.

## Cost
Drawing a book costs us under the $0.99 price: $0.59 for the book in the first test print order (21
pictures, any retries, and the picture checks). Each call's
cost is in the logs, each book's total is on its `book done` line, and admin's Money panel shows the average
beside the $0.99 price. A printed book's costs are in [WRITEUP.md](WRITEUP.md).

See [to-do.md](to-do.md) for what still needs work.
