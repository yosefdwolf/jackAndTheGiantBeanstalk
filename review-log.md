# Review log

Each run of the instructor-rubric review, newest first, with what was changed in response.

## Run 1 — 2026-11-08 — reviewer: Claude (instructor rubric) — browser: Claude in Chrome
Total 64/98 measured (was: none, first run)
PDF 20/40 (capped; lines sum to 26) · UI 16/18 · Money 20/20 · Engineering 8/20
Upload 16:19:43 → PDF 16:21:25 (102 s, Red) · 16:22:46 → ~16:25:20 (146–155 s, Jack)
Balance: 0.01 → fund 5.01 → Red 4.02 → Jack 3.03 → refund 0.00 (history reconciles)
Not measured: usable at 400px (2 pts) — window would not narrow below 814px with the side panel open
Changed since run 0: first run
Fix first:
1. Too slow: 102 s / ~150 s vs 60 s target (Eng -6). IMAGE_CONCURRENCY=7 (app/book/jobs.py:39) draws 20 pages in 3 waves after a ~16 s hero sheet; run all 20 at once if the provider's rate limit allows.
2. Text over the hero's face: Red p.16 "door" across mouth/chin, Red p.3 "stay" across forehead/eye; Jack p.15 caption sits on the giant's forehead (PDF -10, triggers 20-pt cap). text_zone is fixed per page in the story file (pages.py:42, pdf.py:87) — detect where faces landed and pick or shift to the clear band.
3. Retry count never shown (Eng -3). /api/books/{ref} already returns `attempt` per image (all 42 were 1); show it on each thumbnail and cap at 3.
4. review-log.md not in the repo (Eng -2). Commit this file.
5. Stale UI state (UI -2): nav "Wallet" amount lags until reload ($0.01 after +$5, $5.01 after a charge); Bookshelf once rendered as signed out while /api/me said signed in.
Also costing: a second, stock Little Red girl appears beside Sam on Red pp. 5 and 13, and Jack p.2 adds a sister (consistency -2); Red cover/About Me use the turnaround grid while Jack's use a portrait (template -1); white text on bright sky/flowers, plus visible stripe banding in the text scrim (Jack pp. 6, 17; Red pp. 8, 16) (legibility -1); to-do.md is a feature plan, not a defect list (-1).

### What changed in response
1. Speed: every page is drawn at once (IMAGE_CONCURRENCY 20); a rate-limit refusal is waited out without using a try. The scene bible (which drew each story's scenes inside the first book, ~50 s) is off for books (`SCENES=1` turns it on) until single-page tries look right.
2. Faces under text: after each page is drawn, a vision model (gpt-4.1-mini, ~0.05¢ a page) finds the faces; the words go in the band clear of them (the photo face detector missed cartoon faces).
3. Retries shown: "try 2 of 3" on the picture being drawn again and on the finished stack.
4. This file.
5. The nav's wallet amount refreshes after a payment, a book or a refund; a page shown again by the back button reloads (the stale signed-out Bookshelf).
- Extra children: the same vision check counts children; a page with the wrong number is drawn again (up to 3 tries, the best kept). Scenes, which caused the stock children, are off.
- The text shading is one smooth gradient (no stripes), darker over bright sky or flowers.
- The hero's cartoon is asked for as one portrait, not a sheet or grid.
- Checked on a test book after the fixes: Little Red took 49 s (was 102); the face check moved the words on 8 of
  20 pages, each clear of faces. A Jack book took 142 s because the safety filter falsely blocked the hero's cartoon
  once and page 3 twice (each blocked try is drawn again). On it, pages 7 and 8 had faces at both ends (the giant
  up top, Jack below), so the words covered the giant, and page 12 had two hens because its scene asked for two.
  Now a page with faces at both ends is drawn again, asked to keep faces out of the words' band, and page 12's
  scene has one hen.

