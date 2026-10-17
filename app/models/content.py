"""Training content: live courses, in-bot lessons with quizzes, FAQ, editable texts."""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.database.base import Base, IntPKMixin, TimestampMixin
from app.models.enums import Audience, ContentStatus, CourseDelivery, MediaType

# JSONB on PostgreSQL, plain JSON elsewhere (keeps unit tests engine-agnostic).
JSONType = JSONB().with_variant(JSON(), "sqlite")

_AUDIENCE = SAEnum(Audience, native_enum=False, length=32, name="audience")
_STATUS = SAEnum(ContentStatus, native_enum=False, length=32, name="content_status")


class Course(IntPKMixin, TimestampMixin, Base):
    """A live training course (offline or Zoom) clients sign up for."""

    __tablename__ = "courses"

    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    audience: Mapped[Audience] = mapped_column(_AUDIENCE, nullable=False, default=Audience.ALL)
    delivery: Mapped[CourseDelivery] = mapped_column(
        SAEnum(CourseDelivery, native_enum=False, length=32, name="course_delivery"),
        nullable=False,
        default=CourseDelivery.ONLINE,
    )
    #: Free text such as "15–17 ноября, 10:00–13:00" — schedules are too varied
    #: to model as dates, and the admin types them the way clients read them.
    schedule: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    price: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    location: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[ContentStatus] = mapped_column(
        _STATUS, nullable=False, default=ContentStatus.DRAFT
    )
    created_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    __table_args__ = (Index("ix_courses_status_position", "status", "position"),)


class Lesson(IntPKMixin, TimestampMixin, Base):
    """A self-study lesson read directly in Telegram, optionally with a quiz."""

    __tablename__ = "lessons"

    title: Mapped[str] = mapped_column(String(300), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    audience: Mapped[Audience] = mapped_column(_AUDIENCE, nullable=False, default=Audience.ALL)
    media_type: Mapped[MediaType | None] = mapped_column(
        SAEnum(MediaType, native_enum=False, length=16, name="media_type"), nullable=True
    )
    #: Telegram ``file_id`` — the file itself stays on Telegram's servers.
    media_file_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[ContentStatus] = mapped_column(
        _STATUS, nullable=False, default=ContentStatus.DRAFT
    )
    created_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    __table_args__ = (Index("ix_lessons_status_position", "status", "position"),)


class LessonQuestion(IntPKMixin, Base):
    """One multiple-choice question of a lesson quiz."""

    __tablename__ = "lesson_questions"

    lesson_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("lessons.id", ondelete="CASCADE"), nullable=False
    )
    question: Mapped[str] = mapped_column(String(500), nullable=False)
    options: Mapped[list[str]] = mapped_column(JSONType, nullable=False, default=list)
    correct_option: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (Index("ix_lesson_questions_lesson_id", "lesson_id", "position"),)


class LessonProgress(IntPKMixin, Base):
    """A client finished a lesson (and possibly its quiz)."""

    __tablename__ = "lesson_progress"

    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    lesson_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("lessons.id", ondelete="CASCADE"), nullable=False
    )
    quiz_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    quiz_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completed_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("user_id", "lesson_id"),
        Index("ix_lesson_progress_lesson_id", "lesson_id"),
    )


class FaqEntry(IntPKMixin, TimestampMixin, Base):
    __tablename__ = "faq_entries"

    question: Mapped[str] = mapped_column(String(300), nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_published: Mapped[bool] = mapped_column(nullable=False, default=True)


class BotText(Base):
    """Admin-editable texts ("О нас", "Контакты") keyed by a fixed name."""

    __tablename__ = "bot_texts"

    key: Mapped[str] = mapped_column(String(32), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class BotTextKey:
    ABOUT = "about"
    CONTACTS = "contacts"


def quiz_options(raw: Any) -> list[str]:
    """Defensive read of the JSON column (always a list of strings)."""
    if not isinstance(raw, list):
        return []
    return [str(item) for item in raw]
