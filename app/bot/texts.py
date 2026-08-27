"""All user-facing Russian text in one place.

Pure presentation: no I/O, no aiogram imports, so it can be unit-tested and
reused by the notification service. Messages use Telegram HTML parse mode, so
every dynamic value goes through :func:`escape_html`.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from decimal import Decimal
from typing import Protocol
from zoneinfo import ZoneInfo

from app.domain.text import escape_html, format_quantity, truncate
from app.domain.timeutils import format_datetime, format_human, format_timedelta_left
from app.models.enums import (
    PROCUREMENT_STATUS_ICONS,
    PROCUREMENT_STATUS_LABELS,
    REQUEST_STATUS_ICONS,
    REQUEST_STATUS_LABELS,
    ProcurementStatus,
    PurchaseRequestStatus,
)
from app.models.procurement import Procurement
from app.models.purchase_request import PurchaseRequest
from app.models.purchase_request_item import PurchaseRequestItem
from app.models.user import User
from app.parsers.base import ParseError
from app.repositories.procurements import ProcurementStats

# --- reply keyboard captions ------------------------------------------------
BTN_NEW_REQUESTS = "📥 Новые заявки"
BTN_PROCUREMENTS = "📦 Закупки"
BTN_CREATE_PROCUREMENT = "➕ Создать закупку"
BTN_PURCHASERS = "👥 Закупщики"
BTN_STATISTICS = "📊 Статистика"
BTN_SETTINGS = "⚙️ Настройки"

BTN_ACTIVE_PROCUREMENTS = "📢 Активные закупки"
BTN_CREATE_REQUEST = "➕ Создать заявку"
BTN_MY_REQUESTS = "📋 Мои заявки"
BTN_HISTORY = "🕘 История"
BTN_HELP = "ℹ️ Помощь"

# --- generic ---------------------------------------------------------------
NO_ACCESS = (
    "У вас нет доступа к системе.\n\n"
    "Обратитесь к сотруднику тендерного отдела."
)
ACCESS_BLOCKED = (
    "Ваш доступ к системе приостановлен.\n\n"
    "Обратитесь к сотруднику тендерного отдела."
)
CANCELLED = "Действие отменено."
NOTHING_TO_CANCEL = "Сейчас нечего отменять."
STALE_CALLBACK = "Это сообщение устарело. Откройте раздел заново."
GENERIC_ERROR = "Произошла ошибка. Попробуйте еще раз или начните заново: /start"
RATE_LIMITED = "Слишком много действий подряд. Подождите несколько секунд."
DEADLINE_EXPIRED = "Срок подачи заявок по этой закупке уже истек."
EMPTY_LIST = "Пока пусто."


def welcome_employee(name: str) -> str:
    return (
        f"👋 Здравствуйте, {escape_html(name)}!\n\n"
        "Вы вошли как <b>сотрудник тендерного отдела</b>.\n"
        "Выберите действие в меню ниже."
    )


def welcome_purchaser(name: str) -> str:
    return (
        f"👋 Здравствуйте, {escape_html(name)}!\n\n"
        "Вы вошли как <b>закупщик</b>.\n"
        "Здесь вы получаете закупки и подаете заявки."
    )


HELP_EMPLOYEE = (
    "<b>Возможности</b>\n\n"
    f"{BTN_CREATE_PROCUREMENT} — пошагово или одним сообщением.\n"
    f"{BTN_PROCUREMENTS} — список закупок, участники, сводный Excel.\n"
    f"{BTN_NEW_REQUESTS} — входящие заявки закупщиков.\n"
    f"{BTN_PURCHASERS} — добавление, блокировка, отзыв доступа.\n"
    f"{BTN_STATISTICS} — сводные показатели.\n\n"
    "Команды: /start, /help, /cancel"
)

HELP_PURCHASER = (
    "<b>Как подать заявку</b>\n\n"
    "<b>Вариант 1 — по объявленной закупке</b>\n"
    f"1. Откройте {BTN_ACTIVE_PROCUREMENTS}.\n"
    "2. Выберите нужную закупку.\n"
    "3. Нажмите «➕ Подать заявку».\n\n"
    "<b>Вариант 2 — своя заявка</b>\n"
    f"Нажмите {BTN_CREATE_REQUEST}, укажите тему — заявка уйдет сотруднику "
    "тендерного отдела на подтверждение.\n\n"
    "<b>Дальше одинаково</b>\n"
    "Отправьте список товаров одним сообщением, например:\n\n"
    "<code>1. Сахар — 50 кг\n2. Масло — 60 л\n3. Мука — 100 кг</code>\n\n"
    "Проверьте заявку и нажмите «✅ Отправить».\n\n"
    "Команды: /start, /help, /cancel"
)


# --- procurement -----------------------------------------------------------
def procurement_status_line(status: ProcurementStatus) -> str:
    return f"{PROCUREMENT_STATUS_ICONS[status]} {PROCUREMENT_STATUS_LABELS[status]}"


def procurement_list_row(procurement: Procurement, stats: ProcurementStats) -> str:
    return (
        f"{PROCUREMENT_STATUS_ICONS[procurement.status]} "
        f"{procurement.procurement_number} · {truncate(procurement.title, 40)} · "
        f"{stats.responded}/{stats.participants}"
    )


def procurement_card_employee(
    procurement: Procurement, stats: ProcurementStats, tz: ZoneInfo, now: dt.datetime
) -> str:
    lines = [
        f"📦 <b>{escape_html(procurement.procurement_number)}</b>",
        "",
        escape_html(procurement.title),
    ]
    if procurement.description:
        lines += ["", escape_html(truncate(procurement.description, 700))]
    lines += [
        "",
        f"Статус: {procurement_status_line(procurement.status)}",
        f"Срок: {format_datetime(procurement.deadline, tz)}",
    ]
    if procurement.status is ProcurementStatus.OPEN:
        lines.append(f"({format_timedelta_left(procurement.deadline, now)})")
    lines += [
        "",
        f"Участников: {stats.participants}",
        f"Подали заявки: {stats.responded} / {stats.participants}",
        f"Не подали: {stats.pending}",
        f"Процент ответов: {stats.response_rate}%",
        f"Всего позиций: {stats.total_items}",
    ]
    return "\n".join(lines)


def procurement_card_purchaser(
    procurement: Procurement,
    tz: ZoneInfo,
    request: PurchaseRequest | None,
    now: dt.datetime,
) -> str:
    lines = [
        f"📦 <b>{escape_html(procurement.procurement_number)}</b>",
        "",
        escape_html(procurement.title),
    ]
    if procurement.description:
        lines += ["", "Описание:", escape_html(truncate(procurement.description, 700))]
    lines += [
        "",
        "Срок подачи:",
        format_human(procurement.deadline, tz),
    ]
    if procurement.status is ProcurementStatus.OPEN:
        lines.append(f"({format_timedelta_left(procurement.deadline, now)})")
    lines += ["", "Ваш статус:"]
    if request is None or request.status is PurchaseRequestStatus.DRAFT:
        lines.append("Заявка еще не подана")
    else:
        lines.append(
            f"{REQUEST_STATUS_ICONS[request.status]} "
            f"{escape_html(request.public_number)} — "
            f"{REQUEST_STATUS_LABELS[request.status]}"
        )
    return "\n".join(lines)


def procurement_preview(
    number: str,
    title: str,
    description: str | None,
    deadline: dt.datetime,
    tz: ZoneInfo,
    participants_label: str,
    deadline_time_assumed: bool,
) -> str:
    lines = [
        "📦 <b>Проверьте закупку</b>",
        "",
        f"№ {escape_html(number)}",
        "",
        "Название:",
        escape_html(title),
        "",
        "Описание:",
        escape_html(description) if description else "—",
        "",
        "Срок:",
        format_datetime(deadline, tz),
    ]
    if deadline_time_assumed:
        lines.append("<i>Время не указано — подставлено значение по умолчанию.</i>")
    lines += ["", "Получатели:", escape_html(participants_label)]
    return "\n".join(lines)


def new_procurement_notification(procurement: Procurement, tz: ZoneInfo) -> str:
    lines = [
        "📢 <b>Новая закупка</b>",
        "",
        f"№ {escape_html(procurement.procurement_number)}",
        "",
        escape_html(procurement.title),
    ]
    if procurement.description:
        lines += ["", escape_html(truncate(procurement.description, 500))]
    lines += ["", "Срок подачи:", format_datetime(procurement.deadline, tz)]
    return "\n".join(lines)


def reminder_notification(procurement: Procurement, tz: ZoneInfo) -> str:
    return (
        "🔔 <b>Напоминание</b>\n\n"
        f"По закупке № {escape_html(procurement.procurement_number)} "
        "от вас еще не получена заявка.\n\n"
        f"{escape_html(procurement.title)}\n\n"
        f"Срок подачи: {format_datetime(procurement.deadline, tz)}"
    )


# --- purchase requests -----------------------------------------------------
def format_item_line(position: int, name: str, quantity: str, unit: str) -> str:
    return f"{position}. {escape_html(name)} — {quantity} {escape_html(unit)}"


class RenderableItem(Protocol):
    """Anything with a name, an exact quantity and a unit.

    Lets one renderer serve both parsed (not yet stored) and persisted items.
    """

    @property
    def name(self) -> str: ...

    @property
    def quantity(self) -> Decimal: ...

    @property
    def unit(self) -> str: ...


def render_items(items: Sequence[RenderableItem], limit: int) -> tuple[str, int]:
    """Render up to ``limit`` items; returns ``(text, hidden_count)``."""
    lines: list[str] = []
    for index, item in enumerate(items[:limit], start=1):
        position = getattr(item, "position", index)
        lines.append(
            format_item_line(position, item.name, format_quantity(item.quantity), item.unit)
        )
    hidden = max(0, len(items) - limit)
    return "\n".join(lines), hidden


def request_source_lines(
    procurement: Procurement | None, subject: str | None
) -> list[str]:
    """Header block describing what a request is about.

    A request either belongs to a procurement or is self-initiated, in which
    case the purchaser's own subject is shown instead.
    """
    if procurement is not None:
        return [
            "Закупка:",
            f"{escape_html(procurement.procurement_number)} — {escape_html(procurement.title)}",
        ]
    return [
        "Тема (заявка по инициативе закупщика):",
        escape_html(subject or "—"),
    ]


def request_preview(
    procurement: Procurement | None,
    items: Sequence[RenderableItem],
    comment: str | None,
    limit: int,
    subject: str | None = None,
) -> str:
    body, hidden = render_items(items, limit)
    lines = [
        "📋 <b>Заявка</b>",
        "",
        *request_source_lines(procurement, subject),
        "",
        body or "—",
    ]
    if hidden:
        lines.append(f"<i>… и еще {hidden} позиц. (всего {len(items)})</i>")
    lines += ["", f"Позиций: {len(items)}"]
    if comment:
        lines += ["", f"💬 {escape_html(truncate(comment, 500))}"]
    return "\n".join(lines)


def parse_problems(errors: Sequence[ParseError], limit: int = 10) -> str:
    if not errors:
        return ""
    lines = ["⚠️ <b>Не удалось точно распознать:</b>", ""]
    for error in errors[:limit]:
        line = escape_html(truncate(error.line, 120)) or "(пустая строка)"
        lines.append(f"• «{line}» — {escape_html(error.reason)}")
    if len(errors) > limit:
        lines.append(f"… и еще {len(errors) - limit}")
    lines += ["", "Исправьте эти позиции вручную или удалите их."]
    return "\n".join(lines)


def request_card(
    request: PurchaseRequest,
    procurement: Procurement | None,
    purchaser: User,
    items: Sequence[PurchaseRequestItem],
    tz: ZoneInfo,
    limit: int,
    for_employee: bool,
) -> str:
    body, hidden = render_items(items, limit)
    when = request.submitted_at or request.created_at
    lines = [
        f"{REQUEST_STATUS_ICONS[request.status]} <b>{escape_html(request.public_number)}</b>",
        "",
        *request_source_lines(procurement, request.subject),
    ]
    if for_employee:
        lines += ["", "Закупщик:", escape_html(purchaser.display_name)]
    lines += [
        "",
        f"Статус: {REQUEST_STATUS_LABELS[request.status]}",
        f"Дата: {format_datetime(when, tz)}",
        "",
        f"Позиций: {len(items)}",
        "",
        body or "—",
    ]
    if hidden:
        lines.append(f"<i>… и еще {hidden} позиц. Полный список — в Excel.</i>")
    if request.comment:
        lines += ["", f"💬 {escape_html(truncate(request.comment, 500))}"]
    if request.rejection_reason:
        lines += ["", f"❌ Причина отклонения: {escape_html(request.rejection_reason)}"]
    return "\n".join(lines)


def new_request_notification(
    request: PurchaseRequest,
    procurement: Procurement | None,
    purchaser: User,
    items: Sequence[PurchaseRequestItem],
    tz: ZoneInfo,
    limit: int,
) -> str:
    body, hidden = render_items(items, limit)
    when = request.submitted_at or request.created_at
    header = "📥 <b>Новая заявка</b>" if procurement is not None else (
        "📥 <b>Новая заявка от закупщика</b>"
    )
    lines = [
        header,
        "",
        f"№ {escape_html(request.public_number)}",
        "",
        *request_source_lines(procurement, request.subject),
        "",
        "Закупщик:",
        escape_html(purchaser.full_name),
        "",
        "Дата:",
        format_datetime(when, tz),
        "",
        f"Позиций: {len(items)}",
        "",
        body,
    ]
    if hidden:
        lines.append(f"<i>… и еще {hidden} позиц. Полный список — в Excel.</i>")
    if request.comment:
        lines += ["", f"💬 {escape_html(truncate(request.comment, 300))}"]
    return "\n".join(lines)


def request_status_notification(
    request: PurchaseRequest, new_status: PurchaseRequestStatus, reason: str | None
) -> str:
    number = escape_html(request.public_number)
    if new_status is PurchaseRequestStatus.REJECTED:
        text = f"❌ Заявка {number} отклонена."
        if reason:
            text += f"\n\nПричина:\n{escape_html(reason)}"
        return text
    if new_status is PurchaseRequestStatus.COMPLETED:
        return f"✅ Заявка {number} завершена."
    return (
        f"🔄 Статус заявки {number} изменен.\n\n"
        f"Новый статус:\n{REQUEST_STATUS_LABELS[new_status]}"
    )


def request_list_row(request: PurchaseRequest, procurement_number: str | None, who: str) -> str:
    source = procurement_number or f"✋ {truncate(request.subject or 'без темы', 20)}"
    return (
        f"{REQUEST_STATUS_ICONS[request.status]} {request.public_number} · "
        f"{source} · {truncate(who, 24)}"
    )


# --- users -----------------------------------------------------------------
def purchaser_card(user: User, requests_count: int, tz: ZoneInfo) -> str:
    if user.revoked_at is not None:
        status = "❌ Доступ отозван"
    elif user.is_active:
        status = "✅ Активен"
    else:
        status = "🚫 Заблокирован"
    username = f"@{escape_html(user.telegram_username)}" if user.telegram_username else "—"
    return (
        f"👤 <b>{escape_html(user.full_name)}</b>\n\n"
        f"{username}\n"
        f"Telegram ID: <code>{user.telegram_id}</code>\n\n"
        f"Статус: {status}\n"
        f"Добавлен: {format_datetime(user.created_at, tz)}\n"
        f"Заявок: {requests_count}"
    )


def invite_created(code: str, full_name: str, bot_username: str | None, hours: int) -> str:
    link = f"https://t.me/{bot_username}?start={code}" if bot_username else None
    lines = [
        "✅ <b>Приглашение создано</b>",
        "",
        f"Для: {escape_html(full_name)}",
        f"Действует: {hours} ч.",
        "",
        "Отправьте закупщику эту ссылку:",
    ]
    if link:
        lines.append(f"<code>{escape_html(link)}</code>")
    else:
        lines += [
            "Ссылка недоступна (не удалось определить username бота).",
            f"Код приглашения: <code>{escape_html(code)}</code>",
        ]
    lines += ["", "Ссылка одноразовая — после первого использования она перестанет работать."]
    return "\n".join(lines)


# --- statistics ------------------------------------------------------------
def statistics_text(
    open_procurements: int,
    procurements_this_month: int,
    active_purchasers: int,
    requests_today: int,
    requests_this_week: int,
    new_requests: int,
    in_progress_requests: int,
    completed_requests: int,
) -> str:
    return (
        "📊 <b>Статистика</b>\n\n"
        f"Активных закупок: {open_procurements}\n"
        f"Закупок за месяц: {procurements_this_month}\n"
        f"Активных закупщиков: {active_purchasers}\n\n"
        f"Заявок сегодня: {requests_today}\n"
        f"Заявок за неделю: {requests_this_week}\n\n"
        f"Новых заявок: {new_requests}\n"
        f"В работе: {in_progress_requests}\n"
        f"Завершенных: {completed_requests}"
    )


def procurement_stats_text(stats: ProcurementStats) -> str:
    return (
        f"Участников: {stats.participants}\n"
        f"Подали: {stats.responded}\n"
        f"Не подали: {stats.pending}\n"
        f"Процент ответов: {stats.response_rate}%\n"
        f"Всего позиций: {stats.total_items}"
    )


def settings_text(timezone_name: str, default_time: str, page_size: int) -> str:
    return (
        "⚙️ <b>Настройки</b>\n\n"
        f"Часовой пояс: <code>{escape_html(timezone_name)}</code>\n"
        f"Время дедлайна по умолчанию: <code>{escape_html(default_time)}</code>\n"
        f"Размер страницы списков: {page_size}\n\n"
        "<i>Значения задаются переменными окружения "
        "(APP_TIMEZONE, DEFAULT_DEADLINE_TIME, PAGE_SIZE).</i>"
    )
