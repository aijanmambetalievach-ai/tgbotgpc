"""Creating an application: course sign-up, individual training, consultation.

All three dialogs collect their own details, then share the same tail:
contact details (only the first time — name and phone are remembered),
a confirmation screen and the actual submission.

    course:        comment ─────────────────────────────┐
    individual:    goal → preferred time → contact way ──┼─► name/phone ─► confirm
    consultation:  question → contact way [→ time] ─────┘
"""

from __future__ import annotations

import logging
from typing import Any

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.bot.callbacks import CourseCB, FlowCB, MenuCB
from app.bot.handlers.helpers import (
    answer_html,
    chat_id_of,
    edit_or_send,
    extract_attachment,
    plain_text,
    send_html,
)
from app.bot.keyboards import client as kb
from app.bot.keyboards.common import client_menu, flow_cancel, flow_skip_cancel, share_phone
from app.bot.states import ClientFlow
from app.domain.exceptions import DomainError, DuplicateApplicationError
from app.domain.text import escape_html
from app.models.enums import (
    CONTACT_METHOD_LABELS,
    TOPIC_LABELS,
    ApplicationType,
    ConsultationTopic,
    ContactMethod,
    MediaType,
)
from app.models.user import User
from app.services.application_service import (
    ApplicationService,
    Attachment,
    CreatedApplication,
)
from app.services.catalog_service import CatalogService
from app.services.client_service import ClientService
from app.services.notification_service import NotificationService

logger = logging.getLogger(__name__)

router = Router(name="client_flow")


# =============================================================================
# Entry points
# =============================================================================
@router.callback_query(CourseCB.filter(F.action == "enroll"))
async def enroll_start(
    callback: CallbackQuery,
    callback_data: CourseCB,
    session: AsyncSession,
    user: User,
    bot: Bot,
    state: FSMContext,
) -> None:
    card = await CatalogService(session).get_course(user, callback_data.id)
    await state.clear()
    await state.set_state(ClientFlow.course_comment)
    await state.update_data(
        kind=ApplicationType.COURSE, course_id=card.course.id, course_title=card.course.title
    )
    await callback.answer()
    await _ask(bot, callback, texts.ask_course_comment(card.course.title), flow_skip_cancel())


@router.callback_query(MenuCB.filter(F.to == "individual"))
async def individual_start(callback: CallbackQuery, bot: Bot, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(ClientFlow.individual_goal)
    await state.update_data(kind=ApplicationType.INDIVIDUAL)
    await callback.answer()
    await _ask(bot, callback, texts.INDIVIDUAL_INTRO, flow_cancel())


@router.message(F.text == texts.BTN_CONSULTATION)
async def consultation_menu(message: Message, state: FSMContext) -> None:
    await state.clear()
    await answer_html(message, texts.CONSULTATION_INTRO, reply_markup=kb.topics())


@router.callback_query(MenuCB.filter(F.to == "consult"))
async def consultation_menu_button(callback: CallbackQuery, bot: Bot, state: FSMContext) -> None:
    await state.clear()
    await callback.answer()
    await _ask(bot, callback, texts.CONSULTATION_INTRO, kb.topics())


@router.callback_query(FlowCB.filter(F.action == "topic"))
async def consultation_topic(
    callback: CallbackQuery, callback_data: FlowCB, state: FSMContext
) -> None:
    try:
        topic = ConsultationTopic(callback_data.value)
    except ValueError:
        await callback.answer(texts.STALE_CALLBACK, show_alert=True)
        return
    await state.clear()
    await state.set_state(ClientFlow.consultation_question)
    await state.update_data(kind=ApplicationType.CONSULTATION, topic=topic)
    await callback.answer()
    await edit_or_send(
        callback, texts.consultation_ask_question(TOPIC_LABELS[topic]), reply_markup=flow_cancel()
    )


# =============================================================================
# Details
# =============================================================================
@router.message(ClientFlow.course_comment, F.text)
async def course_comment(message: Message, user: User, state: FSMContext) -> None:
    await state.update_data(description=message.text or "")
    await _to_contacts(message, user, state)


@router.message(ClientFlow.individual_goal, F.text)
async def individual_goal(message: Message, state: FSMContext) -> None:
    await state.update_data(description=message.text or "")
    await state.set_state(ClientFlow.preferred_time)
    await answer_html(message, texts.ASK_PREFERRED_TIME, reply_markup=flow_skip_cancel())


@router.message(ClientFlow.consultation_question, F.text | F.photo | F.document | F.video)
async def consultation_question(message: Message, state: FSMContext) -> None:
    attachment = extract_attachment(message)
    text = plain_text(message)
    if not text and attachment is None:
        await answer_html(message, texts.UNSUPPORTED_CONTENT, reply_markup=flow_cancel())
        return
    await state.update_data(
        description=text,
        attachment_type=attachment.media_type if attachment else None,
        attachment_file_id=attachment.file_id if attachment else None,
    )
    await state.set_state(ClientFlow.contact_method)
    await answer_html(message, texts.ASK_CONTACT_METHOD, reply_markup=kb.contact_methods())


@router.message(ClientFlow.preferred_time, F.text)
async def preferred_time(message: Message, user: User, state: FSMContext) -> None:
    await state.update_data(preferred_time=message.text or "")
    await _after_preferred_time(message, user, state)


@router.callback_query(FlowCB.filter(F.action == "skip"), ClientFlow.course_comment)
async def skip_course_comment(callback: CallbackQuery, user: User, state: FSMContext) -> None:
    await callback.answer()
    await state.update_data(description="")
    if isinstance(callback.message, Message):
        await _to_contacts(callback.message, user, state)


@router.callback_query(FlowCB.filter(F.action == "skip"), ClientFlow.preferred_time)
async def skip_preferred_time(callback: CallbackQuery, user: User, state: FSMContext) -> None:
    await callback.answer()
    await state.update_data(preferred_time="")
    if isinstance(callback.message, Message):
        await _after_preferred_time(callback.message, user, state)


async def _after_preferred_time(message: Message, user: User, state: FSMContext) -> None:
    data = await state.get_data()
    if data.get("kind") == ApplicationType.INDIVIDUAL and not data.get("contact_method"):
        await state.set_state(ClientFlow.contact_method)
        await answer_html(message, texts.ASK_CONTACT_METHOD, reply_markup=kb.contact_methods())
        return
    await _to_contacts(message, user, state)


@router.callback_query(FlowCB.filter(F.action == "contact"), ClientFlow.contact_method)
async def contact_method(
    callback: CallbackQuery, callback_data: FlowCB, user: User, state: FSMContext
) -> None:
    try:
        method = ContactMethod(callback_data.value)
    except ValueError:
        await callback.answer(texts.STALE_CALLBACK, show_alert=True)
        return
    await callback.answer()
    await state.update_data(contact_method=method)
    await edit_or_send(callback, f"Связь: {CONTACT_METHOD_LABELS[method]}")
    if not isinstance(callback.message, Message):
        return
    data = await state.get_data()
    # A consultation by phone or in person needs a time; individual training
    # already asked for it before the contact method.
    if data.get("kind") == ApplicationType.CONSULTATION and method is not ContactMethod.TELEGRAM:
        await state.set_state(ClientFlow.preferred_time)
        await answer_html(
            callback.message, texts.ASK_PREFERRED_TIME, reply_markup=flow_skip_cancel()
        )
        return
    await _to_contacts(callback.message, user, state)


# =============================================================================
# Contact details
# =============================================================================
async def _to_contacts(message: Message, user: User, state: FSMContext) -> None:
    if user.has_contact_details:
        await _show_confirm(message, user, state)
        return
    await state.set_state(ClientFlow.name)
    await answer_html(message, texts.ASK_NAME, reply_markup=kb.use_telegram_name(user.full_name))


@router.message(ClientFlow.name, F.text)
async def contact_name(message: Message, state: FSMContext) -> None:
    await state.update_data(name=ClientService.validate_name(message.text or ""))
    await _ask_phone(message, state)


@router.callback_query(FlowCB.filter(F.action == "tg_name"), ClientFlow.name)
async def contact_telegram_name(callback: CallbackQuery, user: User, state: FSMContext) -> None:
    await callback.answer()
    await state.update_data(name=user.full_name)
    await edit_or_send(callback, f"Имя: {escape_html(user.full_name)}")
    if isinstance(callback.message, Message):
        await _ask_phone(callback.message, state)


async def _ask_phone(message: Message, state: FSMContext) -> None:
    await state.set_state(ClientFlow.phone)
    await answer_html(message, texts.ASK_PHONE, reply_markup=share_phone())


@router.message(ClientFlow.phone, F.contact | F.text)
async def contact_phone(
    message: Message, session: AsyncSession, user: User, state: FSMContext
) -> None:
    raw = message.contact.phone_number if message.contact else (message.text or "")
    data = await state.get_data()
    await ClientService(session).update_contacts(
        user, full_name=str(data.get("name") or user.full_name), phone=raw
    )
    await answer_html(message, "✅ Контакты сохранены.", reply_markup=client_menu())
    await _show_confirm(message, user, state)


# =============================================================================
# Confirmation & submission
# =============================================================================
async def _show_confirm(message: Message, user: User, state: FSMContext) -> None:
    data = await state.get_data()
    kind = ApplicationType(data["kind"])
    method = data.get("contact_method")
    await state.set_state(ClientFlow.confirm)
    await answer_html(
        message,
        texts.confirm_application(
            kind,
            user,
            subject=_subject(data),
            description=str(data.get("description") or ""),
            preferred_time=str(data.get("preferred_time") or ""),
            contact_method_label=CONTACT_METHOD_LABELS[ContactMethod(method)] if method else None,
            has_attachment=bool(data.get("attachment_file_id")),
        ),
        reply_markup=kb.confirm_application(),
    )


@router.callback_query(FlowCB.filter(F.action == "submit"), ClientFlow.confirm)
async def submit(
    callback: CallbackQuery, session: AsyncSession, user: User, bot: Bot, state: FSMContext
) -> None:
    data = await state.get_data()
    service = ApplicationService(session)
    try:
        created = await _create(service, user, data)
    except DuplicateApplicationError as exc:
        await state.clear()
        await callback.answer()
        await edit_or_send(
            callback, f"ℹ️ {exc.message}\nСтатус — в разделе {texts.BTN_MY_APPLICATIONS}."
        )
        return
    except DomainError:
        await state.clear()
        raise
    await state.clear()
    await callback.answer("Заявка отправлена")
    await edit_or_send(callback, texts.application_created(created.application))
    await NotificationService(bot).notify_new_application(created)


async def _create(
    service: ApplicationService, user: User, data: dict[str, Any]
) -> CreatedApplication:
    kind = ApplicationType(data["kind"])
    description = str(data.get("description") or "")
    preferred = str(data.get("preferred_time") or "")
    method = ContactMethod(data.get("contact_method") or ContactMethod.TELEGRAM)
    if kind is ApplicationType.COURSE:
        return await service.enroll_in_course(user, int(data["course_id"]), description)
    if kind is ApplicationType.INDIVIDUAL:
        return await service.request_individual(user, description, preferred, method)
    attachment = None
    if data.get("attachment_file_id"):
        attachment = Attachment(MediaType(data["attachment_type"]), str(data["attachment_file_id"]))
    return await service.request_consultation(
        user,
        ConsultationTopic(data["topic"]),
        description,
        method,
        attachment=attachment,
        preferred_time=preferred,
    )


def _subject(data: dict[str, Any]) -> str | None:
    if data.get("course_title"):
        return str(data["course_title"])
    if data.get("topic"):
        return TOPIC_LABELS[ConsultationTopic(data["topic"])]
    return None


# =============================================================================
# Anything else typed in the middle of a dialog
# =============================================================================
@router.message(ClientFlow.contact_method)
@router.message(ClientFlow.confirm)
async def expect_button(message: Message) -> None:
    await answer_html(message, texts.USE_BUTTONS)


@router.message(ClientFlow.course_comment)
@router.message(ClientFlow.individual_goal)
@router.message(ClientFlow.consultation_question)
@router.message(ClientFlow.preferred_time)
@router.message(ClientFlow.name)
@router.message(ClientFlow.phone)
async def unsupported_content(message: Message) -> None:
    await answer_html(message, texts.UNSUPPORTED_CONTENT, reply_markup=flow_cancel())


async def _ask(bot: Bot, callback: CallbackQuery, text: str, markup: Any) -> None:
    """Prompts are new messages so the previous screen (a course card, the
    training menu) stays readable above them."""
    await send_html(bot, chat_id_of(callback), text, reply_markup=markup)
