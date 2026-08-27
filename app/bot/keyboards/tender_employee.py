"""Inline keyboards for the tender employee."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.bot import texts
from app.bot.callbacks import (
    ProcurementCB,
    ProcurementListCB,
    RequestCB,
    RequestListCB,
    UserCB,
    UserListCB,
    WizardCB,
)
from app.bot.keyboards.common import pagination_row
from app.models.enums import ProcurementStatus, PurchaseRequestStatus
from app.models.procurement import Procurement
from app.models.purchase_request import PurchaseRequest
from app.models.user import User
from app.repositories.base import Page
from app.repositories.procurements import ProcurementStats

STATUS_FILTERS: dict[str, tuple[str, tuple[ProcurementStatus, ...]]] = {
    "active": ("🟢 Активные", (ProcurementStatus.OPEN,)),
    "draft": ("📝 Черновики", (ProcurementStatus.DRAFT,)),
    "closed": ("🔒 Закрытые", (ProcurementStatus.CLOSED,)),
    "completed": ("✅ Завершенные", (ProcurementStatus.COMPLETED,)),
    "cancelled": ("❌ Отмененные", (ProcurementStatus.CANCELLED,)),
}


# --- creation wizard -------------------------------------------------------
def create_mode() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🧩 Пошагово", callback_data=WizardCB(action="mode_step").pack()
                ),
                InlineKeyboardButton(
                    text="⚡ Быстро текстом", callback_data=WizardCB(action="mode_quick").pack()
                ),
            ],
            [
                InlineKeyboardButton(
                    text="❌ Отмена", callback_data=WizardCB(action="cancel").pack()
                )
            ],
        ]
    )


def skip_or_cancel() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⏭ Пропустить", callback_data=WizardCB(action="skip").pack()
                ),
                InlineKeyboardButton(
                    text="❌ Отмена", callback_data=WizardCB(action="cancel").pack()
                ),
            ]
        ]
    )


def cancel_only() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="❌ Отмена", callback_data=WizardCB(action="cancel").pack()
                )
            ]
        ]
    )


def participants_picker(
    page: Page[User], selected: set[int], all_selected: bool
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for user in page.items:
        mark = "☑" if (all_selected or user.id in selected) else "☐"
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{mark} {user.full_name}",
                    callback_data=WizardCB(
                        action="toggle", value=str(user.id), page=page.page
                    ).pack(),
                )
            ]
        )
    pager = pagination_row(
        lambda target: WizardCB(action="ppage", page=target).pack(), page.page, page.pages
    )
    if pager:
        rows.append(pager)
    rows.append(
        [
            InlineKeyboardButton(
                text="✅ Выбрать всех",
                callback_data=WizardCB(action="select_all", page=page.page).pack(),
            ),
            InlineKeyboardButton(
                text="❌ Снять выбор",
                callback_data=WizardCB(action="select_none", page=page.page).pack(),
            ),
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(
                text="➡️ Продолжить", callback_data=WizardCB(action="participants_done").pack()
            )
        ]
    )
    rows.append(
        [InlineKeyboardButton(text="❌ Отмена", callback_data=WizardCB(action="cancel").pack())]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def wizard_preview() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Опубликовать", callback_data=WizardCB(action="publish").pack()
                )
            ],
            [
                InlineKeyboardButton(
                    text="✏️ Изменить", callback_data=WizardCB(action="edit").pack()
                ),
                InlineKeyboardButton(
                    text="❌ Отменить", callback_data=WizardCB(action="cancel").pack()
                ),
            ],
        ]
    )


def quick_preview() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Опубликовать", callback_data=WizardCB(action="publish").pack()
                )
            ],
            [
                InlineKeyboardButton(
                    text="👥 Выбрать закупщиков",
                    callback_data=WizardCB(action="choose_participants").pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text="✏️ Исправить", callback_data=WizardCB(action="edit").pack()
                ),
                InlineKeyboardButton(
                    text="❌ Отменить", callback_data=WizardCB(action="cancel").pack()
                ),
            ],
        ]
    )


def wizard_edit_fields() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✏️ Название", callback_data=WizardCB(action="edit_title").pack()
                ),
                InlineKeyboardButton(
                    text="✏️ Описание", callback_data=WizardCB(action="edit_description").pack()
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🗓 Срок", callback_data=WizardCB(action="edit_deadline").pack()
                ),
                InlineKeyboardButton(
                    text="👥 Участники",
                    callback_data=WizardCB(action="choose_participants").pack(),
                ),
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ К предпросмотру", callback_data=WizardCB(action="back").pack()
                )
            ],
        ]
    )


# --- procurement lists / cards --------------------------------------------
def procurement_filters(active: str) -> list[InlineKeyboardButton]:
    row: list[InlineKeyboardButton] = []
    for key, (label, _statuses) in STATUS_FILTERS.items():
        text = f"• {label}" if key == active else label
        row.append(
            InlineKeyboardButton(
                text=text, callback_data=ProcurementListCB(status=key, page=1).pack()
            )
        )
    return row


def procurement_list(
    page: Page[Procurement], stats: dict[int, ProcurementStats], status_filter: str
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for procurement in page.items:
        item_stats = stats.get(procurement.id)
        suffix = (
            f" · {item_stats.responded}/{item_stats.participants}" if item_stats else ""
        )
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{procurement.procurement_number} · {procurement.title[:28]}{suffix}",
                    callback_data=ProcurementCB(
                        action="open", procurement_id=procurement.id
                    ).pack(),
                )
            ]
        )
    pager = pagination_row(
        lambda target: ProcurementListCB(status=status_filter, page=target).pack(),
        page.page,
        page.pages,
    )
    if pager:
        rows.append(pager)
    filters = procurement_filters(status_filter)
    rows.append(filters[:3])
    rows.append(filters[3:])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def procurement_card(procurement: Procurement) -> InlineKeyboardMarkup:
    pid = procurement.id
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(
                text="📋 Заявки",
                callback_data=RequestListCB(scope="proc", procurement_id=pid, page=1).pack(),
            ),
            InlineKeyboardButton(
                text="👥 Участники",
                callback_data=ProcurementCB(action="participants", procurement_id=pid).pack(),
            ),
        ],
        [
            InlineKeyboardButton(
                text="📊 Сводный Excel",
                callback_data=ProcurementCB(action="excel", procurement_id=pid).pack(),
            )
        ],
    ]

    if procurement.status is ProcurementStatus.DRAFT:
        rows.append(
            [
                InlineKeyboardButton(
                    text="🚀 Опубликовать",
                    callback_data=ProcurementCB(action="publish", procurement_id=pid).pack(),
                )
            ]
        )
    if procurement.status in (ProcurementStatus.OPEN, ProcurementStatus.CLOSED):
        rows.append(
            [
                InlineKeyboardButton(
                    text="⏰ Продлить срок",
                    callback_data=ProcurementCB(action="extend", procurement_id=pid).pack(),
                ),
                InlineKeyboardButton(
                    text="🔔 Напомнить",
                    callback_data=ProcurementCB(action="remind", procurement_id=pid).pack(),
                ),
            ]
        )
    if procurement.status is ProcurementStatus.OPEN:
        rows.append(
            [
                InlineKeyboardButton(
                    text="🔒 Закрыть",
                    callback_data=ProcurementCB(action="close", procurement_id=pid).pack(),
                ),
                InlineKeyboardButton(
                    text="❌ Отменить",
                    callback_data=ProcurementCB(action="cancel", procurement_id=pid).pack(),
                ),
            ]
        )
    if procurement.status is ProcurementStatus.CLOSED:
        rows.append(
            [
                InlineKeyboardButton(
                    text="✅ Завершить",
                    callback_data=ProcurementCB(action="complete", procurement_id=pid).pack(),
                )
            ]
        )
    if procurement.status in (ProcurementStatus.DRAFT, ProcurementStatus.OPEN):
        rows.append(
            [
                InlineKeyboardButton(
                    text="✏️ Изменить",
                    callback_data=ProcurementCB(action="edit", procurement_id=pid).pack(),
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text="⬅️ К списку", callback_data=ProcurementListCB(status="active").pack()
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def procurement_edit_fields(procurement_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✏️ Название",
                    callback_data=ProcurementCB(
                        action="edit_title", procurement_id=procurement_id
                    ).pack(),
                ),
                InlineKeyboardButton(
                    text="✏️ Описание",
                    callback_data=ProcurementCB(
                        action="edit_description", procurement_id=procurement_id
                    ).pack(),
                ),
            ],
            [
                InlineKeyboardButton(
                    text="⏰ Срок",
                    callback_data=ProcurementCB(
                        action="extend", procurement_id=procurement_id
                    ).pack(),
                ),
                InlineKeyboardButton(
                    text="⬅️ Назад",
                    callback_data=ProcurementCB(
                        action="open", procurement_id=procurement_id
                    ).pack(),
                ),
            ],
        ]
    )


def participants_view(page: Page[User], procurement_id: int) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    pager = pagination_row(
        lambda target: ProcurementCB(
            action="participants", procurement_id=procurement_id, page=target
        ).pack(),
        page.page,
        page.pages,
    )
    if pager:
        rows.append(pager)
    rows.append(
        [
            InlineKeyboardButton(
                text="⬅️ К закупке",
                callback_data=ProcurementCB(action="open", procurement_id=procurement_id).pack(),
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def confirm_action(action: str, procurement_id: int, label: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=label,
                    callback_data=ProcurementCB(
                        action=f"{action}_yes", procurement_id=procurement_id
                    ).pack(),
                ),
                InlineKeyboardButton(
                    text="⬅️ Назад",
                    callback_data=ProcurementCB(
                        action="open", procurement_id=procurement_id
                    ).pack(),
                ),
            ]
        ]
    )


# --- request lists / cards -------------------------------------------------
def request_list(
    page: Page[PurchaseRequest], scope: str, procurement_id: int = 0
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for request in page.items:
        rows.append(
            [
                InlineKeyboardButton(
                    text=texts.request_list_row(
                        request,
                        request.procurement.procurement_number
                        if request.procurement is not None
                        else None,
                        request.purchaser.full_name,
                    ),
                    callback_data=RequestCB(action="open", request_id=request.id).pack(),
                )
            ]
        )
    pager = pagination_row(
        lambda target: RequestListCB(
            scope=scope, procurement_id=procurement_id, page=target
        ).pack(),
        page.page,
        page.pages,
    )
    if pager:
        rows.append(pager)
    if procurement_id:
        rows.append(
            [
                InlineKeyboardButton(
                    text="⬅️ К закупке",
                    callback_data=ProcurementCB(
                        action="open", procurement_id=procurement_id
                    ).pack(),
                )
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def request_card(request: PurchaseRequest) -> InlineKeyboardMarkup:
    rid = request.id
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(
                text="📥 Excel", callback_data=RequestCB(action="excel", request_id=rid).pack()
            )
        ]
    ]
    status_buttons = {
        PurchaseRequestStatus.VIEWED: "👀 Просмотрена",
        PurchaseRequestStatus.IN_PROGRESS: "🟡 В работу",
        PurchaseRequestStatus.COMPLETED: "✅ Завершить",
        PurchaseRequestStatus.REJECTED: "❌ Отклонить",
    }
    row: list[InlineKeyboardButton] = []
    for status, label in status_buttons.items():
        if status is request.status:
            continue
        row.append(
            InlineKeyboardButton(
                text=label,
                callback_data=RequestCB(
                    action="status", request_id=rid, value=str(status)
                ).pack(),
            )
        )
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    last_row = [
        InlineKeyboardButton(
            text="⬅️ К заявкам", callback_data=RequestListCB(scope="new").pack()
        )
    ]
    if request.procurement_id is not None:
        last_row.insert(
            0,
            InlineKeyboardButton(
                text="📦 К закупке",
                callback_data=ProcurementCB(
                    action="open", procurement_id=request.procurement_id
                ).pack(),
            ),
        )
    rows.append(last_row)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def new_request_notification(request_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📋 Открыть",
                    callback_data=RequestCB(action="open", request_id=request_id).pack(),
                ),
                InlineKeyboardButton(
                    text="📥 Excel",
                    callback_data=RequestCB(action="excel", request_id=request_id).pack(),
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🟡 В работу",
                    callback_data=RequestCB(
                        action="status",
                        request_id=request_id,
                        value=str(PurchaseRequestStatus.IN_PROGRESS),
                    ).pack(),
                ),
                InlineKeyboardButton(
                    text="✅ Завершить",
                    callback_data=RequestCB(
                        action="status",
                        request_id=request_id,
                        value=str(PurchaseRequestStatus.COMPLETED),
                    ).pack(),
                ),
            ],
            [
                InlineKeyboardButton(
                    text="❌ Отклонить",
                    callback_data=RequestCB(
                        action="status",
                        request_id=request_id,
                        value=str(PurchaseRequestStatus.REJECTED),
                    ).pack(),
                )
            ],
        ]
    )


# --- users -----------------------------------------------------------------
def users_list(page: Page[User], include_revoked: bool) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for user in page.items:
        if user.revoked_at is not None:
            mark = "❌"
        elif user.is_active:
            mark = "✅"
        else:
            mark = "🚫"
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{mark} {user.full_name}",
                    callback_data=UserCB(action="open", user_id=user.id, page=page.page).pack(),
                )
            ]
        )
    pager = pagination_row(
        lambda target: UserListCB(page=target, revoked=int(include_revoked)).pack(),
        page.page,
        page.pages,
    )
    if pager:
        rows.append(pager)
    rows.append(
        [
            InlineKeyboardButton(
                text="➕ Добавить закупщика", callback_data=UserCB(action="add").pack()
            )
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(
                text="🙈 Скрыть отозванных" if include_revoked else "👁 Показать отозванных",
                callback_data=UserListCB(page=1, revoked=int(not include_revoked)).pack(),
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def add_purchaser_mode() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔗 Пригласительная ссылка",
                    callback_data=UserCB(action="add_invite").pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text="🆔 По Telegram ID", callback_data=UserCB(action="add_id").pack()
                )
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ Назад", callback_data=UserListCB(page=1).pack()
                )
            ],
        ]
    )


def user_card(user: User, page: int) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(
                text="📋 Заявки",
                callback_data=UserCB(action="requests", user_id=user.id, page=1).pack(),
            )
        ]
    ]
    if user.revoked_at is None:
        if user.is_active:
            rows.append(
                [
                    InlineKeyboardButton(
                        text="🚫 Заблокировать",
                        callback_data=UserCB(
                            action="block", user_id=user.id, page=page
                        ).pack(),
                    )
                ]
            )
        else:
            rows.append(
                [
                    InlineKeyboardButton(
                        text="✅ Разблокировать",
                        callback_data=UserCB(
                            action="unblock", user_id=user.id, page=page
                        ).pack(),
                    )
                ]
            )
        rows.append(
            [
                InlineKeyboardButton(
                    text="❌ Отозвать доступ",
                    callback_data=UserCB(action="revoke", user_id=user.id, page=page).pack(),
                )
            ]
        )
    else:
        rows.append(
            [
                InlineKeyboardButton(
                    text="✅ Восстановить доступ",
                    callback_data=UserCB(action="unblock", user_id=user.id, page=page).pack(),
                )
            ]
        )
    rows.append(
        [InlineKeyboardButton(text="⬅️ К списку", callback_data=UserListCB(page=page).pack())]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def user_requests_list(page: Page[PurchaseRequest], user_id: int) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for request in page.items:
        rows.append(
            [
                InlineKeyboardButton(
                    text=texts.request_list_row(
                        request,
                        request.procurement.procurement_number
                        if request.procurement is not None
                        else None,
                        "",
                    ),
                    callback_data=RequestCB(action="open", request_id=request.id).pack(),
                )
            ]
        )
    pager = pagination_row(
        lambda target: UserCB(action="requests", user_id=user_id, page=target).pack(),
        page.page,
        page.pages,
    )
    if pager:
        rows.append(pager)
    rows.append(
        [
            InlineKeyboardButton(
                text="⬅️ К карточке",
                callback_data=UserCB(action="open", user_id=user_id, page=1).pack(),
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)
