# Print it and ship it: write-up

Live site: https://jack.graydates.com · Repo: https://github.com/yosefdwolf/jackAndTheGiantBeanstalk

## What I built

**A real book.** Every book is now 25 pages, in this order: the front cover ("Little Red Riding Hood, starring
Leo"), a title page, a copyright page ("Text and illustrations copyright © 2026 YWolfpublishing… Published by
YWolfpublishing"), the 20 story pages, The End, and About Me on the back cover. The story starts on the first page
after the copyright page. Each page also keeps the words it was drawn with, so a later edit to a story can't put
the wrong words on a finished book.

**A printed hardcover, shipped.** Under a finished book, "Order a printed copy" opens an order page:
1. The reader looks through the PDF (shown in the page) and ticks that it's ready to print. Nothing is priced or
   sent before that.
2. They type a US address. Each field is checked, and a problem is shown under that field.
3. They see the price for that address. Pricing charges nothing.
4. They place the order. The wallet pays; if it's short, one button tops up just the difference with a card and
   comes back to the order. The app sends Lulu a print job. If Lulu refuses it, the money goes straight back.
5. The order page follows the job in plain words: being checked, accepted, printing, shipped (with tracking),
   delivered. Admin's Printed tab lists every order with the costs and what we kept.

The printer is **Lulu's Print API**, in its sandbox: a job goes through Lulu's real file checks but is never
printed or shipped. The product is an 11 × 8.5 in landscape hardcover, full colour, premium paper. Lulu downloads
two files from signed links on the site: the inside pages (with bleed, padded to Lulu's 24-page hardcover
minimum) and a wraparound cover (About Me on the back, a spine, the front cover).

**The first test order was refused**, and that taught me something: Lulu rejects a PDF whose fonts aren't embedded,
and the standard PDF fonts (Times, Helvetica) aren't. The book now carries its own fonts, a test checks every PDF
for it, and the next order (Lulu job 364801) was accepted in about 20 seconds.

**Checking what people type.** Before a book is charged or drawn, the name and every About Me answer go through
OpenAI's moderation model (free) and a short question to gpt-4.1-mini: is the name a real-sounding name, not an
insult, an epithet or keyboard mashing, and is each answer fine to print in a child's book? A refusal names the
field and says what to change; nothing is charged. If OpenAI can't be reached, a word list does the job.

## The business model

Two things are for sale, both paid from the same wallet:
- **The book itself, $0.99.** Drawn in under a minute, read as a flip book, downloaded as a PDF.
- **A printed hardcover, shipped:** Lulu's charge for that address, plus Stripe's fee, plus **$5**, rounded up to
  the next .99.

The price follows Lulu's quote for each address, so if Lulu's prices or the shipping change, the reader's price
moves with them and we never sell below cost. The $5 is the same on every book, so the reader pays only for the
printing and shipping their address really needs. The cheapest shipping (USPS mail) is the only option, which
keeps the price down. An address that would cost more than $100 is refused.

## Cost per book and margin

The real numbers from the order that Lulu accepted (shipped to Woodmere, NY):

| | |
|---|---:|
| Lulu: printing, mail shipping and tax | $24.53 |
| Drawing the book: 21 pictures, retries and picture checks | $0.59 |
| Stripe's fee on the $30.99 the reader adds (2.9% + 30¢) | $1.20 |
| **Total cost** | **$26.32** |
| **Price** | **$30.99** |
| **We keep** | **$4.67 (15%)** |

The math behind the price: ($24.53 + $5.00 + $0.30) ÷ (1 − 0.029) = $30.72, rounded up to **$30.99**. Rounding
up to .99 adds a few cents; drawing the book (59¢) comes out of the $5, which is why we keep $4.67 rather than
$5. The drawing is already paid for by the book's own $0.99, so the $4.67 is the low end.

Another address for comparison (Washington, DC): Lulu $23.95 ($16.14 printing, $5.69 shipping, $1.37 tax), price
$30.99. Faster shipping costs more at Lulu ($32.48 ground to the home, $39.90 expedited), which is why the cheapest
is the default.

## How I checked it

- **storybook-review Run 4: 94/100** (in `review-log.md`). A new account, a photo I never developed with, both
  stories: 44 s and 48 s from upload to PDF, $0.99 charged each time, refund and history reconcile, both PDFs
  25 pages with no words over a face.
- **A live sandbox order,** from approval to Lulu accepting the files.
- **216 automated tests,** including approval before pricing, address checks, money back when Lulu refuses,
  a wallet that's short, a rude name refused before any charge, and every PDF's fonts embedded.

## What's still wrong

In `to-do.md`. The main one: on Jack's page 19 the words cover the axe biting the beanstalk.
