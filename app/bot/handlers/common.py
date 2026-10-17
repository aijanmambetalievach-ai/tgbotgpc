"""Commands available to everyone, onboarding and the global "cancel"."""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.bot.callbacks import CategoryCB, FlowCB, NoopCB
from app.bot.handlers.client import show_course_from_link
from app.bot.handlers.helpers import answer_html, edit_or_send, menu_for
from app.bot.keyboards import client as client_kb
from app.bot.keyboards.common import admin_menu, client_menu
from app.config.settings import get_settings
from app.models.enums import ClientCategory
from app.models.user import User
from app.services.client_service import ClientService

logger = logging.getLogger(__name__)

router = Router(name="common")

#: ``/start course_12`` opens a course card — handy for advertising links.
COURSE_DEEP_LINK = "course_"
CONSULT_DEEP_LINK = "consult"
#: FSM state name prefixes that belong to client-side dialogs.
CLIENT_STATE_PREFIXES = ("ClientFlow", "ClientChat", "ProfileEdit", "Quiz")


@router.message(CommandStart())
async def start(
    message: Message,
    command: CommandObject,
    session: AsyncSession,
    user: User,
    state: FSMContext,
) -> None:
    await state.clear()
    payload = (command.args or "").strip()

    if user.is_admin and not payload:
        await answer_html(message, texts.welcome_admin(user.full_name), reply_markup=admin_menu())
        return

    await answer_html(
        message,
        texts.welcome(user.full_name, get_settings().brand_name),
        reply_markup=client_menu(),
    )
    if user.category is None and not user.is_admin:
        await answer_html(message, texts.ASK_CATEGORY, reply_markup=client_kb.categories())
        if payload:
            await state.update_data(deep_link=payload)
        return
    await _open_deep_link(message, session, user, payload)


async def _open_deep_link(
    message: Message, session: AsyncSession, user: User, payload: str
) -> None:
    if payload.startswith(COURSE_DEEP_LINK):
        course_id = payload.removeprefix(COURSE_DEEP_LINK)
        if course_id.isdigit():
            await show_course_from_link(message, session, user, int(course_id))
    elif payload == CONSULT_DEEP_LINK:
        await answer_html(message, texts.CONSULTATION_INTRO, reply_markup=client_kb.topics())


@router.callback_query(CategoryCB.filter())
async def choose_category(
    callback: CallbackQuery,
    callback_data: CategoryCB,
    session: AsyncSession,
    user: User,
    state: FSMContext,
) -> None:
    try:
        category = ClientCategory(callback_data.value)
    except ValueError:
        await callback.answer(texts.STALE_CALLBACK, show_alert=True)
        return
    await ClientService(session).set_category(user, category)
    await callback.answer("Сохранено")
    if callback_data.edit:
        await edit_or_send(callback, texts.profile(user), reply_markup=client_kb.profile())
        return
    await edit_or_send(
        callback,
        f"Отлично! Вы: {texts.category_label(category)}.\n\nВыберите раздел в меню ниже 👇",
        reply_markup=client_kb.training_menu(),
    )
    data = await state.get_data()
    payload = str(data.get("deep_link", ""))
    await state.clear()
    if payload and isinstance(callback.message, Message):
        await _open_deep_link(callback.message, session, user, payload)


@router.message(Command("help"))
async def help_command(message: Message, user: User) -> None:
    if user.is_admin:
        await answer_html(message, texts.HELP_ADMIN, reply_markup=admin_menu())
    else:
        await answer_html(message, texts.HELP_CLIENT, reply_markup=client_menu())


@router.message(Command("client"))
async def client_mode(message: Message, state: FSMContext) -> None:
    """Admins can try the bot exactly as a client sees it."""
    await state.clear()
    await answer_html(
        message,
        "👁 Меню клиента. Вернуться в админ-панель: /admin",
        reply_markup=client_menu(),
    )


@router.message(Command("admin"))
async def admin_mode(message: Message, user: User, state: FSMContext) -> None:
    await state.clear()
    if not user.is_admin:
        await answer_html(message, texts.HELP_CLIENT, reply_markup=client_menu())
        return
    await answer_html(message, texts.welcome_admin(user.full_name), reply_markup=admin_menu())


@router.message(Command("cancel"))
@router.message(F.text == texts.BTN_CANCEL)
async def cancel_command(message: Message, state: FSMContext, user: User) -> None:
    current = await state.get_state()
    await state.clear()
    text = texts.CANCELLED if current else texts.NOTHING_TO_CANCEL
    await answer_html(
        message, text, reply_markup=menu_for(user, client_side=_is_client_state(current))
    )


@router.callback_query(FlowCB.filter(F.action == "cancel"))
async def cancel_button(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    current = await state.get_state()
    await state.clear()
    await callback.answer(texts.CANCELLED)
    await edit_or_send(callback, texts.CANCELLED)
    if _is_client_state(current) and isinstance(callback.message, Message):
        # The phone step swaps the reply keyboard — always put the menu back.
        await callback.message.answer(
            "Главное меню 👇", reply_markup=menu_for(user, client_side=True)
        )


@router.callback_query(NoopCB.filter())
async def noop(callback: CallbackQuery) -> None:
    """Page indicator button — acknowledge silently."""
    await callback.answer()


def _is_client_state(state_name: str | None) -> bool:
    return bool(state_name) and str(state_name).startswith(CLIENT_STATE_PREFIXES)
