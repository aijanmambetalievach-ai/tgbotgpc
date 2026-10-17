"""Admin: courses, lessons with quizzes and the FAQ."""

from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.bot.callbacks import AdminCourseCB, AdminFaqCB, AdminLessonCB, FlowCB
from app.bot.filters import IsAdmin
from app.bot.handlers.client import send_lesson
from app.bot.handlers.helpers import (
    answer_html,
    chat_id_of,
    edit_or_send,
    extract_attachment,
    rich_text,
    send_html,
)
from app.bot.keyboards import admin as kb
from app.bot.keyboards.common import flow_cancel, flow_skip_cancel
from app.bot.states import CourseEditor, FaqEditor, LessonEditor
from app.domain.exceptions import ValidationError
from app.models.enums import Audience, ContentStatus, CourseDelivery
from app.models.user import User
from app.services.catalog_service import CatalogService, CourseInput, LessonInput

logger = logging.getLogger(__name__)

router = Router(name="admin_content")
router.message.filter(IsAdmin)
router.callback_query.filter(IsAdmin)


# =============================================================================
# Courses
# =============================================================================
@router.message(F.text == texts.BTN_ADMIN_COURSES)
async def menu_courses(
    message: Message, session: AsyncSession, user: User, state: FSMContext
) -> None:
    await state.clear()
    page = await CatalogService(session).list_courses(user)
    await answer_html(
        message, texts.admin_courses_header(page.total), reply_markup=kb.course_list(page)
    )


@router.callback_query(AdminCourseCB.filter(F.action.in_({"list", "archive"})))
async def course_list(
    callback: CallbackQuery,
    callback_data: AdminCourseCB,
    session: AsyncSession,
    user: User,
    state: FSMContext,
) -> None:
    await state.clear()
    catalog = CatalogService(session)
    archived = callback_data.action == "archive"
    page = (
        await catalog.list_archived_courses(user, callback_data.page)
        if archived
        else await catalog.list_courses(user, callback_data.page)
    )
    await callback.answer()
    await edit_or_send(
        callback,
        texts.admin_courses_header(page.total, archived),
        reply_markup=kb.course_list(page, archived),
    )


@router.callback_query(AdminCourseCB.filter(F.action == "open"))
async def course_open(
    callback: CallbackQuery,
    callback_data: AdminCourseCB,
    session: AsyncSession,
    user: User,
    bot: Bot,
    state: FSMContext,
) -> None:
    await state.clear()
    await callback.answer()
    await _render_course(callback, session, user, bot, callback_data.id, callback_data.page)


async def _render_course(
    target: CallbackQuery | Message,
    session: AsyncSession,
    user: User,
    bot: Bot,
    course_id: int,
    page: int = 1,
) -> None:
    card = await CatalogService(session).get_course(user, course_id)
    me = await bot.me()
    link = f"https://t.me/{me.username}?start=course_{course_id}" if me.username else None
    text = texts.admin_course_card(card.course, card.enrollments, link)
    markup = kb.course_card(card.course, page)
    if isinstance(target, CallbackQuery):
        await edit_or_send(target, text, reply_markup=markup)
    else:
        await answer_html(target, text, reply_markup=markup)


@router.callback_query(AdminCourseCB.filter(F.action == "new"))
async def course_new(callback: CallbackQuery, bot: Bot, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(CourseEditor.title)
    await callback.answer()
    await send_html(bot, chat_id_of(callback), texts.COURSE_ASK_TITLE, reply_markup=flow_cancel())


@router.message(CourseEditor.title, F.text)
async def course_title(message: Message, state: FSMContext) -> None:
    await state.update_data(title=message.text or "")
    await state.set_state(CourseEditor.description)
    await answer_html(message, texts.COURSE_ASK_DESCRIPTION, reply_markup=flow_skip_cancel())


@router.message(CourseEditor.description, F.text)
async def course_description(message: Message, state: FSMContext) -> None:
    await state.update_data(description=rich_text(message))
    await _course_ask_audience(message, state)


@router.callback_query(FlowCB.filter(F.action == "skip"), CourseEditor.description)
async def course_description_skip(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.update_data(description="")
    if isinstance(callback.message, Message):
        await _course_ask_audience(callback.message, state)


async def _course_ask_audience(message: Message, state: FSMContext) -> None:
    await state.set_state(CourseEditor.audience)
    await answer_html(message, texts.COURSE_ASK_AUDIENCE, reply_markup=kb.audience_choices())


@router.callback_query(FlowCB.filter(F.action == "audience"), CourseEditor.audience)
async def course_audience(
    callback: CallbackQuery, callback_data: FlowCB, state: FSMContext
) -> None:
    await state.update_data(audience=Audience(callback_data.value))
    await state.set_state(CourseEditor.delivery)
    await callback.answer()
    await edit_or_send(callback, texts.COURSE_ASK_DELIVERY, reply_markup=kb.delivery_choices())


@router.callback_query(FlowCB.filter(F.action == "delivery"), CourseEditor.delivery)
async def course_delivery(
    callback: CallbackQuery, callback_data: FlowCB, state: FSMContext
) -> None:
    await state.update_data(delivery=CourseDelivery(callback_data.value))
    await state.set_state(CourseEditor.schedule)
    await callback.answer()
    await edit_or_send(callback, texts.COURSE_ASK_SCHEDULE, reply_markup=flow_skip_cancel())


#: Free-text optional steps: state -> (data key, next state, next prompt).
_COURSE_OPTIONAL_STEPS = {
    CourseEditor.schedule.state: ("schedule", CourseEditor.price, texts.COURSE_ASK_PRICE),
    CourseEditor.price.state: ("price", CourseEditor.location, texts.COURSE_ASK_LOCATION),
    CourseEditor.location.state: ("location", None, ""),
}


@router.message(CourseEditor.schedule, F.text)
@router.message(CourseEditor.price, F.text)
@router.message(CourseEditor.location, F.text)
async def course_optional_text(
    message: Message, session: AsyncSession, user: User, bot: Bot, state: FSMContext
) -> None:
    await _course_optional_step(message, session, user, bot, state, message.text or "")


@router.callback_query(FlowCB.filter(F.action == "skip"), CourseEditor.schedule)
@router.callback_query(FlowCB.filter(F.action == "skip"), CourseEditor.price)
@router.callback_query(FlowCB.filter(F.action == "skip"), CourseEditor.location)
async def course_optional_skip(
    callback: CallbackQuery, session: AsyncSession, user: User, bot: Bot, state: FSMContext
) -> None:
    await callback.answer()
    if isinstance(callback.message, Message):
        await _course_optional_step(callback.message, session, user, bot, state, "")


async def _course_optional_step(
    message: Message,
    session: AsyncSession,
    user: User,
    bot: Bot,
    state: FSMContext,
    value: str,
) -> None:
    current = await state.get_state()
    if current not in _COURSE_OPTIONAL_STEPS:
        return
    key, next_state, prompt = _COURSE_OPTIONAL_STEPS[current]
    await state.update_data({key: value})
    if next_state is not None:
        await state.set_state(next_state)
        await answer_html(message, prompt, reply_markup=flow_skip_cancel())
        return

    data = await state.get_data()
    course = await CatalogService(session).create_course(
        user,
        CourseInput(
            title=str(data.get("title", "")),
            description=str(data.get("description", "")),
            audience=Audience(data.get("audience", Audience.ALL)),
            delivery=CourseDelivery(data.get("delivery", CourseDelivery.ONLINE)),
            schedule=str(data.get("schedule", "")),
            price=str(data.get("price", "")),
            location=str(data.get("location", "")),
        ),
    )
    await state.clear()
    await answer_html(message, texts.COURSE_CREATED)
    await _render_course(message, session, user, bot, course.id)


@router.callback_query(AdminCourseCB.filter(F.action == "edit"))
async def course_edit_start(
    callback: CallbackQuery, callback_data: AdminCourseCB, bot: Bot, state: FSMContext
) -> None:
    prompt = texts.COURSE_FIELD_PROMPTS.get(callback_data.value)
    if prompt is None:
        await callback.answer(texts.STALE_CALLBACK, show_alert=True)
        return
    await state.set_state(CourseEditor.edit_field)
    await state.update_data(course_id=callback_data.id, field=callback_data.value)
    await callback.answer()
    await send_html(bot, chat_id_of(callback), prompt, reply_markup=flow_cancel())


@router.message(CourseEditor.edit_field, F.text)
async def course_edit_save(
    message: Message, session: AsyncSession, user: User, bot: Bot, state: FSMContext
) -> None:
    data = await state.get_data()
    field = str(data["field"])
    value = rich_text(message) if field == "description" else (message.text or "")
    course = await CatalogService(session).update_course_text(
        user, int(data["course_id"]), field, value
    )
    await state.clear()
    await answer_html(message, "✅ Сохранено.")
    await _render_course(message, session, user, bot, course.id)


@router.callback_query(AdminCourseCB.filter(F.action.in_({"audience", "delivery"})))
async def course_options(callback: CallbackQuery, callback_data: AdminCourseCB) -> None:
    await callback.answer()
    prompt = "Для кого курс?" if callback_data.action == "audience" else "Формат занятий:"
    await edit_or_send(
        callback,
        prompt,
        reply_markup=kb.course_options(callback_data.id, callback_data.action),
    )


@router.callback_query(AdminCourseCB.filter(F.action.in_({"set_audience", "set_delivery"})))
async def course_options_save(
    callback: CallbackQuery,
    callback_data: AdminCourseCB,
    session: AsyncSession,
    user: User,
    bot: Bot,
) -> None:
    catalog = CatalogService(session)
    if callback_data.action == "set_audience":
        await catalog.update_course_options(
            user, callback_data.id, audience=Audience(callback_data.value)
        )
    else:
        await catalog.update_course_options(
            user, callback_data.id, delivery=CourseDelivery(callback_data.value)
        )
    await callback.answer("Сохранено")
    await _render_course(callback, session, user, bot, callback_data.id)


@router.callback_query(AdminCourseCB.filter(F.action == "status"))
async def course_status(
    callback: CallbackQuery,
    callback_data: AdminCourseCB,
    session: AsyncSession,
    user: User,
    bot: Bot,
) -> None:
    status = ContentStatus(callback_data.value)
    await CatalogService(session).set_course_status(user, callback_data.id, status)
    await callback.answer(texts.CONTENT_STATUS_ANSWERS[status])
    await _render_course(callback, session, user, bot, callback_data.id)


# =============================================================================
# Lessons
# =============================================================================
@router.message(F.text == texts.BTN_ADMIN_LESSONS)
async def menu_lessons(
    message: Message, session: AsyncSession, user: User, state: FSMContext
) -> None:
    await state.clear()
    listing = await CatalogService(session).list_lessons(user)
    await answer_html(
        message,
        texts.admin_lessons_header(listing.page.total),
        reply_markup=kb.lesson_list(listing.page, listing.question_counts),
    )


@router.callback_query(AdminLessonCB.filter(F.action.in_({"list", "archive"})))
async def lesson_list(
    callback: CallbackQuery,
    callback_data: AdminLessonCB,
    session: AsyncSession,
    user: User,
    state: FSMContext,
) -> None:
    await state.clear()
    catalog = CatalogService(session)
    await callback.answer()
    if callback_data.action == "archive":
        page = await catalog.list_archived_lessons(user, callback_data.page)
        counts = await catalog.question_counts([lesson.id for lesson in page.items])
        await edit_or_send(
            callback,
            texts.admin_lessons_header(page.total, archived=True),
            reply_markup=kb.lesson_list(page, counts, archived=True),
        )
        return
    listing = await catalog.list_lessons(user, callback_data.page)
    await edit_or_send(
        callback,
        texts.admin_lessons_header(listing.page.total),
        reply_markup=kb.lesson_list(listing.page, listing.question_counts),
    )


async def _render_lesson(
    target: CallbackQuery | Message,
    session: AsyncSession,
    user: User,
    lesson_id: int,
    page: int = 1,
) -> None:
    view = await CatalogService(session).view_lesson(user, lesson_id)
    text = texts.admin_lesson_card(view.lesson, view.questions)
    markup = kb.lesson_card(view.lesson, page)
    if isinstance(target, CallbackQuery):
        await edit_or_send(target, text, reply_markup=markup)
    else:
        await answer_html(target, text, reply_markup=markup)


@router.callback_query(AdminLessonCB.filter(F.action == "open"))
async def lesson_open(
    callback: CallbackQuery,
    callback_data: AdminLessonCB,
    session: AsyncSession,
    user: User,
    state: FSMContext,
) -> None:
    await state.clear()
    await callback.answer()
    await _render_lesson(callback, session, user, callback_data.id, callback_data.page)


@router.callback_query(AdminLessonCB.filter(F.action == "preview"))
async def lesson_preview(
    callback: CallbackQuery,
    callback_data: AdminLessonCB,
    session: AsyncSession,
    user: User,
    bot: Bot,
) -> None:
    view = await CatalogService(session).view_lesson(user, callback_data.id)
    await callback.answer()
    await send_lesson(bot, chat_id_of(callback), view, show_all=True)


@router.callback_query(AdminLessonCB.filter(F.action == "new"))
async def lesson_new(callback: CallbackQuery, bot: Bot, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(LessonEditor.title)
    await callback.answer()
    await send_html(bot, chat_id_of(callback), texts.LESSON_ASK_TITLE, reply_markup=flow_cancel())


@router.message(LessonEditor.title, F.text)
async def lesson_title(message: Message, state: FSMContext) -> None:
    await state.update_data(title=message.text or "")
    await state.set_state(LessonEditor.content)
    await answer_html(message, texts.LESSON_ASK_CONTENT, reply_markup=flow_cancel())


@router.message(LessonEditor.content, F.text | F.photo | F.video | F.document)
async def lesson_content(message: Message, state: FSMContext) -> None:
    attachment = extract_attachment(message)
    await state.update_data(
        body=rich_text(message),
        media_type=attachment.media_type if attachment else None,
        media_file_id=attachment.file_id if attachment else None,
    )
    if attachment is not None and not (message.caption or "").strip():
        await state.set_state(LessonEditor.text_after_media)
        await answer_html(
            message, texts.LESSON_ASK_TEXT_AFTER_MEDIA, reply_markup=flow_skip_cancel()
        )
        return
    await _lesson_ask_audience(message, state)


@router.message(LessonEditor.text_after_media, F.text)
async def lesson_text_after_media(message: Message, state: FSMContext) -> None:
    await state.update_data(body=rich_text(message))
    await _lesson_ask_audience(message, state)


@router.callback_query(FlowCB.filter(F.action == "skip"), LessonEditor.text_after_media)
async def lesson_text_skip(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if isinstance(callback.message, Message):
        await _lesson_ask_audience(callback.message, state)


async def _lesson_ask_audience(message: Message, state: FSMContext) -> None:
    await state.set_state(LessonEditor.audience)
    await answer_html(message, texts.LESSON_ASK_AUDIENCE, reply_markup=kb.audience_choices())


@router.callback_query(FlowCB.filter(F.action == "audience"), LessonEditor.audience)
async def lesson_create(
    callback: CallbackQuery,
    callback_data: FlowCB,
    session: AsyncSession,
    user: User,
    state: FSMContext,
) -> None:
    data = await state.get_data()
    lesson = await CatalogService(session).create_lesson(
        user,
        LessonInput(
            title=str(data.get("title", "")),
            body=str(data.get("body") or ""),
            audience=Audience(callback_data.value),
            media_type=data.get("media_type"),
            media_file_id=data.get("media_file_id"),
        ),
    )
    await state.clear()
    await callback.answer("Урок создан")
    await edit_or_send(callback, texts.LESSON_CREATED)
    if isinstance(callback.message, Message):
        await _render_lesson(callback.message, session, user, lesson.id)


_LESSON_EDIT_PROMPTS = {
    "title": (LessonEditor.edit_title, texts.LESSON_ASK_NEW_TITLE),
    "body": (LessonEditor.edit_body, texts.LESSON_ASK_NEW_BODY),
    "media": (LessonEditor.edit_media, texts.LESSON_ASK_NEW_MEDIA),
    "position": (LessonEditor.edit_position, texts.LESSON_ASK_POSITION),
}


@router.callback_query(AdminLessonCB.filter(F.action == "edit"))
async def lesson_edit_start(
    callback: CallbackQuery, callback_data: AdminLessonCB, bot: Bot, state: FSMContext
) -> None:
    if callback_data.value not in _LESSON_EDIT_PROMPTS:
        await callback.answer(texts.STALE_CALLBACK, show_alert=True)
        return
    target_state, prompt = _LESSON_EDIT_PROMPTS[callback_data.value]
    await state.set_state(target_state)
    await state.update_data(lesson_id=callback_data.id)
    await callback.answer()
    await send_html(bot, chat_id_of(callback), prompt, reply_markup=flow_cancel())


@router.message(LessonEditor.edit_title, F.text)
async def lesson_edit_title(
    message: Message, session: AsyncSession, user: User, state: FSMContext
) -> None:
    lesson_id = int((await state.get_data())["lesson_id"])
    await CatalogService(session).update_lesson(user, lesson_id, title=message.text or "")
    await _lesson_saved(message, session, user, state, lesson_id)


@router.message(LessonEditor.edit_body, F.text)
async def lesson_edit_body(
    message: Message, session: AsyncSession, user: User, state: FSMContext
) -> None:
    lesson_id = int((await state.get_data())["lesson_id"])
    await CatalogService(session).update_lesson(user, lesson_id, body=rich_text(message))
    await _lesson_saved(message, session, user, state, lesson_id)


@router.message(LessonEditor.edit_media, F.photo | F.video | F.document)
async def lesson_edit_media(
    message: Message, session: AsyncSession, user: User, state: FSMContext
) -> None:
    attachment = extract_attachment(message)
    if attachment is None:  # pragma: no cover - guarded by the filter
        return
    lesson_id = int((await state.get_data())["lesson_id"])
    await CatalogService(session).update_lesson(
        user, lesson_id, media=(attachment.media_type, attachment.file_id)
    )
    await _lesson_saved(message, session, user, state, lesson_id)


@router.message(LessonEditor.edit_position, F.text)
async def lesson_edit_position(
    message: Message, session: AsyncSession, user: User, state: FSMContext
) -> None:
    raw = (message.text or "").strip()
    if not raw.isdigit():
        raise ValidationError("Нужно целое число, например 5.")
    lesson_id = int((await state.get_data())["lesson_id"])
    await CatalogService(session).update_lesson(user, lesson_id, position=int(raw))
    await _lesson_saved(message, session, user, state, lesson_id)


async def _lesson_saved(
    message: Message, session: AsyncSession, user: User, state: FSMContext, lesson_id: int
) -> None:
    await state.clear()
    await answer_html(message, "✅ Сохранено.")
    await _render_lesson(message, session, user, lesson_id)


@router.callback_query(AdminLessonCB.filter(F.action == "nomedia"))
async def lesson_remove_media(
    callback: CallbackQuery, callback_data: AdminLessonCB, session: AsyncSession, user: User
) -> None:
    await CatalogService(session).update_lesson(user, callback_data.id, remove_media=True)
    await callback.answer("Файл убран")
    await _render_lesson(callback, session, user, callback_data.id)


@router.callback_query(AdminLessonCB.filter(F.action == "audience"))
async def lesson_audience(callback: CallbackQuery, callback_data: AdminLessonCB) -> None:
    await callback.answer()
    await edit_or_send(
        callback, "Для кого урок?", reply_markup=kb.lesson_audience(callback_data.id)
    )


@router.callback_query(AdminLessonCB.filter(F.action == "set_audience"))
async def lesson_audience_save(
    callback: CallbackQuery, callback_data: AdminLessonCB, session: AsyncSession, user: User
) -> None:
    await CatalogService(session).update_lesson(
        user, callback_data.id, audience=Audience(callback_data.value)
    )
    await callback.answer("Сохранено")
    await _render_lesson(callback, session, user, callback_data.id)


@router.callback_query(AdminLessonCB.filter(F.action == "status"))
async def lesson_status(
    callback: CallbackQuery, callback_data: AdminLessonCB, session: AsyncSession, user: User
) -> None:
    status = ContentStatus(callback_data.value)
    await CatalogService(session).set_lesson_status(user, callback_data.id, status)
    await callback.answer(texts.CONTENT_STATUS_ANSWERS[status])
    await _render_lesson(callback, session, user, callback_data.id)


@router.callback_query(AdminLessonCB.filter(F.action == "delete"))
async def lesson_delete_ask(callback: CallbackQuery, callback_data: AdminLessonCB) -> None:
    await callback.answer()
    await edit_or_send(
        callback,
        texts.CONFIRM_DELETE_LESSON,
        reply_markup=kb.confirm_lesson_action(callback_data.id, "delete", "🗑 Удалить"),
    )


@router.callback_query(AdminLessonCB.filter(F.action == "delete_yes"))
async def lesson_delete(
    callback: CallbackQuery, callback_data: AdminLessonCB, session: AsyncSession, user: User
) -> None:
    await CatalogService(session).delete_lesson(user, callback_data.id)
    await callback.answer(texts.LESSON_DELETED)
    page = await CatalogService(session).list_archived_lessons(user)
    counts = await CatalogService(session).question_counts([lesson.id for lesson in page.items])
    await edit_or_send(
        callback,
        f"{texts.LESSON_DELETED}\n\n{texts.admin_lessons_header(page.total, archived=True)}",
        reply_markup=kb.lesson_list(page, counts, archived=True),
    )


# --- quiz ----------------------------------------------------------------------
async def _render_quiz(
    target: CallbackQuery | Message, session: AsyncSession, user: User, lesson_id: int
) -> None:
    view = await CatalogService(session).view_lesson(user, lesson_id)
    text = texts.admin_quiz(view.lesson, view.questions)
    markup = kb.lesson_quiz(lesson_id, bool(view.questions))
    if isinstance(target, CallbackQuery):
        await edit_or_send(target, text, reply_markup=markup)
    else:
        await answer_html(target, text, reply_markup=markup)


@router.callback_query(AdminLessonCB.filter(F.action == "quiz"))
async def quiz_open(
    callback: CallbackQuery,
    callback_data: AdminLessonCB,
    session: AsyncSession,
    user: User,
    state: FSMContext,
) -> None:
    await state.clear()
    await callback.answer()
    await _render_quiz(callback, session, user, callback_data.id)


@router.callback_query(AdminLessonCB.filter(F.action == "add_q"))
async def quiz_add_start(
    callback: CallbackQuery, callback_data: AdminLessonCB, bot: Bot, state: FSMContext
) -> None:
    await state.set_state(LessonEditor.add_question)
    await state.update_data(lesson_id=callback_data.id)
    await callback.answer()
    await send_html(
        bot,
        chat_id_of(callback),
        texts.QUIZ_ASK_QUESTION,
        reply_markup=kb.quiz_adding_done(callback_data.id),
    )


@router.message(LessonEditor.add_question, F.text)
async def quiz_add(message: Message, session: AsyncSession, user: User, state: FSMContext) -> None:
    lesson_id = int((await state.get_data())["lesson_id"])
    catalog = CatalogService(session)
    await catalog.add_question(user, lesson_id, message.text or "")
    total = (await catalog.question_counts([lesson_id])).get(lesson_id, 0)
    await answer_html(
        message, texts.question_added(total), reply_markup=kb.quiz_adding_done(lesson_id)
    )


@router.callback_query(AdminLessonCB.filter(F.action == "clear_q"))
async def quiz_clear_ask(callback: CallbackQuery, callback_data: AdminLessonCB) -> None:
    await callback.answer()
    await edit_or_send(
        callback,
        "Удалить все вопросы теста?",
        reply_markup=kb.confirm_lesson_action(callback_data.id, "clear_q", "🧹 Удалить"),
    )


@router.callback_query(AdminLessonCB.filter(F.action == "clear_q_yes"))
async def quiz_clear(
    callback: CallbackQuery, callback_data: AdminLessonCB, session: AsyncSession, user: User
) -> None:
    await CatalogService(session).clear_quiz(user, callback_data.id)
    await callback.answer("Тест очищен")
    await _render_quiz(callback, session, user, callback_data.id)


# =============================================================================
# FAQ
# =============================================================================
@router.message(F.text == texts.BTN_ADMIN_FAQ)
async def menu_faq(message: Message, session: AsyncSession, user: User, state: FSMContext) -> None:
    await state.clear()
    page = await CatalogService(session).list_faq(user)
    await answer_html(message, texts.admin_faq_header(page.total), reply_markup=kb.faq_list(page))


@router.callback_query(AdminFaqCB.filter(F.action == "list"))
async def faq_list(
    callback: CallbackQuery,
    callback_data: AdminFaqCB,
    session: AsyncSession,
    user: User,
    state: FSMContext,
) -> None:
    await state.clear()
    page = await CatalogService(session).list_faq(user, callback_data.page)
    await callback.answer()
    await edit_or_send(callback, texts.admin_faq_header(page.total), reply_markup=kb.faq_list(page))


@router.callback_query(AdminFaqCB.filter(F.action == "open"))
async def faq_open(
    callback: CallbackQuery,
    callback_data: AdminFaqCB,
    session: AsyncSession,
    user: User,
    state: FSMContext,
) -> None:
    await state.clear()
    entry = await CatalogService(session).get_faq(user, callback_data.id)
    await callback.answer()
    await edit_or_send(
        callback, texts.admin_faq_card(entry), reply_markup=kb.faq_card(entry, callback_data.page)
    )


@router.callback_query(AdminFaqCB.filter(F.action == "new"))
async def faq_new(callback: CallbackQuery, bot: Bot, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(FaqEditor.question)
    await callback.answer()
    await send_html(bot, chat_id_of(callback), texts.FAQ_ASK_QUESTION, reply_markup=flow_cancel())


@router.message(FaqEditor.question, F.text)
async def faq_question(message: Message, state: FSMContext) -> None:
    await state.update_data(question=message.text or "")
    await state.set_state(FaqEditor.answer)
    await answer_html(message, texts.FAQ_ASK_ANSWER, reply_markup=flow_cancel())


@router.message(FaqEditor.answer, F.text)
async def faq_answer(
    message: Message, session: AsyncSession, user: User, state: FSMContext
) -> None:
    data = await state.get_data()
    entry = await CatalogService(session).save_faq(
        user, question=str(data.get("question", "")), answer=rich_text(message)
    )
    await state.clear()
    await answer_html(message, texts.admin_faq_card(entry), reply_markup=kb.faq_card(entry, 1))


@router.callback_query(AdminFaqCB.filter(F.action.in_({"edit_q", "edit_a"})))
async def faq_edit_start(
    callback: CallbackQuery, callback_data: AdminFaqCB, bot: Bot, state: FSMContext
) -> None:
    editing_question = callback_data.action == "edit_q"
    await state.set_state(FaqEditor.edit_question if editing_question else FaqEditor.edit_answer)
    await state.update_data(entry_id=callback_data.id)
    await callback.answer()
    prompt = texts.FAQ_ASK_QUESTION if editing_question else texts.FAQ_ASK_ANSWER
    await send_html(bot, chat_id_of(callback), prompt, reply_markup=flow_cancel())


@router.message(FaqEditor.edit_question, F.text)
@router.message(FaqEditor.edit_answer, F.text)
async def faq_edit_save(
    message: Message, session: AsyncSession, user: User, state: FSMContext
) -> None:
    data = await state.get_data()
    editing_question = await state.get_state() == FaqEditor.edit_question.state
    entry = await CatalogService(session).save_faq(
        user,
        entry_id=int(data["entry_id"]),
        question=(message.text or "") if editing_question else None,
        answer=None if editing_question else rich_text(message),
    )
    await state.clear()
    await answer_html(message, texts.admin_faq_card(entry), reply_markup=kb.faq_card(entry, 1))


@router.callback_query(AdminFaqCB.filter(F.action == "toggle"))
async def faq_toggle(
    callback: CallbackQuery, callback_data: AdminFaqCB, session: AsyncSession, user: User
) -> None:
    entry = await CatalogService(session).toggle_faq(user, callback_data.id)
    await callback.answer("Показывается" if entry.is_published else "Скрыт")
    await edit_or_send(
        callback, texts.admin_faq_card(entry), reply_markup=kb.faq_card(entry, callback_data.page)
    )


@router.callback_query(AdminFaqCB.filter(F.action == "delete"))
async def faq_delete_ask(callback: CallbackQuery, callback_data: AdminFaqCB) -> None:
    await callback.answer()
    await edit_or_send(
        callback,
        "Удалить этот вопрос?",
        reply_markup=kb.confirm_faq_delete(callback_data.id, callback_data.page),
    )


@router.callback_query(AdminFaqCB.filter(F.action == "delete_yes"))
async def faq_delete(
    callback: CallbackQuery, callback_data: AdminFaqCB, session: AsyncSession, user: User
) -> None:
    catalog = CatalogService(session)
    await catalog.delete_faq(user, callback_data.id)
    await callback.answer(texts.FAQ_DELETED)
    page = await catalog.list_faq(user, callback_data.page)
    await edit_or_send(callback, texts.admin_faq_header(page.total), reply_markup=kb.faq_list(page))
