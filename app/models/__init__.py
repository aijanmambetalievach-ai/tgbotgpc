"""ORM models.

Importing this package registers every table on ``Base.metadata`` — Alembic's
env.py relies on that for autogenerate.
"""

from app.models.application import Application, ApplicationMessage
from app.models.audit_log import AuditAction, AuditLog
from app.models.content import (
    BotText,
    BotTextKey,
    Course,
    FaqEntry,
    Lesson,
    LessonProgress,
    LessonQuestion,
)
from app.models.enums import (
    ApplicationStatus,
    ApplicationType,
    Audience,
    ClientCategory,
    ConsultationTopic,
    ContactMethod,
    ContentStatus,
    CourseDelivery,
    MediaType,
    UserRole,
)
from app.models.number_counter import NumberCounter, NumberScope
from app.models.user import User

__all__ = [
    "Application",
    "ApplicationMessage",
    "ApplicationStatus",
    "ApplicationType",
    "Audience",
    "AuditAction",
    "AuditLog",
    "BotText",
    "BotTextKey",
    "ClientCategory",
    "ConsultationTopic",
    "ContactMethod",
    "ContentStatus",
    "Course",
    "CourseDelivery",
    "FaqEntry",
    "Lesson",
    "LessonProgress",
    "LessonQuestion",
    "MediaType",
    "NumberCounter",
    "NumberScope",
    "User",
    "UserRole",
]
