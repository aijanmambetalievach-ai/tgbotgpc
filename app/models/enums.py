"""Domain enumerations shared by models, services and the UI layer."""

from __future__ import annotations

from enum import StrEnum


class UserRole(StrEnum):
    """System roles.

    ``ADMIN`` runs the training centre (answers consultations, manages content);
    ``CLIENT`` is anyone who opened the bot.
    """

    ADMIN = "ADMIN"
    CLIENT = "CLIENT"


class ClientCategory(StrEnum):
    """Who the client is — drives which content is suggested to them."""

    PURCHASER = "PURCHASER"
    SUPPLIER = "SUPPLIER"
    BEGINNER = "BEGINNER"


class Audience(StrEnum):
    """Who a course or lesson is meant for."""

    ALL = "ALL"
    PURCHASER = "PURCHASER"
    SUPPLIER = "SUPPLIER"
    BEGINNER = "BEGINNER"


class ContentStatus(StrEnum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    ARCHIVED = "ARCHIVED"


class CourseDelivery(StrEnum):
    ONLINE = "ONLINE"
    OFFLINE = "OFFLINE"
    MIXED = "MIXED"


class MediaType(StrEnum):
    PHOTO = "PHOTO"
    VIDEO = "VIDEO"
    DOCUMENT = "DOCUMENT"


class ApplicationType(StrEnum):
    COURSE = "COURSE"
    INDIVIDUAL = "INDIVIDUAL"
    CONSULTATION = "CONSULTATION"


class ApplicationStatus(StrEnum):
    NEW = "NEW"
    IN_PROGRESS = "IN_PROGRESS"
    DONE = "DONE"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class ConsultationTopic(StrEnum):
    PORTAL = "PORTAL"
    PLANNING = "PLANNING"
    TENDER_DOCS = "TENDER_DOCS"
    SUPPLIER_BID = "SUPPLIER_BID"
    EVALUATION = "EVALUATION"
    CONTRACT = "CONTRACT"
    COMPLAINT = "COMPLAINT"
    OTHER = "OTHER"


class ContactMethod(StrEnum):
    TELEGRAM = "TELEGRAM"
    PHONE = "PHONE"
    MEETING = "MEETING"


ROLE_LABELS: dict[UserRole, str] = {
    UserRole.ADMIN: "Администратор",
    UserRole.CLIENT: "Клиент",
}

CATEGORY_LABELS: dict[ClientCategory, str] = {
    ClientCategory.PURCHASER: "Закупщик (госорган)",
    ClientCategory.SUPPLIER: "Поставщик",
    ClientCategory.BEGINNER: "Новичок",
}

CATEGORY_ICONS: dict[ClientCategory, str] = {
    ClientCategory.PURCHASER: "🏛",
    ClientCategory.SUPPLIER: "🏢",
    ClientCategory.BEGINNER: "🌱",
}

AUDIENCE_LABELS: dict[Audience, str] = {
    Audience.ALL: "Для всех",
    Audience.PURCHASER: "Для закупщиков",
    Audience.SUPPLIER: "Для поставщиков",
    Audience.BEGINNER: "Для новичков",
}

CONTENT_STATUS_LABELS: dict[ContentStatus, str] = {
    ContentStatus.DRAFT: "📝 Черновик",
    ContentStatus.PUBLISHED: "🟢 Опубликован",
    ContentStatus.ARCHIVED: "🗄 В архиве",
}

DELIVERY_LABELS: dict[CourseDelivery, str] = {
    CourseDelivery.ONLINE: "Онлайн (Zoom)",
    CourseDelivery.OFFLINE: "Офлайн",
    CourseDelivery.MIXED: "Онлайн и офлайн",
}

APPLICATION_TYPE_LABELS: dict[ApplicationType, str] = {
    ApplicationType.COURSE: "Запись на курс",
    ApplicationType.INDIVIDUAL: "Индивидуальное обучение",
    ApplicationType.CONSULTATION: "Консультация",
}

APPLICATION_TYPE_ICONS: dict[ApplicationType, str] = {
    ApplicationType.COURSE: "📚",
    ApplicationType.INDIVIDUAL: "🎯",
    ApplicationType.CONSULTATION: "💬",
}

APPLICATION_STATUS_LABELS: dict[ApplicationStatus, str] = {
    ApplicationStatus.NEW: "Новая",
    ApplicationStatus.IN_PROGRESS: "В работе",
    ApplicationStatus.DONE: "Завершена",
    ApplicationStatus.REJECTED: "Отклонена",
    ApplicationStatus.CANCELLED: "Отменена клиентом",
}

APPLICATION_STATUS_ICONS: dict[ApplicationStatus, str] = {
    ApplicationStatus.NEW: "🆕",
    ApplicationStatus.IN_PROGRESS: "🟡",
    ApplicationStatus.DONE: "✅",
    ApplicationStatus.REJECTED: "❌",
    ApplicationStatus.CANCELLED: "🚫",
}

TOPIC_LABELS: dict[ConsultationTopic, str] = {
    ConsultationTopic.PORTAL: "Работа на портале госзакупок",
    ConsultationTopic.PLANNING: "План закупок и смета",
    ConsultationTopic.TENDER_DOCS: "Объявление и техспецификация",
    ConsultationTopic.SUPPLIER_BID: "Подача заявки поставщиком",
    ConsultationTopic.EVALUATION: "Оценка предложений, комиссия",
    ConsultationTopic.CONTRACT: "Договор и его исполнение",
    ConsultationTopic.COMPLAINT: "Жалобы и споры",
    ConsultationTopic.OTHER: "Другой вопрос",
}

CONTACT_METHOD_LABELS: dict[ContactMethod, str] = {
    ContactMethod.TELEGRAM: "💬 Ответить в Telegram",
    ContactMethod.PHONE: "📞 Позвонить мне",
    ContactMethod.MEETING: "🤝 Личная встреча / Zoom",
}

#: Statuses in which the conversation is still open.
OPEN_APPLICATION_STATUSES: frozenset[ApplicationStatus] = frozenset(
    {ApplicationStatus.NEW, ApplicationStatus.IN_PROGRESS}
)

#: The audiences a client of a given category sees.
CATEGORY_AUDIENCES: dict[ClientCategory | None, tuple[Audience, ...]] = {
    None: tuple(Audience),
    ClientCategory.PURCHASER: (Audience.ALL, Audience.PURCHASER),
    ClientCategory.SUPPLIER: (Audience.ALL, Audience.SUPPLIER),
    # Beginners are still exploring, so they are shown everything.
    ClientCategory.BEGINNER: tuple(Audience),
}
