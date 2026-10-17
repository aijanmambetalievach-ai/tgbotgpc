"""Inline keyboards for clients."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.bot import texts
from app.bot.callbacks import (
    AppCB,
    CategoryCB,
    CourseCB,
    FaqCB,
    FlowCB,
    LessonCB,
    MenuCB,
    ProfileCB,
    QuizCB,
)
from app.bot.keyboards.common import button, pagination_row
from app.domain.text import truncate
from app.models.content import Course, FaqEntry
from app.models.enums import (
    CATEGORY_ICONS,
    CATEGORY_LABELS,
    CONTACT_METHOD_LABELS,
    TOPIC_LABELS,
    ClientCategory,
)
from app.repositories.applications import ApplicationRow
from app.repositories.base import Page
from app.services.catalog_service import LessonListing, LessonView


def categories(edit: bool = False) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                button(
                    f"{CATEGORY_ICONS[category]} {CATEGORY_LABELS[category]}",
                    CategoryCB(value=category, edit=int(edit)).pack(),
                )
            ]
            for category in ClientCategory
        ]
    )


def training_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [button("🗓 Живые курсы", CourseCB(action="list").pack())],
            [button("📖 Уроки в боте", LessonCB(action="list").pack())],
            [button("🎯 Индивидуальное обучение", MenuCB(to="individual").pack())],
        ]
    )


def _filter_toggle(show_all: bool, has_category: bool, build: str) -> list[InlineKeyboardButton]:
    if not has_category:
        return []
    if build == "course":
        data = CourseCB(action="list", all=int(not show_all)).pack()
    else:
        data = LessonCB(action="list", all=int(not show_all)).pack()
    return [button("🎯 Только для меня" if show_all else "🔎 Показать все", data)]


def course_list(page: Page[Course], show_all: bool, has_category: bool) -> InlineKeyboardMarkup:
    rows = [
        [
            button(
                texts.course_row(course),
                CourseCB(action="open", id=course.id, page=page.page, all=int(show_all)).pack(),
            )
        ]
        for course in page.items
    ]
    nav = pagination_row(
        lambda p: CourseCB(action="list", page=p, all=int(show_all)).pack(),
        page.page,
        page.pages,
    )
    if nav:
        rows.append(nav)
    toggle = _filter_toggle(show_all, has_category, "course")
    if toggle:
        rows.append(toggle)
    rows.append([button("‹ Обучение", MenuCB(to="training").pack())])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def course_card(course_id: int, page: int, show_all: bool) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [button("✍️ Записаться", CourseCB(action="enroll", id=course_id).pack())],
            [button("‹ Все курсы", CourseCB(action="list", page=page, all=int(show_all)).pack())],
        ]
    )


def lesson_list(listing: LessonListing, show_all: bool, has_category: bool) -> InlineKeyboardMarkup:
    page = listing.page
    rows = [
        [
            button(
                texts.lesson_row(
                    lesson,
                    lesson.id in listing.completed,
                    listing.question_counts.get(lesson.id, 0),
                ),
                LessonCB(action="open", id=lesson.id, all=int(show_all)).pack(),
            )
        ]
        for lesson in page.items
    ]
    nav = pagination_row(
        lambda p: LessonCB(action="list", page=p, all=int(show_all)).pack(),
        page.page,
        page.pages,
    )
    if nav:
        rows.append(nav)
    toggle = _filter_toggle(show_all, has_category, "lesson")
    if toggle:
        rows.append(toggle)
    rows.append([button("‹ Обучение", MenuCB(to="training").pack())])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def lesson_view(view: LessonView, show_all: bool) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    lesson_id = view.lesson.id
    if view.questions:
        label = (
            "🔁 Пройти тест еще раз" if view.progress else f"📝 Пройти тест ({len(view.questions)})"
        )
        rows.append(
            [button(label, LessonCB(action="quiz", id=lesson_id, all=int(show_all)).pack())]
        )
    elif view.progress is None:
        rows.append(
            [
                button(
                    "✅ Урок пройден",
                    LessonCB(action="done", id=lesson_id, all=int(show_all)).pack(),
                )
            ]
        )
    nav: list[InlineKeyboardButton] = []
    if view.prev_id:
        nav.append(
            button("‹ Назад", LessonCB(action="open", id=view.prev_id, all=int(show_all)).pack())
        )
    if view.next_id:
        nav.append(
            button("Далее ›", LessonCB(action="open", id=view.next_id, all=int(show_all)).pack())
        )
    if nav:
        rows.append(nav)
    rows.append([button("📖 Все уроки", LessonCB(action="list", all=int(show_all)).pack())])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def quiz_options(lesson_id: int, number: int, options_count: int) -> InlineKeyboardMarkup:
    """Numbered buttons — the option texts themselves are in the message."""
    buttons = [
        button(str(index + 1), QuizCB(lesson=lesson_id, number=number, option=index).pack())
        for index in range(options_count)
    ]
    rows = [buttons[i : i + 3] for i in range(0, len(buttons), 3)]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def after_lesson(lesson_id: int, next_id: int | None, show_all: bool) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if next_id:
        rows.append(
            [
                button(
                    "➡️ Следующий урок",
                    LessonCB(action="open", id=next_id, all=int(show_all)).pack(),
                )
            ]
        )
    rows.append([button("📖 Все уроки", LessonCB(action="list", all=int(show_all)).pack())])
    rows.append([button("💬 Задать вопрос специалисту", MenuCB(to="consult").pack())])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def support_cta() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[button("🤝 Оставить заявку", MenuCB(to="support").pack())]]
    )


def topics() -> InlineKeyboardMarkup:
    rows = [
        [button(label, FlowCB(action="topic", value=topic).pack())]
        for topic, label in TOPIC_LABELS.items()
    ]
    rows.append([button(texts.BTN_CANCEL, FlowCB(action="cancel").pack())])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def contact_methods() -> InlineKeyboardMarkup:
    rows = [
        [button(label, FlowCB(action="contact", value=method).pack())]
        for method, label in CONTACT_METHOD_LABELS.items()
    ]
    rows.append([button(texts.BTN_CANCEL, FlowCB(action="cancel").pack())])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def use_telegram_name(name: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [button(f"✅ {truncate(name, 30)}", FlowCB(action="tg_name").pack())],
            [button(texts.BTN_CANCEL, FlowCB(action="cancel").pack())],
        ]
    )


def confirm_application() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [button("✅ Отправить заявку", FlowCB(action="submit").pack())],
            [button(texts.BTN_CANCEL, FlowCB(action="cancel").pack())],
        ]
    )


def my_applications(page: Page[ApplicationRow]) -> InlineKeyboardMarkup:
    rows = [
        [
            button(
                f"{row.application.number} · {texts.application_row(row.application)}",
                AppCB(action="open", id=row.application.id, page=page.page).pack(),
            )
        ]
        for row in page.items
    ]
    nav = pagination_row(lambda p: AppCB(action="mine", page=p).pack(), page.page, page.pages)
    if nav:
        rows.append(nav)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def application_card(
    application_id: int, is_open: bool, has_files: bool, page: int
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if is_open:
        rows.append(
            [button("✍️ Написать специалисту", AppCB(action="write", id=application_id).pack())]
        )
    if has_files:
        rows.append([button("📎 Показать файлы", AppCB(action="files", id=application_id).pack())])
    if is_open:
        rows.append(
            [button("🚫 Отменить заявку", AppCB(action="cancel", id=application_id).pack())]
        )
    rows.append([button("‹ Мои заявки", AppCB(action="mine", page=page).pack())])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def confirm_cancel_application(application_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                button("Да, отменить", AppCB(action="cancel_yes", id=application_id).pack()),
                button("Нет", AppCB(action="open", id=application_id).pack()),
            ]
        ]
    )


def reply_to_staff(application_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                button("✍️ Ответить", AppCB(action="write", id=application_id).pack()),
                button("📋 Открыть заявку", AppCB(action="open", id=application_id).pack()),
            ]
        ]
    )


def faq_list(page: Page[FaqEntry]) -> InlineKeyboardMarkup:
    rows = [
        [
            button(
                truncate(entry.question, 60),
                FaqCB(action="open", id=entry.id, page=page.page).pack(),
            )
        ]
        for entry in page.items
    ]
    nav = pagination_row(lambda p: FaqCB(action="list", page=p).pack(), page.page, page.pages)
    if nav:
        rows.append(nav)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def faq_answer(page: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [button("💬 Не нашли ответ? Спросите специалиста", MenuCB(to="consult").pack())],
            [button("‹ Все вопросы", FaqCB(action="list", page=page).pack())],
        ]
    )


def about() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[button("💬 Задать вопрос", MenuCB(to="consult").pack())]]
    )


def profile() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                button("✏️ Имя", ProfileCB(action="name").pack()),
                button("✏️ Телефон", ProfileCB(action="phone").pack()),
            ],
            [
                button("✏️ Организация", ProfileCB(action="organization").pack()),
                button("✏️ Кто я", ProfileCB(action="category").pack()),
            ],
        ]
    )
