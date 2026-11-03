# To do

What still needs work in this build, most important first.

## Book quality
- **Two of the supporting character sheets are turnaround sheets.** `mother.png` and `old_man.png` came out with side and back views and close-up panels, because the prompt said "character reference sheet". The model could copy that multi-panel layout into a page. The prompt now asks for a single front view; those two sheets should be regenerated (`python -m scripts.make_character_sheets mother old_man`). The mother also came out younger and less worn than the approved Playground version.
- **The hero sheet is redrawn for every book, with no way to approve it first.** If the cartoon doesn't look like the child, all three pages inherit that. A "here's your cartoon, keep it or redraw it" step before the pages would catch it early, at the cost of one extra call.
- **Bean count and colours drift.** The prompt asks for exactly five beans in five named colours. Playground runs showed four on page 2 and six or seven on page 3 before that wording was added; it hasn't been checked across many runs.
- **Text areas are requested, not guaranteed.** Each page asks for a plain band (lower third, top sky, dark grass). If the model puts a face there, the text lands on it. Next step: check the band's detail level after generating and nudge the text.
- **Mood swings between pages.** Pages 1–2 came out too bright and happy until the world line and per-page mood were added. That needs re-checking whenever a page is added.
- **No measured likeness check across pages yet.** The old ArcFace eval was for the two-scene app and was removed. It should come back as: photo vs hero sheet, and hero sheet vs each page, so "Jack's face drifts by page 3" shows up as a number.

## Pipeline
- **Pages 4–20 aren't written.** Page 4 (the beanstalk at dawn) is next. Each page is one entry in `stories/jack_and_the_beanstalk.yaml`.
- **Progress bars estimate, they don't measure.** Each picture's bar follows how long that kind of picture usually takes (median of recent ones), not real progress from the model. OpenAI can stream partial images; showing those would be truer.
- **Background books run inside the web process.** A deploy interrupts them (they resume on restart), and two app instances would each try to resume the same book. That's fine on one Railway instance; more instances need a real job queue.
- **The PDF font is the built-in Times.** A picture-book font file (licensed for embedding) would look better.
- **OpenAI's safety filter sometimes blocks ordinary pages.** Live book d594a533 lost 2 of 3 pages to it. There's no automatic retry (the assignment says no loops around the API call); instead the reader gets a "Try the missing pictures again" button that redraws only the failed ones. Worth finding which words in the page prompts trip it.

## Logging
- **Images are stored in Postgres** (about 1.5 MB per book). Fine for a class project; at scale they belong in object storage.

## Site
- **The face finder is a simple one (OpenCV Haar).** It turned away several real photos ("couldn't find a face"). It now tries a gentler second pass, and refused photos are kept so the admin can see them. If refusals keep happening, switch to a modern detector (e.g. OpenCV's YuNet).
- **Agnes is untested against the real API.** The provider follows Agnes's docs (OpenAI-style JSON, reference images under `extra_body.image`), but no book has been drawn with it yet. Try one admin book with `AGNES_API_KEY` set and check the admin timeline.
- **Reviewers need the magic word and a Google account.** Crowd participants must be given the magic word in the study instructions, and someone without Google can't take part.
- **No alert on failures.** The admin site lists them, but nobody is told when one happens.