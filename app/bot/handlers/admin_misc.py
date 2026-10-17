"""Admin: clients, broadcasts and editable texts."""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.bot.callbacks import AdminClientCB, BroadcastCB, SettingsCB
from app.bot.filters import IsAdmin
from app.bot.handlers.helpers import answer_html, chat_id_of, edit_or_send, rich_text, send_html
from app.bot.keyboards import admin as kb
from app.bot.keyboards.common import admin_menu, client_menu, flow_cancel
from app.bot.states import Broadcast, SettingsEditor
from app.config.settings import get_settings
from app.database.session import session_scope
from app.models.content import BotTextKey
from app.models.enums import ClientCategory
from app.models.user import User
from app.services.application_service import ApplicationService
from app.services.catalog_service import CatalogService
from app.services.client_service import ClientService
from app.services.excel_export_service import ExcelExportService
from app.services.notification_service import NotificationService

logger = logging.getLogger(__name__)

router = Router(name="admin_misc")
router.message.filter(IsAdmin)
router.callback_query.filter(IsAdmin)

#: Strong references to running broadcasts so they are not garbage-collected.
_BACKGROUND_TASKS: set[asyncio.Task[None]] = set()


def _category(filter_key: str) -> ClientCategory | None:
    try:
        return ClientCategory(filter_key)
    except ValueError:
        return None


# =============================================================================
# Clients
# =============================================================================
@router.message(F.text == texts.BTN_ADMIN_CLIENTS)
async def menu_clients(
    message: Message, session: AsyncSession, user: User, state: FSMContext
) -> None:
    await state.clear()
    page = await ClientService(session).list_clients(user)
    await answer_html(
        message,
        texts.admin_clients_header(page.total, "all"),
        reply_markup=kb.client_list(page, "all"),
    )


@router.callback_query(AdminClientCB.filter(F.action == "list"))
async def client_list(
    callback: CallbackQuery, callback_data: AdminClientCB, session: AsyncSession, user: User
) -> None:
    category = _category(callback_data.cat)
    filter_key = str(category) if category else "all"
    page = await ClientService(session).list_clients(user, callback_data.page, category)
    await callback.answer()
    await edit_or_send(
        callback,
        texts.admin_clients_header(page.total, filter_key),
        reply_markup=kb.client_list(page, filter_key),
    )


@router.callback_query(AdminClientCB.filter(F.action == "open"))
async def client_open(
    callback: CallbackQuery, callback_data: AdminClientCB, session: AsyncSession, user: User
) -> None:
    card = await ClientService(session).get_card(user, callback_data.id)
    await callback.answer()
    await edit_or_send(
        callback,
        texts.admin_client_card(card.user, card.applications_count, get_settings().timezone),
        reply_markup=kb.client_card(card.user, callback_data.page, callback_data.cat),
    )


@router.callback_query(AdminClientCB.filter(F.action.in_({"block", "unblock"})))
async def client_block(
    callback: CallbackQuery, callback_data: AdminClientCB, session: AsyncSession, user: User
) -> None:
    service = ClientService(session)
    blocked = callback_data.action == "block"
    await service.set_blocked(user, callback_data.id, blocked)
    card = await service.get_card(user, callback_data.id)
    await callback.answer("Клиент заблокирован" if blocked else "Доступ восстановлен")
    await edit_or_send(
        callback,
        texts.admin_client_card(card.user, card.applications_count, get_settings().timezone),
        reply_markup=kb.client_card(card.user, callback_data.page, callback_data.cat),
    )


@router.callback_query(AdminClientCB.filter(F.action == "apps"))
async def client_applications(
    callback: CallbackQuery, callback_data: AdminClientCB, session: AsyncSession, user: User
) -> None:
    page = await ApplicationService(session).list_of_client(
        user, callback_data.id, callback_data.page
    )
    await callback.answer()
    await edit_or_send(
        callback,
        f"📋 <b>Заявки клиента</b>\nВсего: {page.total}" if page.total else "У клиента нет заявок.",
        reply_markup=kb.client_applications(page, callback_data.id),
    )


@router.callback_query(AdminClientCB.filter(F.action == "export"))
async def client_export(
    callback: CallbackQuery, session: AsyncSession, user: User, bot: Bot
) -> None:
    await callback.answer("Готовлю файл…")
    excel = await ExcelExportService(session).export_clients(user)
    await bot.send_document(
        chat_id_of(callback), BufferedInputFile(excel.content, filename=excel.filename)
    )


# =============================================================================
# Broadcast
# =============================================================================
@router.message(F.text == texts.BTN_ADMIN_BROADCAST)
async def menu_broadcast(message: Message, state: FSMContext) -> None:
    await state.clear()
    await answer_html(
        message, texts.BROADCAST_CHOOSE_AUDIENCE, reply_markup=kb.broadcast_audiences()
    )


@router.callback_query(BroadcastCB.filter(F.action == "audience"))
async def broadcast_audience(
    callback: CallbackQuery, callback_data: BroadcastCB, state: FSMContext
) -> None:
    if callback_data.value not in kb.BROADCAST_AUDIENCES:
        await callback.answer(texts.STALE_CALLBACK, show_alert=True)
        return
    await state.set_state(Broadcast.message)
    await state.update_data(audience=callback_data.value)
    await callback.answer()
    await edit_or_send(
        callback,
        texts.broadcast_ask_message(kb.BROADCAST_AUDIENCES[callback_data.value]),
        reply_markup=flow_cancel(),
    )


@router.message(Broadcast.message)
async def broadcast_message(
    message: Message, session: AsyncSession, user: User, bot: Bot, state: FSMContext
) -> None:
    data = await state.get_data()
    audience = str(data.get("audience", "ALL"))
    recipients = await ClientService(session).broadcast_recipients(user, _category(audience))
    if not recipients:
        await state.clear()
        await answer_html(message, texts.BROADCAST_NO_RECIPIENTS, reply_markup=admin_menu())
        return
    await state.set_state(Broadcast.confirm)
    await state.update_data(from_chat_id=message.chat.id, message_id=message.message_id)
    # Show the admin exactly what clients will receive.
    await bot.copy_message(message.chat.id, message.chat.id, message.message_id)
    await answer_html(
        message,
        texts.broadcast_preview(kb.BROADCAST_AUDIENCES[audience], len(recipients)),
        reply_markup=kb.broadcast_confirm(),
    )


@router.callback_query(BroadcastCB.filter(F.action == "send"), Broadcast.confirm)
async def broadcast_send(
    callback: CallbackQuery, session: AsyncSession, user: User, bot: Bot, state: FSMContext
) -> None:
    data = await state.get_data()
    await state.clear()
    audience = str(data.get("audience", "ALL"))
    category = _category(audience)
    recipients = await ClientService(session).broadcast_recipients(user, category)
    await callback.answer()
    await edit_or_send(callback, texts.BROADCAST_STARTED)

    async def run() -> None:
        delivered = await NotificationService(bot).broadcast_copy(
            recipients, int(data["from_chat_id"]), int(data["message_id"])
        )
        async with session_scope() as task_session:
            await ClientService(task_session).log_broadcast(
                user, category, delivered, len(recipients)
            )
        await send_html(bot, user.telegram_id, texts.broadcast_done(delivered, len(recipients)))

    task = asyncio.create_task(run())
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)


# =============================================================================
# Settings
# =============================================================================
@router.message(F.text == texts.BTN_ADMIN_SETTINGS)
async def menu_settings(message: Message, state: FSMContext) -> None:
    await state.clear()
    await answer_html(message, texts.SETTINGS_MENU, reply_markup=kb.settings_menu())


@router.callback_query(SettingsCB.filter(F.action == "edit"))
async def settings_edit(
    callback: CallbackQuery,
    callback_data: SettingsCB,
    session: AsyncSession,
    bot: Bot,
    state: FSMContext,
) -> None:
    prompt = texts.SETTINGS_ASK.get(callback_data.key)
    if prompt is None:
        await callback.answer(texts.STALE_CALLBACK, show_alert=True)
        return
    current = await CatalogService(session).get_text(callback_data.key)
    await state.set_state(SettingsEditor.text)
    await state.update_data(key=callback_data.key)
    await callback.answer()
    await send_html(bot, chat_id_of(callback), f"Сейчас:\n\n{current}")
    await send_html(bot, chat_id_of(callback), prompt, reply_markup=flow_cancel())


@router.message(SettingsEditor.text, F.text)
async def settings_save(
    message: Message, session: AsyncSession, user: User, state: FSMContext
) -> None:
    key = str((await state.get_data())["key"])
    catalog = CatalogService(session)
    await catalog.set_text(user, key, rich_text(message))
    await state.clear()
    await answer_html(message, texts.SETTINGS_SAVED, reply_markup=admin_menu())
    await answer_html(
        message,
        texts.about(
            await catalog.get_text(BotTextKey.ABOUT), await catalog.get_text(BotTextKey.CONTACTS)
        ),
    )


@router.callback_query(SettingsCB.filter(F.action == "client_mode"))
async def settings_client_mode(callback: CallbackQuery, bot: Bot, state: FSMContext) -> None:
    await state.clear()
    await callback.answer()
    await bot.send_message(
        chat_id_of(callback),
        "👁 Меню клиента. Вернуться в админ-панель: /admin",
        reply_markup=client_menu(),
    )
