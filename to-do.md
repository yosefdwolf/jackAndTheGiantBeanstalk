# To do

What still needs work in this build, most important first.

## Book quality
- **Supporting character sheets aren't in the repo yet.** `assets/characters/` needs `mother.png`, `milky_white.png` and `old_man.png`. Make them once (`python -m scripts.make_character_sheets`, or save the Playground versions) and commit them. Until then, real books fail with "No character sheet", and mock books use placeholders.
- **The hero sheet is redrawn for every book, with no way to approve it first.** If the cartoon doesn't look like the child, all three pages inherit that. A "here's your cartoon, keep it or redraw it" step before the pages would catch it early, at the cost of one extra call.
- **Bean count and colours drift.** The prompt asks for exactly five beans in five named colours. Playground runs showed four on page 2 and six or seven on page 3 before that wording was added; it hasn't been checked across many runs.
- **Text areas are requested, not guaranteed.** Each page asks for a plain band (lower third, top sky, dark grass). If the model puts a face there, the text lands on it. Next step: check the band's detail level after generating and nudge the text.
- **Mood swings between pages.** Pages 1–2 came out too bright and happy until the world line and per-page mood were added. That needs re-checking whenever a page is added.
- **No measured likeness check across pages yet.** The old ArcFace eval was for the two-scene app and was removed. It should come back as: photo vs hero sheet, and hero sheet vs each page, so "Jack's face drifts by page 3" shows up as a number.

## Pipeline
- **Pages 4–20 aren't written.** Page 4 (the beanstalk at dawn) is next. Each page is one entry in `stories/jack_and_the_beanstalk.yaml`.
- **One request builds the whole book.** That's fine for 3 pages (about a minute), but 20 pages would take several minutes and could hit request timeouts on the host. It needs a background job with a progress endpoint before the book grows much.
- **No title page or cover yet.**
- **The PDF font is the built-in Times.** A picture-book font file (licensed for embedding) would look better.
- **No retry when OpenAI's safety filter blocks a page.** That happened once, with an ordinary adult photo, and the same photo passed on the next try. Right now the whole book fails.

## Site
- **One shared password (`APP_PASSWORD`), no rate limit.** Anyone with the password can make unlimited books. A per-password or per-IP limit would cap the spend.
- **The webcam selfie hasn't been tested on Railway.** It can't run in the dev browser pane.
- **Deployed on Railway, while the assignment says Render.** Waiting to hear whether Railway is acceptable.
