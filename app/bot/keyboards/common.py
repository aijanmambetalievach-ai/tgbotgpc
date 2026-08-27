"""Shared keyboard builders."""

from __future__ import annotations

from collections.abc import Callable

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)

from app.bot import texts
from app.bot.callbacks import NoopCB
from app.models.enums import UserRole


def main_menu(role: UserRole) -> ReplyKeyboardMarkup:
    """Persistent reply keyboard — users never have to remember commands."""
    if role in (UserRole.TENDER_EMPLOYEE, UserRole.ADMIN):
        rows = [
            [
                KeyboardButton(text=texts.BTN_NEW_REQUESTS),
                KeyboardButton(text=texts.BTN_PROCUREMENTS),
            ],
            [KeyboardButton(text=texts.BTN_CREATE_PROCUREMENT)],
            [KeyboardButton(text=texts.BTN_PURCHASERS), KeyboardButton(text=texts.BTN_STATISTICS)],
            [KeyboardButton(text=texts.BTN_SETTINGS)],
        ]
    else:
        rows = [
            [KeyboardButton(text=texts.BTN_ACTIVE_PROCUREMENTS)],
            [KeyboardButton(text=texts.BTN_CREATE_REQUEST)],
            [KeyboardButton(text=texts.BTN_MY_REQUESTS), KeyboardButton(text=texts.BTN_HISTORY)],
            [KeyboardButton(text=texts.BTN_HELP)],
        ]
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def remove_keyboard() -> ReplyKeyboardRemove:
    return ReplyKeyboardRemove()


def pagination_row(
    build: Callable[[int], str], current_page: int, total_pages: int
) -> list[InlineKeyboardButton]:
    """``‹ Назад | 2/7 | Вперед ›`` — only rendered when there is more than one page."""
    if total_pages <= 1:
        return []
    buttons: list[InlineKeyboardButton] = []
    if current_page > 1:
        buttons.append(InlineKeyboardButton(text="‹", callback_data=build(current_page - 1)))
    buttons.append(
        InlineKeyboardButton(
            text=f"{current_page}/{total_pages}", callback_data=NoopCB(tag="page").pack()
        )
    )
    if current_page < total_pages:
        buttons.append(InlineKeyboardButton(text="›", callback_data=build(current_page + 1)))
    return buttons


def single_button(text: str, callback_data: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=text, callback_data=callback_data)]]
    )


def confirm_cancel(
    confirm_text: str, confirm_data: str, cancel_text: str, cancel_data: str
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=confirm_text, callback_data=confirm_data),
                InlineKeyboardButton(text=cancel_text, callback_data=cancel_data),
            ]
        ]
    )
