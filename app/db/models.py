"""Database tables. Design notes: docs/schema.md.

Every request gets a ref, and every ref has a row: book requests in `books` (even refused ones),
anything else that fails in `request_errors`. `book_events` is the step-by-step trail for a book.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import (JSON, BigInteger, DateTime, ForeignKey, Integer, LargeBinary, Numeric,
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
