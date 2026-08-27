"""Inline keyboards for purchasers."""

from __future__ import annotations

from collections.abc import Sequence

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.bot.callbacks import ItemCB, ProcurementCB, RequestCB, RequestListCB
from app.bot.keyboards.common import pagination_row
from app.models.enums import PurchaseRequestStatus
from app.models.procurement import Procurement
from app.models.purchase_request import PurchaseRequest
from app.models.purchase_request_item import PurchaseRequestItem
from app.repositories.base import Page

MAX_ITEM_BUTTONS = 20


def procurement_list(page: Page[Procurement], scope: str) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for procurement in page.items:
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{procurement.procurement_number} · {procurement.title[:32]}",
                    callback_data=ProcurementCB(
                        action="popen", procurement_id=procurement.id
                    ).pack(),
                )
            ]
        )
    pager = pagination_row(
        lambda target: ProcurementCB(
            action="plist" if scope == "open" else "phistory", page=target
        ).pack(),
        page.page,
        page.pages,
    )
    if pager:
        rows.append(pager)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def procurement_card(
    procurement: Procurement, request: PurchaseRequest | None, can_submit: bool
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if request is not None and request.status is not PurchaseRequestStatus.DRAFT:
        rows.append(
            [
                InlineKeyboardButton(
                    text="📋 Моя заявка",
                    callback_data=RequestCB(action="myopen", request_id=request.id).pack(),
                )
            ]
        )
    elif can_submit:
        rows.append(
            [
                InlineKeyboardButton(
                    text="➕ Подать заявку",
                    callback_data=ProcurementCB(
                        action="submit", procurement_id=procurement.id
                    ).pack(),
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text="⬅️ Назад", callback_data=ProcurementCB(action="plist", page=1).pack()
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def items_prompt() -> InlineKeyboardMarkup:
    """Shown together with the "send me the list" prompt."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📄 Шаблон Excel", callback_data=ItemCB(action="template").pack()
                )
            ],
            [
                InlineKeyboardButton(
                    text="❌ Отменить", callback_data=ItemCB(action="cancel").pack()
                )
            ],
        ]
    )


def draft_preview(has_errors: bool) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if not has_errors:
        rows.append(
            [
                InlineKeyboardButton(
                    text="✅ Отправить", callback_data=ItemCB(action="submit").pack()
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text="✏️ Редактировать", callback_data=ItemCB(action="edit_pick").pack()
            ),
            InlineKeyboardButton(
                text="➕ Добавить позицию", callback_data=ItemCB(action="add").pack()
            ),
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(
                text="🗑 Удалить позицию", callback_data=ItemCB(action="delete_pick").pack()
            ),
            InlineKeyboardButton(
                text="💬 Комментарий", callback_data=ItemCB(action="comment").pack()
            ),
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(
                text="🔄 Ввести список заново", callback_data=ItemCB(action="restart").pack()
            )
        ]
    )
    rows.append(
        [InlineKeyboardButton(text="❌ Отменить", callback_data=ItemCB(action="cancel").pack())]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def item_picker(count: int, action: str) -> InlineKeyboardMarkup:
    """Numbered buttons for choosing an item to edit or delete."""
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for index in range(1, min(count, MAX_ITEM_BUTTONS) + 1):
        row.append(
            InlineKeyboardButton(
                text=str(index), callback_data=ItemCB(action=action, index=index).pack()
            )
        )
        if len(row) == 5:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append(
        [InlineKeyboardButton(text="⬅️ Назад", callback_data=ItemCB(action="back").pack())]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def my_requests_list(page: Page[PurchaseRequest], scope: str) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for request in page.items:
        rows.append(
            [
                InlineKeyboardButton(
                    text=(
                        f"{request.public_number} · "
                        f"{request.procurement.procurement_number}"
                        if request.procurement is not None
                        else f"{request.public_number} · ✋ {(request.subject or '')[:24]}"
                    ),
                    callback_data=RequestCB(action="myopen", request_id=request.id).pack(),
                )
            ]
        )
    pager = pagination_row(
        lambda target: RequestListCB(scope=scope, page=target).pack(), page.page, page.pages
    )
    if pager:
        rows.append(pager)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def my_request_card(request: PurchaseRequest, items: Sequence[PurchaseRequestItem]) -> (
    InlineKeyboardMarkup
):
    rows: list[list[InlineKeyboardButton]] = []
    if items:
        rows.append(
            [
                InlineKeyboardButton(
                    text="📥 Excel",
                    callback_data=RequestCB(action="excel", request_id=request.id).pack(),
                )
            ]
        )
    last_row = [
        InlineKeyboardButton(
            text="⬅️ Мои заявки", callback_data=RequestListCB(scope="mine", page=1).pack()
        )
    ]
    if request.procurement_id is not None:
        last_row.insert(
            0,
            InlineKeyboardButton(
                text="📦 Закупка",
                callback_data=ProcurementCB(
                    action="popen", procurement_id=request.procurement_id
                ).pack(),
            ),
        )
    rows.append(last_row)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def new_procurement_notification(procurement_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📋 Открыть",
                    callback_data=ProcurementCB(
                        action="popen", procurement_id=procurement_id
                    ).pack(),
                ),
                InlineKeyboardButton(
                    text="➕ Подать заявку",
                    callback_data=ProcurementCB(
                        action="submit", procurement_id=procurement_id
                    ).pack(),
                ),
            ]
        ]
    )
