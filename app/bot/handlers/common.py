"""Commands available to everyone: /start, /help, /cancel."""

from __future__ import annotations

import logging

from aiogram import Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.bot.callbacks import NoopCB
from app.bot.handlers.helpers import answer_html
from app.bot.keyboards.common import main_menu
from app.domain.exceptions import InviteError
from app.models.user import User
from app.services.auth_service import AuthService

logger = logging.getLogger(__name__)

router = Router(name="common")


@router.message(CommandStart(deep_link=True))
async def start_with_payload(
    message: Message,
    command: CommandObject,
    session: AsyncSession,
    user: User | None,
    state: FSMContext,
) -> None:
    """``/start <invite-code>`` — redeem an invitation."""
    await state.clear()
    payload = (command.args or "").strip()

    if user is not None:
        await _greet(message, user)
        return

    if not payload:
        await answer_html(message, texts.NO_ACCESS)
        return

    auth = AuthService(session)
    try:
        joined = await auth.accept_invite(
            code=payload,
            telegram_id=message.from_user.id if message.from_user else 0,
            telegram_username=message.from_user.username if message.from_user else None,
            telegram_full_name=message.from_user.full_name if message.from_user else None,
        )
    except InviteError as exc:
        await answer_html(message, f"⚠️ {exc.message}\n\n{texts.NO_ACCESS}")
        return

    await _greet(message, joined)


@router.message(CommandStart())
async def start(message: Message, user: User | None, state: FSMContext) -> None:
    await state.clear()
    if user is None:
        await answer_html(message, texts.NO_ACCESS)
        return
    await _greet(message, user)


@router.message(Command("help"))
async def help_command(message: Message, user: User | None) -> None:
    if user is None:
        await answer_html(message, texts.NO_ACCESS)
        return
    text = texts.HELP_EMPLOYEE if user.is_employee else texts.HELP_PURCHASER
    await answer_html(message, text, reply_markup=main_menu(user.role))


@router.message(Command("cancel"))
async def cancel_command(message: Message, state: FSMContext, user: User | None) -> None:
    current = await state.get_state()
    await state.clear()
    if user is None:
        await answer_html(message, texts.NO_ACCESS)
        return
    text = texts.CANCELLED if current else texts.NOTHING_TO_CANCEL
    await answer_html(message, text, reply_markup=main_menu(user.role))


@router.callback_query(NoopCB.filter())
async def noop(callback: CallbackQuery) -> None:
    """Page indicator button — acknowledge silently."""
    await callback.answer()


async def _greet(message: Message, user: User) -> None:
    text = (
        texts.welcome_employee(user.full_name)
        if user.is_employee
        else texts.welcome_purchaser(user.full_name)
    )
    await answer_html(message, text, reply_markup=main_menu(user.role))
    logger.info(
        "session started",
        extra={
            "operation": "start",
            "telegram_user_id": user.telegram_id,
            "user_id": user.id,
            "result": str(user.role),
        },
    )
