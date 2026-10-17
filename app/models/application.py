"""Client applications (course sign-up, individual training, consultation) and
the conversation attached to each of them."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, IntPKMixin, TimestampMixin
from app.models.enums import (
    OPEN_APPLICATION_STATUSES,
    ApplicationStatus,
    ApplicationType,
    ConsultationTopic,
    ContactMethod,
    MediaType,
)


class Application(IntPKMixin, TimestampMixin, Base):
    __tablename__ = "applications"

    number: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    type: Mapped[ApplicationType] = mapped_column(
        SAEnum(ApplicationType, native_enum=False, length=32, name="application_type"),
        nullable=False,
    )
    status: Mapped[ApplicationStatus] = mapped_column(
        SAEnum(ApplicationStatus, native_enum=False, length=32, name="application_status"),
        nullable=False,
        default=ApplicationStatus.NEW,
    )
    client_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    course_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("courses.id", ondelete="SET NULL"), nullable=True
    )
    #: Course title at the moment of sign-up — survives course edits/archiving.
    course_title: Mapped[str | None] = mapped_column(String(300), nullable=True)
    topic: Mapped[ConsultationTopic | None] = mapped_column(
        SAEnum(ConsultationTopic, native_enum=False, length=32, name="consultation_topic"),
        nullable=True,
    )
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    preferred_time: Mapped[str | None] = mapped_column(String(300), nullable=True)
    contact_method: Mapped[ContactMethod] = mapped_column(
        SAEnum(ContactMethod, native_enum=False, length=32, name="contact_method"),
        nullable=False,
        default=ContactMethod.TELEGRAM,
    )
    assignee_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    closed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_applications_status_created", "status", "created_at"),
        Index("ix_applications_client_id", "client_id", "created_at"),
        Index("ix_applications_course_id", "course_id"),
    )

    @property
    def is_open(self) -> bool:
        return self.status in OPEN_APPLICATION_STATUSES


class ApplicationMessage(IntPKMixin, Base):
    """One message in the client ↔ consultant thread of an application."""

    __tablename__ = "application_messages"

    application_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("applications.id", ondelete="CASCADE"), nullable=False
    )
    author_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    from_staff: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    media_type: Mapped[MediaType | None] = mapped_column(
        SAEnum(MediaType, native_enum=False, length=16, name="media_type"), nullable=True
    )
    media_file_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_application_messages_application_id", "application_id", "created_at"),
    )
