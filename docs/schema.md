# Database schema

Postgres on Railway (`DATABASE_URL`). Locally and in tests it's SQLite, with the same models
(`app/db/models.py`). Migrations live in `migrations/` (Alembic) and run on every deploy before the app
starts (`Procfile`).

## The rule: every request has a ref, and every ref has a row
- **A book request** creates its `books` row before any check runs. A wrong password or a photo with
  no face is a row too (`status = refused`, with `refused_reason`).
- **Anything else that fails** (a page script error, an unexpected crash, and later the review form and
  sign-in) is a row in `request_errors`.
- The ref is shown to the user in every error message, returned as the `X-Request-Id` header, and
  printed on every log line. Given a ref, look it up in `books` or `request_errors`, then read
  `book_events` in order.
- **A `start` event with no matching `done` is where a book got stuck.**

## Tables

| table | one row per | notes |
|---|---|---|
| `users` | Google account | `google_sub` is Google's stable ID. Admin rights come from `ADMIN_EMAILS`, not the database. |
| `unlimited_emails` | email whose books are free | managed in the admin site; can be added before the person signs in |
| `books` | book request | `id` is the ref. `status`: queued, running, done, failed, interrupted, refused. Also holds which provider and model drew it, the prompt version, the child's name and About Me details, and the total cost. |
| `uploads` | book | the photo the model saw (1024px, WebP), kept for debugging |
| `images` | generated image | the hero sheet (page 0) and each page: status (waiting, drawing, done, failed), the exact prompt, the attached character sheets, the image (WebP), tokens, cost, the provider's request ID, any error, and timings. Unique on (book, kind, page), so a resumed book can't duplicate an image. |
| `book_events` | step event | the trail: start, done, failed, info, refused, with a duration and fields. Never holds the password, the photo, or the child's name and details. |
| `request_errors` | failure outside a book | the ref, path, status, error type, message, traceback and browser |
| `activity` | something a person did | sign-ins, money in and out, books asked for, finished and failed, reviews: everything logged outside a book, plus a book's milestones. The admin's Activity tab. |
| `page_events` | a page view or click | for the admin's Funnel tab: an anonymous visitor ID from the browser, the event name, the path and a few whitelisted fields. No IP, never typed text. Deleted after 90 days; nothing from Do Not Track or GPC browsers. |
| `admin_settings` | admin | the debug panel's provider, model, quality and size; these apply only to that admin's books |
| `reviews` | review response | three 1–5 ratings plus "what isn't good", by the book's owner only. `respondent_key` is the user's id (one review per person; answering again, on any of their books, replaces it). `source` is `site` or `connect`; `connect_id` is the crowd participant ID from the study link |
| `settings` | site-wide value | e.g. `featured_review_book_id` |
| `payments` | Stripe Checkout session | `id` is Stripe's session id. `status`: open, paid, expired. `refunded_cents` is how much of it has gone back to the card. |
| `transactions` | change to a wallet | `amount_cents` is + for a credit, − for a debit; the balance is the sum. `kind`: deposit, book, refund (to the card), book_refund (to the wallet), with the book, payment, Stripe refund or refund request that caused it. |
| `refund_requests` | book someone says came out wrong | the book, its price, what they said, and the admin's answer. `status`: pending, approved (the price goes back in their wallet), denied. Unspent money back to the card needs no request: it's a `refund` row in `transactions` with Stripe's refund id. |

## Decisions
- **Images are stored in Postgres as WebP (quality 90)**, about 1.5 MB per book. PDFs aren't stored:
  they're rebuilt from the saved images on each download, which takes under a second.
- **Money is in whole cents,** never floats. A book is charged inside a per-user row lock, so two
  books can't both spend the last 99¢.
- **Restarts:** at startup, books still `queued` or `running` become `interrupted` and resume. Images
  already `done` are reused, not redrawn.
- **No deletion feature.** The upload page says plainly that the photo and book are kept.
