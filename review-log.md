# Review log

Each run of the instructor-rubric review, oldest first, with what was changed in response.

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

## Run 2 — 2026-11-08 — reviewer: self — browser: Claude in Chrome
Total 83/94 measured (was 64/98 measured)
PDF 32/36 · UI 18/18 · Money 20/20 · Engineering 13/20
Upload 17:21:56 → PDF 17:23:29 (93 s, Jack; run 1 Jack was 146–155 s)
Balance: 0.00 → fund 5.00 → 2 builder books 3.02 → generate 2.03 → refund 0.00 (history reconciles back to Nov 7)
Not measured: one template shared by both stories (PDF 4), only Jack tested; usable at 400px (UI 2), the window
would not narrow below 589px
Changed since run 1: pages drawn at once; no text over any face on all 20 pages; "try N of 3" shown; nav balance
updates without a reload; review-log.md committed
Fix first:
1. Still over 60 s: 93 s (Eng -6). At 66 s five pages were on "try 3 of 3". Fix the most common `picture check
   failed` problem; where the only problem is placing the text, move the text instead of redrawing.
2. Captions cover what the page is about (PDF -4): "Chop! Chop!" over the axe hitting the stalk (story p.19);
   "the golden harp" into the top of the harp (story p.14).
3. to-do.md is still a feature plan, not a defect list (Eng -1).
4. The 400px layout is unverified (UI 2 unmeasured).

### What changed in response
1. Speed: book f03afd13's log showed the picture check failing pages wrongly. It counted Jack (drawn looking about
   16) as no child (pp. 2, 17) and his young-looking mother as a second child (pp. 10, 11, 18, 20), so those pages
   were drawn three times for nothing. The check is now told who belongs on the page (the hero counts as the child
   even if drawn older; a listed grown-up never does). On p.7 it boxed the giant's whole body as his "face", so a
   face box is now capped at a head's height. Faces at both ends of a page get one redraw at most; after that the
   words go where they cover less. The `picture check failed` and `kept the best try` events weren't being saved
   (the column was 16 characters); it's 32 now.
2. Each page in both story files names its `focus:` ("the axe biting into the beanstalk", "the golden harp"). The
   check finds it, and the words go at whichever end of the page keeps it clear (it never causes a redraw).
4. Checked locally at 390px: library, story page, bookshelf, wallet and the flip book all fit with no sideways
   scroll.

## Run 3 — 2026-11-09 — reviewer: self — browser: Claude in Chrome
Total 94/100 (was 83/94 measured)
PDF 36/40 · UI 20/20 · Money 19/20 · Engineering 19/20
Upload 13:28:22 → PDF ≤13:29:06 (≤44 s, Red b302b0d7) · 13:31:12 → PDF 13:31:57–13:32:10 (45–58 s, Jack faef47ac)
Balance: 3.02 → fund 8.02 → Red 7.03 → Jack 6.04 → refund 0.00 (two rows, −5.00 and −1.04; history reconciles back to Nov 7)
Avg cost per book: not shown in the app (admin API 403 for this account; see Fix first 2) (price $0.99)
Not measured: none. 400px measured at 396px in a same-origin iframe (side panel stops the window narrowing): no
sideways scroll, every field and the submit button inside x 16–380. Account was the builder's own, not a first-time
user. Photo: one the builder never developed with (adult man, entered as Daniel, 19).
Changed since run 2: both books under 60 s (93 s in run 2); "try 2 of 3" seen live on Jack p.14; Jack p.15 caption
now sits at the top, clear of the harp; empty wallet greys out the button with "A book costs $0.99. Add money to your
wallet", and the server refuses with 402 (main.py:352, :369) under a per-user lock (wallet.py:92).
Checked: both PDFs are cover + 20 story pages + About Me + The End (23 pp.), same layout; no text over any face on
any page of either; text is ReportLab Times-Bold (clean at zoom on Jack p.20); About Me shows Daniel / 19 /
basketball, hiking, pizza / Loves the beach; no keys in HEAD or any of 54 commits; character bible in stories /
characters / character_pictures; Daniel recognizably the same person on every page; after sign-out and sign-in,
b302b0d7's PDF still downloads (200, 23 pp.).
Fix first:
1. Caption over the thing the page is about (PDF -4): Jack PDF p.20 (story p.19), "cracked" runs across the axe blade
   where it bites the stalk. The story file says `text_zone: top`, `focus: the axe biting into the beanstalk`
   (stories/jack_and_the_beanstalk.yaml:434-435), but the face check found the giant up top and moved the words down
   onto the focus. When the faces-free band holds the focus, don't settle: redraw once asking for the axe low and the
   sky clear, or set the words smaller in the clear corner. Minor: Red p.3, the bottom of the basket is under the words.
2. Cost per book isn't tracked in full and isn't shown (Money -2). One image row per picture, and each try overwrites
   its cost (app/book/jobs.py:283), so retries vanish; vision-check calls go into log.add_cost, but log.total_cost()
   is never read, so Book.total_cost (jobs.py:510) is images only. Save every try and every vision call, and show
   "average $X over N books vs $0.99" in admin.
3. to-do.md's Defects list is stale (Eng -1): its one item (giant's whole body boxed as a face) was fixed in run 2;
   items 1–2 above aren't there.
4. Speed has little margin (0 pts now): Jack took 45–58 s with one retry (p.14, try 2). A second retry or a slow
   provider minute puts it over 60 s. Watch the slowest page in each book.
