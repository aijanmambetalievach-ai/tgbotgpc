"""Client sections: training catalog, lessons with quizzes, FAQ, about, profile
and "my applications" with the conversation thread.

Creating applications lives in :mod:`app.bot.handlers.client_flow`.
"""

from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.bot.callbacks import AppCB, CourseCB, FaqCB, LessonCB, MenuCB, ProfileCB, QuizCB
from app.bot.handlers.helpers import (
    answer_html,
    chat_id_of,
    edit_or_send,
    extract_attachment,
    plain_text,
    send_html,
    send_media,
)
from app.bot.keyboards import client as kb
from app.bot.keyboards.common import client_menu, flow_cancel, share_phone
from app.bot.states import ClientChat, ProfileEdit, Quiz
from app.config.settings import get_settings
from app.domain.exceptions import DomainError
from app.models.content import BotTextKey, quiz_options
from app.models.enums import UserRole
from app.models.user import User
from app.repositories.users import UserRepository
from app.services.application_service import ApplicationService
from app.services.catalog_service import CatalogService, LessonView
from app.services.client_service import ClientService
from app.services.notification_service import NotificationService

logger = logging.getLogger(__name__)

router = Router(name="client")


# =============================================================================
# Main menu
# =============================================================================
@router.message(F.text == texts.BTN_TRAINING)
async def menu_training(message: Message, state: FSMContext) -> None:
    await state.clear()
    await answer_html(message, texts.TRAINING_MENU, reply_markup=kb.training_menu())


@router.callback_query(MenuCB.filter(F.to == "training"))
async def back_to_training(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.answer()
    await edit_or_send(callback, texts.TRAINING_MENU, reply_markup=kb.training_menu())


@router.message(F.text == texts.BTN_FAQ)
async def menu_faq(message: Message, session: AsyncSession, user: User, state: FSMContext) -> None:
    await state.clear()
    page = await CatalogService(session).list_faq(user, page=1)
    if page.is_empty:
        await answer_html(message, texts.NO_FAQ)
        return
    await answer_html(message, texts.FAQ_HEADER, reply_markup=kb.faq_list(page))


@router.message(F.text == texts.BTN_ABOUT)
async def menu_about(message: Message, session: AsyncSession, state: FSMContext) -> None:
    await state.clear()
    catalog = CatalogService(session)
    await answer_html(
        message,
        texts.about(
            await catalog.get_text(BotTextKey.ABOUT), await catalog.get_text(BotTextKey.CONTACTS)
        ),
        reply_markup=kb.about(),
    )


@router.message(F.text == texts.BTN_PROFILE)
async def menu_profile(message: Message, user: User, state: FSMContext) -> None:
    await state.clear()
    await answer_html(message, texts.profile(user), reply_markup=kb.profile())


@router.message(F.text == texts.BTN_MY_APPLICATIONS)
async def menu_my_applications(
    message: Message, session: AsyncSession, user: User, state: FSMContext
) -> None:
    await state.clear()
    page = await ApplicationService(session).list_own(user, page=1)
    if page.is_empty:
        await answer_html(message, texts.NO_APPLICATIONS)
        return
    await answer_html(
        message, texts.my_applications_header(page.total), reply_markup=kb.my_applications(page)
    )


# =============================================================================
# Courses
# =============================================================================
@router.callback_query(CourseCB.filter(F.action == "list"))
async def course_list(
    callback: CallbackQuery, callback_data: CourseCB, session: AsyncSession, user: User
) -> None:
    show_all = bool(callback_data.all)
    page = await CatalogService(session).list_courses(
        _as_client(user), page=callback_data.page, show_all=show_all
    )
    await callback.answer()
    if page.is_empty and not show_all and user.category is not None:
        # Nothing for this category — fall back to everything published.
        show_all = True
        page = await CatalogService(session).list_courses(_as_client(user), show_all=True)
    if page.is_empty:
        await edit_or_send(callback, texts.NO_COURSES, reply_markup=kb.training_menu())
        return
    filtered = not show_all and user.category is not None
    await edit_or_send(
        callback,
        texts.courses_header(page.total, filtered),
        reply_markup=kb.course_list(page, show_all, user.category is not None),
    )


@router.callback_query(CourseCB.filter(F.action == "open"))
async def course_open(
    callback: CallbackQuery, callback_data: CourseCB, session: AsyncSession, user: User
) -> None:
    card = await CatalogService(session).get_course(_as_client(user), callback_data.id)
    await callback.answer()
    await edit_or_send(
        callback,
        texts.course_card(card.course),
        reply_markup=kb.course_card(card.course.id, callback_data.page, bool(callback_data.all)),
    )


async def show_course_from_link(
    message: Message, session: AsyncSession, user: User, course_id: int
) -> None:
    """``/start course_<id>`` — an advertising link straight to a course."""
    try:
        card = await CatalogService(session).get_course(_as_client(user), course_id)
    except DomainError as exc:
        await answer_html(message, f"⚠️ {exc.message}", reply_markup=kb.training_menu())
        return
    await answer_html(
        message,
        texts.course_card(card.course),
        reply_markup=kb.course_card(card.course.id, 1, True),
    )


# =============================================================================
# Lessons
# =============================================================================
@router.callback_query(LessonCB.filter(F.action == "list"))
async def lesson_list(
    callback: CallbackQuery,
    callback_data: LessonCB,
    session: AsyncSession,
    user: User,
    state: FSMContext,
) -> None:
    await state.clear()
    show_all = bool(callback_data.all)
    catalog = CatalogService(session)
    listing = await catalog.list_lessons(
        _as_client(user), page=callback_data.page, show_all=show_all
    )
    if listing.page.is_empty and not show_all and user.category is not None:
        show_all = True
        listing = await catalog.list_lessons(_as_client(user), show_all=True)
    await callback.answer()
    if listing.page.is_empty:
        await edit_or_send(callback, texts.NO_LESSONS, reply_markup=kb.training_menu())
        return
    filtered = not show_all and user.category is not None
    await edit_or_send(
        callback,
        texts.lessons_header(listing.page.total, len(listing.completed), filtered),
        reply_markup=kb.lesson_list(listing, show_all, user.category is not None),
    )


@router.callback_query(LessonCB.filter(F.action == "open"))
async def lesson_open(
    callback: CallbackQuery,
    callback_data: LessonCB,
    session: AsyncSession,
    user: User,
    bot: Bot,
    state: FSMContext,
) -> None:
    await state.clear()
    show_all = bool(callback_data.all)
    view = await CatalogService(session).view_lesson(_as_client(user), callback_data.id, show_all)
    await callback.answer()
    await send_lesson(bot, chat_id_of(callback), view, show_all)


async def send_lesson(bot: Bot, chat_id: int, view: LessonView, show_all: bool) -> None:
    """A lesson is always sent as new messages: the file (if any) and then the
    text with navigation — a media message cannot be edited into text."""
    lesson = view.lesson
    if lesson.media_type and lesson.media_file_id:
        await send_media(bot, chat_id, lesson.media_type, lesson.media_file_id)
    await send_html(
        bot,
        chat_id,
        texts.lesson_text(lesson, view.index, view.total, len(view.questions), view.progress),
        reply_markup=kb.lesson_view(view, show_all),
    )


@router.callback_query(LessonCB.filter(F.action == "done"))
async def lesson_done(
    callback: CallbackQuery, callback_data: LessonCB, session: AsyncSession, user: User
) -> None:
    catalog = CatalogService(session)
    show_all = bool(callback_data.all)
    await catalog.complete_lesson(user, callback_data.id)
    view = await catalog.view_lesson(_as_client(user), callback_data.id, show_all)
    await callback.answer(texts.LESSON_COMPLETED)
    text = texts.LESSON_COMPLETED if view.next_id else texts.ALL_LESSONS_DONE
    await edit_or_send(
        callback, text, reply_markup=kb.after_lesson(view.lesson.id, view.next_id, show_all)
    )


@router.callback_query(LessonCB.filter(F.action == "quiz"))
async def quiz_start(
    callback: CallbackQuery,
    callback_data: LessonCB,
    session: AsyncSession,
    user: User,
    bot: Bot,
    state: FSMContext,
) -> None:
    view = await CatalogService(session).view_lesson(
        _as_client(user), callback_data.id, bool(callback_data.all)
    )
    if not view.questions:
        await callback.answer(texts.STALE_CALLBACK, show_alert=True)
        return
    await state.set_state(Quiz.answering)
    await state.update_data(
        quiz_lesson=view.lesson.id, quiz_number=1, quiz_score=0, quiz_all=callback_data.all
    )
    await callback.answer()
    await _send_question(bot, chat_id_of(callback), view, 1)


async def _send_question(bot: Bot, chat_id: int, view: LessonView, number: int) -> None:
    question = view.questions[number - 1]
    options = quiz_options(question.options)
    await send_html(
        bot,
        chat_id,
        texts.quiz_question(question, options, number, len(view.questions)),
        reply_markup=kb.quiz_options(view.lesson.id, number, len(options)),
    )


@router.callback_query(QuizCB.filter())
async def quiz_answer(
    callback: CallbackQuery,
    callback_data: QuizCB,
    session: AsyncSession,
    user: User,
    bot: Bot,
    state: FSMContext,
) -> None:
    data = await state.get_data()
    if (
        await state.get_state() != Quiz.answering.state
        or data.get("quiz_lesson") != callback_data.lesson
        or data.get("quiz_number") != callback_data.number
    ):
        # Double tap, or an old question from a previous attempt.
        await callback.answer(texts.STALE_CALLBACK)
        return

    show_all = bool(data.get("quiz_all"))
    catalog = CatalogService(session)
    view = await catalog.view_lesson(_as_client(user), callback_data.lesson, show_all)
    total = len(view.questions)
    number = callback_data.number
    if number > total:
        await state.clear()
        await callback.answer(texts.STALE_CALLBACK, show_alert=True)
        return

    question = view.questions[number - 1]
    options = quiz_options(question.options)
    correct = callback_data.option == question.correct_option
    score = int(data.get("quiz_score", 0)) + int(correct)
    await callback.answer("✅ Верно!" if correct else "❌ Неверно")
    await edit_or_send(
        callback,
        texts.quiz_answer_feedback(question, options, callback_data.option, number, total),
    )

    if number < total:
        await state.update_data(quiz_number=number + 1, quiz_score=score)
        await _send_question(bot, chat_id_of(callback), view, number + 1)
        return

    await state.clear()
    await catalog.complete_lesson(user, view.lesson.id, quiz_score=score, quiz_total=total)
    await send_html(
        bot,
        chat_id_of(callback),
        texts.quiz_result(score, total),
        reply_markup=kb.after_lesson(view.lesson.id, view.next_id, show_all),
    )


# =============================================================================
# FAQ
# =============================================================================
@router.callback_query(FaqCB.filter(F.action == "list"))
async def faq_list(
    callback: CallbackQuery, callback_data: FaqCB, session: AsyncSession, user: User
) -> None:
    page = await CatalogService(session).list_faq(_as_client(user), page=callback_data.page)
    await callback.answer()
    if page.is_empty:
        await edit_or_send(callback, texts.NO_FAQ)
        return
    await edit_or_send(callback, texts.FAQ_HEADER, reply_markup=kb.faq_list(page))


@router.callback_query(FaqCB.filter(F.action == "open"))
async def faq_open(
    callback: CallbackQuery, callback_data: FaqCB, session: AsyncSession, user: User
) -> None:
    entry = await CatalogService(session).get_faq(_as_client(user), callback_data.id)
    await callback.answer()
    await edit_or_send(
        callback, texts.faq_answer(entry), reply_markup=kb.faq_answer(callback_data.page)
    )


# =============================================================================
# My applications
# =============================================================================
@router.callback_query(AppCB.filter(F.action == "mine"))
async def my_applications(
    callback: CallbackQuery,
    callback_data: AppCB,
    session: AsyncSession,
    user: User,
    state: FSMContext,
) -> None:
    await state.clear()
    page = await ApplicationService(session).list_own(user, page=callback_data.page)
    await callback.answer()
    if page.is_empty:
        await edit_or_send(callback, texts.NO_APPLICATIONS)
        return
    await edit_or_send(
        callback, texts.my_applications_header(page.total), reply_markup=kb.my_applications(page)
    )


@router.callback_query(AppCB.filter(F.action == "open"))
async def application_open(
    callback: CallbackQuery,
    callback_data: AppCB,
    session: AsyncSession,
    user: User,
    state: FSMContext,
) -> None:
    await state.clear()
    thread = await ApplicationService(session).get_thread(user, callback_data.id)
    await callback.answer()
    has_files = any(message.media_file_id for message in thread.messages)
    await edit_or_send(
        callback,
        texts.application_card(thread.application, thread.messages, get_settings().timezone),
        reply_markup=kb.application_card(
            thread.application.id, thread.application.is_open, has_files, callback_data.page
        ),
    )


@router.callback_query(AppCB.filter(F.action == "files"))
async def application_files(
    callback: CallbackQuery, callback_data: AppCB, session: AsyncSession, user: User, bot: Bot
) -> None:
    """Re-send the photos and documents of a thread (works for admins too)."""
    thread = await ApplicationService(session).get_thread(user, callback_data.id)
    await callback.answer()
    sent = await NotificationService(bot).send_attachments(chat_id_of(callback), thread.messages)
    if not sent:
        await send_html(bot, chat_id_of(callback), "Файлов в заявке нет.")


@router.callback_query(AppCB.filter(F.action == "write"))
async def application_write(
    callback: CallbackQuery,
    callback_data: AppCB,
    session: AsyncSession,
    user: User,
    state: FSMContext,
) -> None:
    thread = await ApplicationService(session).get_thread(user, callback_data.id)
    if not thread.application.is_open:
        await callback.answer("Эта заявка уже закрыта.", show_alert=True)
        return
    await state.set_state(ClientChat.writing)
    await state.update_data(application_id=thread.application.id)
    await callback.answer()
    if isinstance(callback.message, Message):
        await answer_html(
            callback.message,
            f"Заявка {thread.application.number}.\n\n{texts.ASK_CLIENT_MESSAGE}",
            reply_markup=flow_cancel(),
        )


@router.message(ClientChat.writing)
async def application_write_message(
    message: Message, session: AsyncSession, user: User, bot: Bot, state: FSMContext
) -> None:
    attachment = extract_attachment(message)
    text = plain_text(message)
    if not text and attachment is None:
        await answer_html(message, texts.UNSUPPORTED_CONTENT, reply_markup=flow_cancel())
        return
    data = await state.get_data()
    posted = await ApplicationService(session).client_message(
        user, int(data["application_id"]), text, attachment
    )
    await state.clear()
    await answer_html(message, texts.MESSAGE_SENT, reply_markup=client_menu())
    await NotificationService(bot).notify_client_message(posted)


@router.callback_query(AppCB.filter(F.action == "cancel"))
async def application_cancel_ask(callback: CallbackQuery, callback_data: AppCB) -> None:
    await callback.answer()
    await edit_or_send(
        callback,
        texts.CONFIRM_CANCEL_APPLICATION,
        reply_markup=kb.confirm_cancel_application(callback_data.id),
    )


@router.callback_query(AppCB.filter(F.action == "cancel_yes"))
async def application_cancel(
    callback: CallbackQuery, callback_data: AppCB, session: AsyncSession, user: User, bot: Bot
) -> None:
    change = await ApplicationService(session).cancel(user, callback_data.id)
    await callback.answer(texts.APPLICATION_CANCELLED)
    await edit_or_send(callback, texts.APPLICATION_CANCELLED)
    admins = await UserRepository(session).list_admins()
    await NotificationService(bot).notify_cancelled(change, admins)


# =============================================================================
# Profile
# =============================================================================
@router.callback_query(ProfileCB.filter())
async def profile_edit(
    callback: CallbackQuery, callback_data: ProfileCB, user: User, state: FSMContext
) -> None:
    await callback.answer()
    if callback_data.action == "category":
        await edit_or_send(callback, texts.ASK_CATEGORY, reply_markup=kb.categories(edit=True))
        return
    prompts = {
        "name": (ProfileEdit.name, texts.ASK_NAME, flow_cancel()),
        "phone": (ProfileEdit.phone, texts.ASK_PHONE, share_phone()),
        "organization": (ProfileEdit.organization, "Укажите организацию:", flow_cancel()),
    }
    if callback_data.action not in prompts:
        return
    target_state, prompt, markup = prompts[callback_data.action]
    await state.set_state(target_state)
    if isinstance(callback.message, Message):
        await answer_html(callback.message, prompt, reply_markup=markup)


@router.message(ProfileEdit.name, F.text)
async def profile_name(
    message: Message, session: AsyncSession, user: User, state: FSMContext
) -> None:
    await ClientService(session).update_contacts(user, full_name=message.text or "")
    await _profile_saved(message, user, state)


@router.message(ProfileEdit.phone, F.contact | F.text)
async def profile_phone(
    message: Message, session: AsyncSession, user: User, state: FSMContext
) -> None:
    raw = message.contact.phone_number if message.contact else (message.text or "")
    await ClientService(session).update_contacts(user, phone=raw)
    await _profile_saved(message, user, state)


@router.message(ProfileEdit.organization, F.text)
async def profile_organization(
    message: Message, session: AsyncSession, user: User, state: FSMContext
) -> None:
    await ClientService(session).update_contacts(user, organization=message.text or "")
    await _profile_saved(message, user, state)


async def _profile_saved(message: Message, user: User, state: FSMContext) -> None:
    await state.clear()
    await answer_html(message, texts.PROFILE_SAVED, reply_markup=client_menu())
    await answer_html(message, texts.profile(user), reply_markup=kb.profile())


# =============================================================================
# helpers
# =============================================================================
def _as_client(user: User) -> User:
    """Admins browsing the client side see exactly what clients see.

    A transient copy with the client role — never added to the session, so it
    can't be flushed by accident.
    """
    if not user.is_admin:
        return user
    clone = User(
        telegram_id=user.telegram_id,
        full_name=user.full_name,
        role=UserRole.CLIENT,
        category=user.category,
        is_active=user.is_active,
    )
    clone.id = user.id
    return clone
