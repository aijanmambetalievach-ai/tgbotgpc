"""Admin: incoming applications, replies to clients, status changes, statistics."""

from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.bot.callbacks import AdminAppListCB, AppCB
from app.bot.filters import IsAdmin
from app.bot.handlers.helpers import (
    answer_html,
    chat_id_of,
    edit_or_send,
    extract_attachment,
    rich_text,
    send_html,
)
from app.bot.keyboards import admin as kb
from app.bot.keyboards.common import admin_menu, flow_cancel
from app.bot.states import AdminReply
from app.config.settings import get_settings
from app.models.user import User
from app.services.application_service import ApplicationService
from app.services.excel_export_service import ExcelExportService
from app.services.notification_service import NotificationService
from app.services.statistics_service import StatisticsService

logger = logging.getLogger(__name__)

router = Router(name="admin_applications")
router.message.filter(IsAdmin)
router.callback_query.filter(IsAdmin)


@router.message(F.text == texts.BTN_ADMIN_APPLICATIONS)
async def menu_applications(
    message: Message, session: AsyncSession, user: User, state: FSMContext
) -> None:
    await state.clear()
    page = await ApplicationService(session).list_for_admin(user, "new", 1)
    await answer_html(
        message,
        texts.admin_applications_header("new", page.total),
        reply_markup=kb.application_list(page, "new"),
    )


@router.message(F.text == texts.BTN_ADMIN_STATS)
async def menu_statistics(
    message: Message, session: AsyncSession, user: User, state: FSMContext
) -> None:
    await state.clear()
    stats = await StatisticsService(session).dashboard(user)
    await answer_html(
        message,
        texts.statistics(
            stats.clients_total,
            stats.clients_by_category,
            stats.applications.by_status,
            stats.applications.last_7_days,
            stats.lessons_completed,
        ),
    )


@router.callback_query(AdminAppListCB.filter())
async def application_list(
    callback: CallbackQuery,
    callback_data: AdminAppListCB,
    session: AsyncSession,
    user: User,
    state: FSMContext,
) -> None:
    await state.clear()
    page = await ApplicationService(session).list_for_admin(
        user, callback_data.scope, callback_data.page
    )
    await callback.answer()
    await edit_or_send(
        callback,
        texts.admin_applications_header(callback_data.scope, page.total),
        reply_markup=kb.application_list(page, callback_data.scope),
    )


@router.callback_query(AppCB.filter(F.action == "admin"))
async def application_card(
    callback: CallbackQuery,
    callback_data: AppCB,
    session: AsyncSession,
    user: User,
    state: FSMContext,
) -> None:
    await state.clear()
    await callback.answer()
    await _render_card(
        callback, session, user, callback_data.id, callback_data.page, callback_data.scope
    )


async def _render_card(
    callback: CallbackQuery,
    session: AsyncSession,
    user: User,
    application_id: int,
    page: int = 1,
    scope: str = "",
) -> None:
    thread = await ApplicationService(session).get_thread(user, application_id)
    has_files = any(message.media_file_id for message in thread.messages)
    await edit_or_send(
        callback,
        texts.application_card(
            thread.application,
            thread.messages,
            get_settings().timezone,
            client=thread.client,
            assignee=thread.assignee,
        ),
        reply_markup=kb.application_card(thread.application, has_files, page, scope),
    )


@router.callback_query(AppCB.filter(F.action == "export"))
async def export_applications(
    callback: CallbackQuery, session: AsyncSession, user: User, bot: Bot
) -> None:
    await callback.answer("Готовлю файл…")
    excel = await ExcelExportService(session).export_applications(user)
    await bot.send_document(
        chat_id_of(callback), BufferedInputFile(excel.content, filename=excel.filename)
    )


# =============================================================================
# Replying
# =============================================================================
@router.callback_query(AppCB.filter(F.action == "reply"))
async def reply_start(
    callback: CallbackQuery,
    callback_data: AppCB,
    session: AsyncSession,
    user: User,
    bot: Bot,
    state: FSMContext,
) -> None:
    thread = await ApplicationService(session).get_thread(user, callback_data.id)
    if not thread.application.is_open:
        await callback.answer("Заявка уже закрыта.", show_alert=True)
        return
    await state.set_state(AdminReply.writing)
    await state.update_data(application_id=thread.application.id)
    await callback.answer()
    await send_html(
        bot,
        chat_id_of(callback),
        f"Заявка {thread.application.number} · {texts.escape_html(thread.client.full_name)}\n\n"
        + texts.ASK_STAFF_REPLY,
        reply_markup=flow_cancel(),
    )


@router.message(AdminReply.writing)
async def reply_send(
    message: Message, session: AsyncSession, user: User, bot: Bot, state: FSMContext
) -> None:
    attachment = extract_attachment(message)
    text = rich_text(message)
    if not text and attachment is None:
        await answer_html(message, texts.UNSUPPORTED_CONTENT, reply_markup=flow_cancel())
        return
    data = await state.get_data()
    posted = await ApplicationService(session).staff_reply(
        user, int(data["application_id"]), text, attachment
    )
    await state.clear()
    delivered = await NotificationService(bot).notify_staff_reply(posted)
    await answer_html(
        message,
        texts.reply_delivered(delivered),
        reply_markup=kb.application_notification(posted.application.id),
    )


# =============================================================================
# Status changes
# =============================================================================
@router.callback_query(AppCB.filter(F.action == "take"))
async def take(
    callback: CallbackQuery, callback_data: AppCB, session: AsyncSession, user: User, bot: Bot
) -> None:
    change = await ApplicationService(session).take(user, callback_data.id)
    await callback.answer("Заявка в работе")
    await NotificationService(bot).notify_status(change)
    await _render_card(callback, session, user, callback_data.id)


@router.callback_query(AppCB.filter(F.action == "done"))
async def complete_ask(callback: CallbackQuery, callback_data: AppCB) -> None:
    await callback.answer()
    await edit_or_send(
        callback,
        "Завершить заявку? Клиент получит уведомление.",
        reply_markup=kb.confirm_status(callback_data.id, "done", "✅ Завершить"),
    )


@router.callback_query(AppCB.filter(F.action == "done_yes"))
async def complete(
    callback: CallbackQuery, callback_data: AppCB, session: AsyncSession, user: User, bot: Bot
) -> None:
    change = await ApplicationService(session).complete(user, callback_data.id)
    await callback.answer("Заявка завершена")
    await NotificationService(bot).notify_status(change)
    await _render_card(callback, session, user, callback_data.id)


@router.callback_query(AppCB.filter(F.action == "reject"))
async def reject_start(
    callback: CallbackQuery, callback_data: AppCB, bot: Bot, state: FSMContext
) -> None:
    await state.set_state(AdminReply.reject_reason)
    await state.update_data(application_id=callback_data.id)
    await callback.answer()
    await send_html(bot, chat_id_of(callback), texts.ASK_REJECT_REASON, reply_markup=flow_cancel())


@router.message(AdminReply.reject_reason, F.text)
async def reject(
    message: Message, session: AsyncSession, user: User, bot: Bot, state: FSMContext
) -> None:
    data = await state.get_data()
    change = await ApplicationService(session).reject(
        user, int(data["application_id"]), message.text or ""
    )
    await state.clear()
    await NotificationService(bot).notify_status(change)
    await answer_html(
        message,
        f"❌ Заявка {change.application.number} отклонена, клиент уведомлен.",
        reply_markup=admin_menu(),
    )
