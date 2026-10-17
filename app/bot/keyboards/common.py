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
from app.bot.callbacks import FlowCB, NoopCB


def client_menu() -> ReplyKeyboardMarkup:
    """Persistent reply keyboard — clients never have to remember commands."""
    rows = [
        [KeyboardButton(text=texts.BTN_TRAINING), KeyboardButton(text=texts.BTN_CONSULTATION)],
        [KeyboardButton(text=texts.BTN_MY_APPLICATIONS), KeyboardButton(text=texts.BTN_FAQ)],
        [KeyboardButton(text=texts.BTN_ABOUT), KeyboardButton(text=texts.BTN_PROFILE)],
    ]
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def admin_menu() -> ReplyKeyboardMarkup:
    rows = [
        [
            KeyboardButton(text=texts.BTN_ADMIN_APPLICATIONS),
            KeyboardButton(text=texts.BTN_ADMIN_STATS),
        ],
        [
            KeyboardButton(text=texts.BTN_ADMIN_COURSES),
            KeyboardButton(text=texts.BTN_ADMIN_LESSONS),
        ],
        [KeyboardButton(text=texts.BTN_ADMIN_FAQ), KeyboardButton(text=texts.BTN_ADMIN_CLIENTS)],
        [
            KeyboardButton(text=texts.BTN_ADMIN_BROADCAST),
            KeyboardButton(text=texts.BTN_ADMIN_SETTINGS),
        ],
    ]
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def share_phone() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=texts.BTN_SHARE_PHONE, request_contact=True)],
            [KeyboardButton(text=texts.BTN_CANCEL)],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def remove_keyboard() -> ReplyKeyboardRemove:
    return ReplyKeyboardRemove()


def pagination_row(
    build: Callable[[int], str], current_page: int, total_pages: int
) -> list[InlineKeyboardButton]:
    """``‹ | 2/7 | ›`` — only rendered when there is more than one page."""
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


def button(text: str, callback_data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=callback_data)


def single_button(text: str, callback_data: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[button(text, callback_data)]])


def confirm_cancel(
    confirm_text: str, confirm_data: str, cancel_text: str, cancel_data: str
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[button(confirm_text, confirm_data), button(cancel_text, cancel_data)]]
    )


def flow_cancel() -> InlineKeyboardMarkup:
    return single_button(texts.BTN_CANCEL, FlowCB(action="cancel").pack())


def flow_skip_cancel() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                button("⏭ Пропустить", FlowCB(action="skip").pack()),
                button(texts.BTN_CANCEL, FlowCB(action="cancel").pack()),
            ]
        ]
    )


def flow_choices(
    choices: list[tuple[str, str]], action: str, columns: int = 1, cancel: bool = True
) -> InlineKeyboardMarkup:
    """One button per ``(value, label)``; all carry the same ``action``."""
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for value, label in choices:
        row.append(button(label, FlowCB(action=action, value=value).pack()))
        if len(row) == columns:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    if cancel:
        rows.append([button(texts.BTN_CANCEL, FlowCB(action="cancel").pack())])
    return InlineKeyboardMarkup(inline_keyboard=rows)
