"""Database tables. Design notes: docs/schema.md.

Every request gets a ref, and every ref has a row: book requests in `books` (even refused ones),
anything else that fails in `request_errors`. `book_events` is the step-by-step trail for a book.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import (JSON, BigInteger, Boolean, DateTime, ForeignKey, Integer, LargeBinary, Numeric,
                        SmallInteger, String, Text, UniqueConstraint, Uuid)
from sqlalchemy.dialects.postgresql import BYTEA, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

Json = JSON().with_variant(JSONB(), "postgresql")
Bytes = LargeBinary().with_variant(BYTEA(), "postgresql")
Id = BigInteger().with_variant(Integer(), "sqlite")  # SQLite only autoincrements INTEGER keys


def now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    google_sub: Mapped[str] = mapped_column(String(64), unique=True)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    name: Mapped[str | None] = mapped_column(Text)
    picture_url: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UnlimitedEmail(Base):
    __tablename__ = "unlimited_emails"
    email: Mapped[str] = mapped_column(String(320), primary_key=True)
    added_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Book(Base):
    __tablename__ = "books"
    id: Mapped[str] = mapped_column(String(16), primary_key=True)  # the ref users see
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), index=True)
    # queued | running | done | failed | interrupted | refused
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)
    refused_reason: Mapped[str | None] = mapped_column(String(64))
    story_key: Mapped[str] = mapped_column(String(64))
    # Set when the book is made (and for older books by the story sync on startup).
    story_id: Mapped[int | None] = mapped_column(ForeignKey("stories.id", name="fk_books_story_id"), index=True)
    style_key: Mapped[str] = mapped_column(String(64))
    prompt_version: Mapped[str] = mapped_column(String(16))
    gender: Mapped[str] = mapped_column(String(8))
    child_name: Mapped[str] = mapped_column(Text, default="")
    details: Mapped[list] = mapped_column(Json, default=list)  # [[label, value], ...] in form order
    provider: Mapped[str] = mapped_column(String(32))
    model: Mapped[str | None] = mapped_column(String(64))
    quality: Mapped[str | None] = mapped_column(String(16))
    page_size: Mapped[str | None] = mapped_column(String(16))
    total_cost: Mapped[float] = mapped_column(Numeric(10, 4), default=0)
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    upload: Mapped["Upload | None"] = relationship(back_populates="book", uselist=False)
    images: Mapped[list["BookImage"]] = relationship(back_populates="book", order_by="BookImage.id")


class StoryRow(Base):
    """One story file (stories/<key>.yaml), mirrored here on every startup by app/book/bible.py sync_stories.
    The file is the master copy; a story whose file is gone stays, inactive, so old books still open."""
    __tablename__ = "stories"
    id: Mapped[int] = mapped_column(Id, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(64), unique=True)
    title: Mapped[str] = mapped_column(Text)
    file_hash: Mapped[str] = mapped_column(String(16))  # changes whenever the file does
    active: Mapped[bool] = mapped_column(Boolean, default=True)  # its file is in stories/ and fits the template
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class StoryCharacter(Base):
    """A story's character, as its story file describes them. `pin` is the file's `picture:` line, if any;
    `picture_id` is the picture books use right now."""
    __tablename__ = "characters"
    __table_args__ = (UniqueConstraint("story_id", "key"),)
    id: Mapped[int] = mapped_column(Id, primary_key=True, autoincrement=True)
    story_id: Mapped[int] = mapped_column(ForeignKey("stories.id"), index=True)
    key: Mapped[str] = mapped_column(String(64))  # wolf
    name: Mapped[str] = mapped_column(Text)       # the wolf
    description: Mapped[str] = mapped_column(Text)
    pin: Mapped[str | None] = mapped_column(String(160))  # wolf-2, or other_story/wolf-2
    picture_id: Mapped[int | None] = mapped_column(ForeignKey("character_pictures.id", use_alter=True,
                                                              name="fk_characters_picture_id"))


class CharacterPicture(Base):
    """Every version of a character's reference picture. Nothing is ever replaced: a changed description draws
    a new version, and a story file can pin any version by its name."""
    __tablename__ = "character_pictures"
    __table_args__ = (UniqueConstraint("character_id", "name"),)
    id: Mapped[int] = mapped_column(Id, primary_key=True, autoincrement=True)
    character_id: Mapped[int] = mapped_column(ForeignKey("characters.id"), index=True)
    name: Mapped[str] = mapped_column(String(80))  # "<character>-<version>", e.g. wolf-2
    image: Mapped[bytes] = mapped_column(Bytes)    # PNG, sent to the image model with each page
    prompt: Mapped[str] = mapped_column(Text)      # what it was drawn from
    source: Mapped[str] = mapped_column(String(16))  # drawn | imported (from assets/characters/)
    cost: Mapped[float | None] = mapped_column(Numeric(10, 4))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Upload(Base):
    """The uploaded photo, kept so a failed or odd book can be compared with what was sent."""
    __tablename__ = "uploads"
    book_id: Mapped[str] = mapped_column(ForeignKey("books.id"), primary_key=True)
    image: Mapped[bytes] = mapped_column(Bytes)
    mime: Mapped[str] = mapped_column(String(32))
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    face_box: Mapped[dict | None] = mapped_column(Json)
    face_description: Mapped[str | None] = mapped_column(Text)
    book: Mapped[Book] = relationship(back_populates="upload")


class BookImage(Base):
    """Every generated image: the hero sheet and each page. Drives the per-image progress bars."""
    __tablename__ = "images"
    __table_args__ = (UniqueConstraint("book_id", "kind", "page_number"),)
    id: Mapped[int] = mapped_column(Id, primary_key=True, autoincrement=True)
    book_id: Mapped[str] = mapped_column(ForeignKey("books.id"), index=True)
    kind: Mapped[str] = mapped_column(String(16))  # hero_sheet | page
    page_number: Mapped[int] = mapped_column(Integer, default=0)  # 0 for the hero sheet
    status: Mapped[str] = mapped_column(String(16), default="waiting")  # waiting | drawing | done | failed
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")  # tries so far (up to 3)
    prompt: Mapped[str | None] = mapped_column(Text)
    refs: Mapped[list | None] = mapped_column(Json)
    image: Mapped[bytes | None] = mapped_column(Bytes)  # WebP
    provider: Mapped[str | None] = mapped_column(String(32))
    model: Mapped[str | None] = mapped_column(String(64))
    quality: Mapped[str | None] = mapped_column(String(16))
    tokens: Mapped[dict | None] = mapped_column(Json)
    cost: Mapped[float] = mapped_column(Numeric(10, 4), default=0)
    provider_request_id: Mapped[str | None] = mapped_column(String(128))
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    book: Mapped[Book] = relationship(back_populates="images")


class BookEvent(Base):
    """The step trail: a `start` with no `done` is where a book got stuck."""
    __tablename__ = "book_events"
    id: Mapped[int] = mapped_column(Id, primary_key=True, autoincrement=True)
    book_id: Mapped[str] = mapped_column(ForeignKey("books.id"), index=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    level: Mapped[str] = mapped_column(String(8))
    step: Mapped[str] = mapped_column(String(64))
    event: Mapped[str] = mapped_column(String(16))  # start | done | failed | info | refused
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    fields: Mapped[dict | None] = mapped_column(Json)


class Activity(Base):
    """What people did, for the admin's Activity tab: sign-ins, money in and out, books asked for, finished
    and failed, reviews. Everything logged outside a book, plus a book's own milestones (not each picture)."""
    __tablename__ = "activity"
    id: Mapped[int] = mapped_column(Id, primary_key=True, autoincrement=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)
    book_id: Mapped[str | None] = mapped_column(String(16))
    level: Mapped[str] = mapped_column(String(8))
    step: Mapped[str] = mapped_column(String(64))
    event: Mapped[str] = mapped_column(String(32))
    fields: Mapped[dict | None] = mapped_column(Json)


class PageEvent(Base):
    """What visitors look at and click, for the admin's Funnel tab (see app/tracking.py). Anonymous: a random
    visitor ID kept in the browser, no cookies, no IP, never what anyone typed. Kept 90 days."""
    __tablename__ = "page_events"
    id: Mapped[int] = mapped_column(Id, primary_key=True, autoincrement=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    visitor: Mapped[str] = mapped_column(String(24), index=True)
    session: Mapped[str] = mapped_column(String(24))
    user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    name: Mapped[str] = mapped_column(String(32))
    path: Mapped[str] = mapped_column(String(128))
    props: Mapped[dict | None] = mapped_column(Json)


class RequestError(Base):
    """Failures outside a book (review form, sign-in, page script errors), each with a ref."""
    __tablename__ = "request_errors"
    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    path: Mapped[str] = mapped_column(String(256))
    status_code: Mapped[int | None] = mapped_column(Integer)
    error_type: Mapped[str | None] = mapped_column(String(128))
    message: Mapped[str | None] = mapped_column(Text)
    traceback: Mapped[str | None] = mapped_column(Text)
    browser: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)


class AdminSettings(Base):
    __tablename__ = "admin_settings"
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    provider: Mapped[str] = mapped_column(String(32), default="openai")
    model: Mapped[str | None] = mapped_column(String(64))
    quality: Mapped[str | None] = mapped_column(String(16))
    page_size: Mapped[str | None] = mapped_column(String(16))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class Review(Base):
    __tablename__ = "reviews"
    id: Mapped[int] = mapped_column(Id, primary_key=True, autoincrement=True)
    book_id: Mapped[str] = mapped_column(ForeignKey("books.id"), index=True)
    looks_like_me: Mapped[int] = mapped_column(SmallInteger)
    story_rings_true: Mapped[int] = mapped_column(SmallInteger)
    looks_professional: Mapped[int] = mapped_column(SmallInteger)
    not_good: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(16), default="site")  # site | connect
    respondent_key: Mapped[str | None] = mapped_column(String(64), index=True)
    connect_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict | None] = mapped_column(Json)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


# --- the wallet: money in cents, every change a row in `transactions` -------------------------------

class Payment(Base):
    """A Stripe Checkout session someone opened to add money. Credited once, when Stripe says it's paid."""
    __tablename__ = "payments"
    id: Mapped[str] = mapped_column(String(255), primary_key=True)  # Stripe's checkout session id
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    amount_cents: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="open")  # open | paid | expired
    payment_intent: Mapped[str | None] = mapped_column(String(255))
    refunded_cents: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Transaction(Base):
    """One credit (+) or debit (-). The balance is the sum; each row says what caused it."""
    __tablename__ = "transactions"
    id: Mapped[int] = mapped_column(Id, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    amount_cents: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(16))  # deposit | book | refund | book_refund
    book_id: Mapped[str | None] = mapped_column(ForeignKey("books.id"))
    payment_id: Mapped[str | None] = mapped_column(ForeignKey("payments.id"), unique=True)
    refund_request_id: Mapped[int | None] = mapped_column(ForeignKey("refund_requests.id"))
    stripe_refund_id: Mapped[str | None] = mapped_column(String(255))
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)


class RefundRequest(Base):
    """Someone says a book came out wrong. The admin decides; approved puts its price back in their wallet.
    (Unspent money goes back to the card straight away and needs no request.)"""
    __tablename__ = "refund_requests"
    id: Mapped[int] = mapped_column(Id, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    book_id: Mapped[str] = mapped_column(ForeignKey("books.id"), index=True)
    amount_cents: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)  # pending | approved | denied
    admin_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
