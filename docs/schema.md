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
| `unlimited_emails` | email with no daily limit | managed in the debug panel; can be added before the person signs in |
| `books` | book request | `id` is the ref. `status`: queued, running, done, failed, interrupted, refused. Also holds which provider and model drew it, the prompt version, the child's name and About Me details, and the total cost. |
| `uploads` | book | the photo the model saw (1024px, WebP), kept for debugging |
| `images` | generated image | the hero sheet (page 0) and each page: status (waiting, drawing, done, failed), the exact prompt, the attached character sheets, the image (WebP), tokens, cost, the provider's request ID, any error, and timings. Unique on (book, kind, page), so a resumed book can't duplicate an image. |
| `book_events` | step event | the trail: start, done, failed, info, refused, with a duration and fields. Never holds the password, the photo, or the child's name and details. |
| `request_errors` | failure outside a book | the ref, path, status, error type, message, traceback and browser |
| `admin_settings` | admin | the debug panel's provider, model, quality and size; these apply only to that admin's books |
| `reviews` | review response | three 1–5 ratings plus "what isn't good", by the book's owner only. `respondent_key` is the user's id (one review per person; answering again, on any of their books, replaces it). `source` is `site` or `connect`; `connect_id` is the crowd participant ID from the study link |
| `settings` | site-wide value | e.g. `featured_review_book_id` |

## Decisions
- **Images are stored in Postgres as WebP (quality 90)**, about 1.5 MB per book. PDFs aren't stored:
  they're rebuilt from the saved images on each download, which takes under a second.
- **Daily limit (phase 2):** 3 books per UTC day. `refused` books never count, and a failed book counts
  only if at least one image was drawn.
- **Restarts:** at startup, books still `queued` or `running` become `interrupted` and resume. Images
  already `done` are reused, not redrawn.
- **No deletion feature.** The upload page says plainly that the photo and book are kept.
