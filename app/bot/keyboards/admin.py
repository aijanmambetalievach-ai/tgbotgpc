"""Inline keyboards for administrators."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.bot import texts
from app.bot.callbacks import (
    AdminAppListCB,
    AdminClientCB,
    AdminCourseCB,
    AdminFaqCB,
    AdminLessonCB,
    AppCB,
    BroadcastCB,
    FlowCB,
    SettingsCB,
)
from app.bot.keyboards.common import button, pagination_row
from app.models.application import Application
from app.models.content import Course, FaqEntry, Lesson
from app.models.enums import (
    AUDIENCE_LABELS,
    DELIVERY_LABELS,
    ApplicationStatus,
    ContentStatus,
)
from app.models.user import User
from app.repositories.applications import ApplicationRow
from app.repositories.base import Page

BACK = "‹ Назад"


# =============================================================================
# Applications
# =============================================================================
def application_list(page: Page[ApplicationRow], scope: str) -> InlineKeyboardMarkup:
    tabs = [
        button(
            ("• " if key == scope else "") + label,
            AdminAppListCB(scope=key).pack(),
        )
        for key, label in texts.ADMIN_SCOPE_LABELS.items()
    ]
    rows: list[list[InlineKeyboardButton]] = [tabs[:2], tabs[2:]]
    rows += [
        [
            button(
                f"{row.application.number[-6:]} "
                + texts.application_row(row.application, row.client.full_name),
                AppCB(action="admin", id=row.application.id, page=page.page, scope=scope).pack(),
            )
        ]
        for row in page.items
    ]
    nav = pagination_row(
        lambda p: AdminAppListCB(scope=scope, page=p).pack(), page.page, page.pages
    )
    if nav:
        rows.append(nav)
    rows.append([button("📤 Выгрузить все заявки в Excel", AppCB(action="export").pack())])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def application_card(
    application: Application, has_files: bool, page: int, scope: str
) -> InlineKeyboardMarkup:
    app_id = application.id
    rows: list[list[InlineKeyboardButton]] = []
    if application.is_open:
        rows.append([button("✍️ Ответить клиенту", AppCB(action="reply", id=app_id).pack())])
        status_row = []
        if application.status is ApplicationStatus.NEW:
            status_row.append(button("🟡 Взять в работу", AppCB(action="take", id=app_id).pack()))
        status_row.append(button("✅ Завершить", AppCB(action="done", id=app_id).pack()))
        rows.append(status_row)
        rows.append([button("❌ Отклонить", AppCB(action="reject", id=app_id).pack())])
    if has_files:
        rows.append([button("📎 Показать файлы", AppCB(action="files", id=app_id).pack())])
    rows.append(
        [
            button("👤 Клиент", AdminClientCB(action="open", id=application.client_id).pack()),
            button("🔄 Обновить", AppCB(action="admin", id=app_id, page=page, scope=scope).pack()),
        ]
    )
    rows.append([button("‹ К списку", AdminAppListCB(scope=scope or "new", page=page).pack())])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def application_notification(application_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                button("✍️ Ответить", AppCB(action="reply", id=application_id).pack()),
                button("📂 Открыть", AppCB(action="admin", id=application_id).pack()),
            ]
        ]
    )


def confirm_status(application_id: int, action: str, label: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                button(label, AppCB(action=f"{action}_yes", id=application_id).pack()),
                button(BACK, AppCB(action="admin", id=application_id).pack()),
            ]
        ]
    )


# =============================================================================
# Courses
# =============================================================================
def course_list(page: Page[Course], archived: bool = False) -> InlineKeyboardMarkup:
    list_action = "archive" if archived else "list"
    rows = [
        [
            button(
                texts.admin_course_row(course),
                AdminCourseCB(action="open", id=course.id, page=page.page).pack(),
            )
        ]
        for course in page.items
    ]
    nav = pagination_row(
        lambda p: AdminCourseCB(action=list_action, page=p).pack(), page.page, page.pages
    )
    if nav:
        rows.append(nav)
    if archived:
        rows.append([button("‹ Курсы", AdminCourseCB(action="list").pack())])
    else:
        rows.append(
            [
                button("➕ Новый курс", AdminCourseCB(action="new").pack()),
                button("🗄 Архив", AdminCourseCB(action="archive").pack()),
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def course_card(course: Course, page: int) -> InlineKeyboardMarkup:
    cid = course.id

    def edit(label: str, field: str) -> InlineKeyboardButton:
        return button(label, AdminCourseCB(action="edit", id=cid, value=field).pack())

    rows = [
        [edit("✏️ Название", "title"), edit("✏️ Описание", "description")],
        [edit("✏️ Расписание", "schedule"), edit("✏️ Стоимость", "price")],
        [edit("✏️ Место/ссылка", "location")],
        [
            button("🎯 Аудитория", AdminCourseCB(action="audience", id=cid).pack()),
            button("📍 Формат", AdminCourseCB(action="delivery", id=cid).pack()),
        ],
    ]
    status_row: list[InlineKeyboardButton] = []
    if course.status is ContentStatus.PUBLISHED:
        status_row.append(
            button(
                "📝 Снять с публикации",
                AdminCourseCB(action="status", id=cid, value="DRAFT").pack(),
            )
        )
    else:
        status_row.append(
            button(
                "🟢 Опубликовать", AdminCourseCB(action="status", id=cid, value="PUBLISHED").pack()
            )
        )
    if course.status is ContentStatus.ARCHIVED:
        status_row = [
            button(
                "♻️ Вернуть в черновики",
                AdminCourseCB(action="status", id=cid, value="DRAFT").pack(),
            )
        ]
    else:
        status_row.append(
            button("🗄 В архив", AdminCourseCB(action="status", id=cid, value="ARCHIVED").pack())
        )
    rows.append(status_row)
    back_action = "archive" if course.status is ContentStatus.ARCHIVED else "list"
    rows.append([button("‹ Курсы", AdminCourseCB(action=back_action, page=page).pack())])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def course_options(course_id: int, kind: str) -> InlineKeyboardMarkup:
    labels = AUDIENCE_LABELS if kind == "audience" else DELIVERY_LABELS
    rows = [
        [button(label, AdminCourseCB(action=f"set_{kind}", id=course_id, value=value).pack())]
        for value, label in labels.items()
    ]
    rows.append([button(BACK, AdminCourseCB(action="open", id=course_id).pack())])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def audience_choices() -> InlineKeyboardMarkup:
    rows = [
        [button(label, FlowCB(action="audience", value=value).pack())]
        for value, label in AUDIENCE_LABELS.items()
    ]
    rows.append([button(texts.BTN_CANCEL, FlowCB(action="cancel").pack())])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def delivery_choices() -> InlineKeyboardMarkup:
    rows = [
        [button(label, FlowCB(action="delivery", value=value).pack())]
        for value, label in DELIVERY_LABELS.items()
    ]
    rows.append([button(texts.BTN_CANCEL, FlowCB(action="cancel").pack())])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# =============================================================================
# Lessons
# =============================================================================
def lesson_list(
    page: Page[Lesson], question_counts: dict[int, int], archived: bool = False
) -> InlineKeyboardMarkup:
    list_action = "archive" if archived else "list"
    rows = [
        [
            button(
                texts.admin_lesson_row(lesson, question_counts.get(lesson.id, 0)),
                AdminLessonCB(action="open", id=lesson.id, page=page.page).pack(),
            )
        ]
        for lesson in page.items
    ]
    nav = pagination_row(
        lambda p: AdminLessonCB(action=list_action, page=p).pack(), page.page, page.pages
    )
    if nav:
        rows.append(nav)
    if archived:
        rows.append([button("‹ Уроки", AdminLessonCB(action="list").pack())])
    else:
        rows.append(
            [
                button("➕ Новый урок", AdminLessonCB(action="new").pack()),
                button("🗄 Архив", AdminLessonCB(action="archive").pack()),
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def lesson_card(lesson: Lesson, page: int) -> InlineKeyboardMarkup:
    lid = lesson.id

    def act(label: str, action: str, value: str = "") -> InlineKeyboardButton:
        return button(label, AdminLessonCB(action=action, id=lid, value=value).pack())

    rows = [
        [act("✏️ Название", "edit", "title"), act("✏️ Текст", "edit", "body")],
        [act("🎬 Заменить файл", "edit", "media"), act("🔢 Порядок", "edit", "position")],
        [act("🎯 Аудитория", "audience"), act("📝 Тест", "quiz")],
        [act("👁 Предпросмотр", "preview")],
    ]
    if lesson.media_file_id:
        rows[1].insert(1, act("🚫 Убрать файл", "nomedia"))
    if lesson.status is ContentStatus.ARCHIVED:
        rows.append([act("♻️ Вернуть в черновики", "status", "DRAFT"), act("🗑 Удалить", "delete")])
    elif lesson.status is ContentStatus.PUBLISHED:
        rows.append(
            [
                act("📝 Снять с публикации", "status", "DRAFT"),
                act("🗄 В архив", "status", "ARCHIVED"),
            ]
        )
    else:
        rows.append(
            [act("🟢 Опубликовать", "status", "PUBLISHED"), act("🗄 В архив", "status", "ARCHIVED")]
        )
    back_action = "archive" if lesson.status is ContentStatus.ARCHIVED else "list"
    rows.append([button("‹ Уроки", AdminLessonCB(action=back_action, page=page).pack())])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def lesson_audience(lesson_id: int) -> InlineKeyboardMarkup:
    rows = [
        [button(label, AdminLessonCB(action="set_audience", id=lesson_id, value=value).pack())]
        for value, label in AUDIENCE_LABELS.items()
    ]
    rows.append([button(BACK, AdminLessonCB(action="open", id=lesson_id).pack())])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def lesson_quiz(lesson_id: int, has_questions: bool) -> InlineKeyboardMarkup:
    rows = [[button("➕ Добавить вопрос", AdminLessonCB(action="add_q", id=lesson_id).pack())]]
    if has_questions:
        rows.append(
            [button("🧹 Удалить все вопросы", AdminLessonCB(action="clear_q", id=lesson_id).pack())]
        )
    rows.append([button("‹ К уроку", AdminLessonCB(action="open", id=lesson_id).pack())])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def quiz_adding_done(lesson_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[button("✅ Готово", AdminLessonCB(action="quiz", id=lesson_id).pack())]]
    )


def confirm_lesson_action(lesson_id: int, action: str, label: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                button(label, AdminLessonCB(action=f"{action}_yes", id=lesson_id).pack()),
                button(BACK, AdminLessonCB(action="open", id=lesson_id).pack()),
            ]
        ]
    )


# =============================================================================
# FAQ
# =============================================================================
def faq_list(page: Page[FaqEntry]) -> InlineKeyboardMarkup:
    rows = [
        [
            button(
                texts.admin_faq_row(entry),
                AdminFaqCB(action="open", id=entry.id, page=page.page).pack(),
            )
        ]
        for entry in page.items
    ]
    nav = pagination_row(lambda p: AdminFaqCB(action="list", page=p).pack(), page.page, page.pages)
    if nav:
        rows.append(nav)
    rows.append([button("➕ Добавить вопрос", AdminFaqCB(action="new").pack())])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def faq_card(entry: FaqEntry, page: int) -> InlineKeyboardMarkup:
    eid = entry.id
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                button("✏️ Вопрос", AdminFaqCB(action="edit_q", id=eid).pack()),
                button("✏️ Ответ", AdminFaqCB(action="edit_a", id=eid).pack()),
            ],
            [
                button(
                    "🙈 Скрыть" if entry.is_published else "👁 Показывать",
                    AdminFaqCB(action="toggle", id=eid, page=page).pack(),
                ),
                button("🗑 Удалить", AdminFaqCB(action="delete", id=eid, page=page).pack()),
            ],
            [button("‹ Все вопросы", AdminFaqCB(action="list", page=page).pack())],
        ]
    )


def confirm_faq_delete(entry_id: int, page: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                button(
                    "🗑 Да, удалить", AdminFaqCB(action="delete_yes", id=entry_id, page=page).pack()
                ),
                button(BACK, AdminFaqCB(action="open", id=entry_id, page=page).pack()),
            ]
        ]
    )


# =============================================================================
# Clients
# =============================================================================
def client_list(page: Page[User], filter_key: str) -> InlineKeyboardMarkup:
    tabs = [
        button(
            ("• " if key == filter_key else "") + label,
            AdminClientCB(action="list", cat=str(key)).pack(),
        )
        for key, label in texts.CLIENT_FILTER_LABELS.items()
    ]
    rows: list[list[InlineKeyboardButton]] = [tabs[:2], tabs[2:]]
    rows += [
        [
            button(
                texts.admin_client_row(user),
                AdminClientCB(action="open", id=user.id, page=page.page, cat=filter_key).pack(),
            )
        ]
        for user in page.items
    ]
    nav = pagination_row(
        lambda p: AdminClientCB(action="list", page=p, cat=filter_key).pack(),
        page.page,
        page.pages,
    )
    if nav:
        rows.append(nav)
    rows.append([button("📤 Выгрузить клиентов в Excel", AdminClientCB(action="export").pack())])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def client_card(user: User, page: int, filter_key: str) -> InlineKeyboardMarkup:
    rows = [
        [button("📋 Заявки клиента", AdminClientCB(action="apps", id=user.id).pack())],
    ]
    if not user.is_admin:
        rows.append(
            [
                button(
                    "✅ Разблокировать" if not user.is_active else "🚫 Заблокировать",
                    AdminClientCB(
                        action="unblock" if not user.is_active else "block",
                        id=user.id,
                        page=page,
                        cat=filter_key,
                    ).pack(),
                )
            ]
        )
    rows.append(
        [button("‹ Клиенты", AdminClientCB(action="list", page=page, cat=filter_key).pack())]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def client_applications(page: Page[ApplicationRow], client_id: int) -> InlineKeyboardMarkup:
    rows = [
        [
            button(
                f"{row.application.number} · {texts.application_row(row.application)}",
                AppCB(action="admin", id=row.application.id).pack(),
            )
        ]
        for row in page.items
    ]
    nav = pagination_row(
        lambda p: AdminClientCB(action="apps", id=client_id, page=p).pack(), page.page, page.pages
    )
    if nav:
        rows.append(nav)
    rows.append([button("‹ К клиенту", AdminClientCB(action="open", id=client_id).pack())])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# =============================================================================
# Broadcast & settings
# =============================================================================
BROADCAST_AUDIENCES: dict[str, str] = {
    "ALL": "Всем клиентам",
    "PURCHASER": "🏛 Закупщикам",
    "SUPPLIER": "🏢 Поставщикам",
    "BEGINNER": "🌱 Новичкам",
}


def broadcast_audiences() -> InlineKeyboardMarkup:
    rows = [
        [button(label, BroadcastCB(action="audience", value=key).pack())]
        for key, label in BROADCAST_AUDIENCES.items()
    ]
    rows.append([button(texts.BTN_CANCEL, FlowCB(action="cancel").pack())])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def broadcast_confirm() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                button("✅ Отправить", BroadcastCB(action="send").pack()),
                button(texts.BTN_CANCEL, FlowCB(action="cancel").pack()),
            ]
        ]
    )


def settings_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [button("✏️ О нас", SettingsCB(action="edit", key="about").pack())],
            [button("✏️ Контакты", SettingsCB(action="edit", key="contacts").pack())],
            [button("👁 Меню клиента", SettingsCB(action="client_mode").pack())],
        ]
    )
