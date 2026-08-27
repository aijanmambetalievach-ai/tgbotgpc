"""Purchaser flows: browse procurements, compose and submit a request."""

from __future__ import annotations

import logging
from decimal import Decimal
from io import BytesIO
from typing import Any

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import texts
from app.bot.callbacks import ItemCB, ProcurementCB, RequestCB, RequestListCB
from app.bot.filters import PurchaserFilter
from app.bot.handlers.helpers import answer_html, edit_or_send, notify_stale
from app.bot.keyboards import purchaser as kb
from app.bot.keyboards.common import main_menu
from app.bot.states.purchase_request import RequestCreation
from app.config.settings import get_settings
from app.domain.exceptions import ValidationError
from app.domain.text import escape_html
from app.domain.timeutils import utcnow
from app.models.enums import ProcurementStatus, PurchaseRequestStatus
from app.models.user import User
from app.parsers.base import ParsedItem, ParseError, ParseResult
from app.parsers.excel_list_parser import ExcelPurchaseListParser
from app.parsers.purchase_list_parser import RegexPurchaseListParser
from app.repositories.users import UserRepository
from app.services.excel_export_service import ExcelExportService, build_items_template
from app.services.notification_service import NotificationService
from app.services.procurement_service import ProcurementService
from app.services.purchase_request_service import PurchaseRequestService, SubmitResult

logger = logging.getLogger(__name__)

router = Router(name="purchaser")
router.message.filter(PurchaserFilter)
router.callback_query.filter(PurchaserFilter)

ACTIVE_STATUSES = (
    PurchaseRequestStatus.SUBMITTED,
    PurchaseRequestStatus.VIEWED,
    PurchaseRequestStatus.IN_PROGRESS,
)
HISTORY_STATUSES = (
    PurchaseRequestStatus.COMPLETED,
    PurchaseRequestStatus.REJECTED,
    PurchaseRequestStatus.CANCELLED,
)

ITEMS_PROMPT = (
    "Отправьте список товаров одним сообщением.\n\n"
    "Пример:\n"
    "<code>1. Сахар — 50 кг\n"
    "2. Масло — 60 л\n"
    "3. Мука — 100 кг\n"
    "4. Яйца — 200 шт</code>\n\n"
    "Можно писать свободно: <code>Сахар 50кг</code>, <code>масло кол 60 литров</code>.\n\n"
    "📎 Либо просто пришлите файл <b>Excel (.xlsx)</b> со списком — "
    "колонки «Наименование», «Количество», «Ед. измерения»."
)

EXCEL_EXTENSIONS = (".xlsx", ".xlsm")


def _parser() -> RegexPurchaseListParser:
    settings = get_settings()
    return RegexPurchaseListParser(
        max_items=settings.max_items_per_request,
        max_name_length=settings.max_item_name_length,
    )


def _excel_parser() -> ExcelPurchaseListParser:
    settings = get_settings()
    return ExcelPurchaseListParser(
        max_items=settings.max_items_per_request,
        max_name_length=settings.max_item_name_length,
        max_rows=settings.max_upload_rows,
    )


# --- FSM payload helpers ----------------------------------------------------
def _dump_items(items: list[ParsedItem]) -> list[dict[str, Any]]:
    return [
        {
            "name": item.name,
            "quantity": str(item.quantity),
            "unit": item.unit,
            "source_text": item.source_text,
            "confidence": item.confidence,
        }
        for item in items
    ]


def _load_items(raw: list[dict[str, Any]] | None) -> list[ParsedItem]:
    return [
        ParsedItem(
            name=entry["name"],
            quantity=Decimal(entry["quantity"]),
            unit=entry["unit"],
            source_text=entry.get("source_text", ""),
            confidence=entry.get("confidence"),
        )
        for entry in (raw or [])
    ]


def _dump_errors(errors: list[ParseError]) -> list[dict[str, str]]:
    return [{"line": error.line, "reason": error.reason} for error in errors]


def _load_errors(raw: list[dict[str, str]] | None) -> list[ParseError]:
    return [ParseError(line=entry["line"], reason=entry["reason"]) for entry in (raw or [])]


# --- menu -------------------------------------------------------------------
@router.message(F.text == texts.BTN_ACTIVE_PROCUREMENTS)
async def show_active_procurements(
    message: Message, session: AsyncSession, user: User, state: FSMContext
) -> None:
    await state.clear()
    await _render_procurement_list(message, session, user, page=1, only_open=True)


@router.message(F.text == texts.BTN_HISTORY)
async def show_history(
    message: Message, session: AsyncSession, user: User, state: FSMContext
) -> None:
    await state.clear()
    service = PurchaseRequestService(session)
    page = await service.list_own(user, page=1, statuses=HISTORY_STATUSES)
    if page.is_empty:
        await answer_html(message, "🕘 История пуста.")
        return
    await answer_html(
        message,
        f"🕘 <b>История заявок</b>\nВсего: {page.total}",
        reply_markup=kb.my_requests_list(page, scope="history"),
    )


@router.message(F.text == texts.BTN_MY_REQUESTS)
async def show_my_requests(
    message: Message, session: AsyncSession, user: User, state: FSMContext
) -> None:
    await state.clear()
    service = PurchaseRequestService(session)
    page = await service.list_own(user, page=1, statuses=ACTIVE_STATUSES)
    if page.is_empty:
        await answer_html(message, "📋 Активных заявок нет.")
        return
    await answer_html(
        message,
        f"📋 <b>Мои заявки</b>\nВсего: {page.total}",
        reply_markup=kb.my_requests_list(page, scope="mine"),
    )


@router.message(F.text == texts.BTN_HELP)
async def show_help(message: Message, user: User, state: FSMContext) -> None:
    await state.clear()
    await answer_html(message, texts.HELP_PURCHASER, reply_markup=main_menu(user.role))


# --- self-initiated request -------------------------------------------------
@router.message(F.text == texts.BTN_CREATE_REQUEST)
async def start_self_initiated_request(message: Message, state: FSMContext) -> None:
    """A request the purchaser raises on their own, without a procurement."""
    await state.clear()
    await state.set_state(RequestCreation.subject)
    await answer_html(
        message,
        "📝 <b>Новая заявка</b>\n\n"
        "Напишите одной строкой, что нужно закупить — эту тему увидит сотрудник "
        "тендерного отдела.\n\n"
        "<i>Например: Канцелярия для бухгалтерии на сентябрь</i>",
    )


@router.message(RequestCreation.subject, F.text)
async def receive_subject(
    message: Message, session: AsyncSession, user: User, state: FSMContext
) -> None:
    draft = await PurchaseRequestService(session).create_self_initiated_draft(
        user, message.text or ""
    )
    await state.set_state(RequestCreation.waiting_items)
    await state.update_data(
        request_id=draft.request.id,
        procurement_id=None,
        subject=draft.request.subject,
        items=[],
        errors=[],
        comment=draft.request.comment,
    )
    await answer_html(
        message,
        f"Тема: <b>{escape_html(draft.request.subject or '')}</b>\n\n{ITEMS_PROMPT}",
        reply_markup=kb.items_prompt(),
    )


# --- procurement browsing ---------------------------------------------------
async def _render_procurement_list(
    target: Message | CallbackQuery,
    session: AsyncSession,
    user: User,
    page: int,
    only_open: bool,
) -> None:
    service = ProcurementService(session)
    result = await service.list_for_purchaser(user, page=page, only_open=only_open)
    title = "📢 <b>Активные закупки</b>" if only_open else "🕘 <b>Архив закупок</b>"
    if result.is_empty:
        body = f"{title}\n\nПока нет доступных закупок."
        markup = None
    else:
        body = f"{title}\nВсего: {result.total}"
        markup = kb.procurement_list(result, scope="open" if only_open else "archive")

    if isinstance(target, CallbackQuery):
        await edit_or_send(target, body, markup)
        await target.answer()
    else:
        await answer_html(target, body, reply_markup=markup)


@router.callback_query(ProcurementCB.filter(F.action == "plist"))
async def procurement_list_page(
    callback: CallbackQuery, callback_data: ProcurementCB, session: AsyncSession, user: User
) -> None:
    await _render_procurement_list(callback, session, user, callback_data.page, only_open=True)


@router.callback_query(ProcurementCB.filter(F.action == "phistory"))
async def procurement_history_page(
    callback: CallbackQuery, callback_data: ProcurementCB, session: AsyncSession, user: User
) -> None:
    await _render_procurement_list(callback, session, user, callback_data.page, only_open=False)


@router.callback_query(ProcurementCB.filter(F.action == "popen"))
async def open_procurement(
    callback: CallbackQuery, callback_data: ProcurementCB, session: AsyncSession, user: User
) -> None:
    settings = get_settings()
    procurements = ProcurementService(session)
    requests = PurchaseRequestService(session)

    procurement = await procurements.get_for_purchaser(user, callback_data.procurement_id)
    existing = await requests.get_own_request(user, procurement.id)
    now = utcnow()
    can_submit = procurement.accepts_submissions(now)

    text = texts.procurement_card_purchaser(procurement, settings.timezone, existing, now)
    if not can_submit and procurement.status is ProcurementStatus.OPEN:
        text += f"\n\n⚠️ {texts.DEADLINE_EXPIRED}"
    await edit_or_send(callback, text, kb.procurement_card(procurement, existing, can_submit))
    await callback.answer()


# --- composing a request ----------------------------------------------------
@router.callback_query(ProcurementCB.filter(F.action == "submit"))
async def start_request(
    callback: CallbackQuery,
    callback_data: ProcurementCB,
    session: AsyncSession,
    user: User,
    state: FSMContext,
) -> None:
    service = PurchaseRequestService(session)
    draft = await service.get_or_create_draft(user, callback_data.procurement_id)

    if draft.already_submitted:
        await _show_own_request(callback, session, user, draft.request.id)
        await callback.answer("Заявка по этой закупке уже отправлена.", show_alert=True)
        return

    # This entry point always comes from a procurement card, so the draft is
    # bound to one.
    procurement = draft.procurement
    if procurement is None:  # pragma: no cover - defensive
        await notify_stale(callback)
        return

    existing_items = await service.list_items(user, draft.request.id)
    await state.clear()
    await state.set_state(RequestCreation.waiting_items)
    await state.update_data(
        request_id=draft.request.id,
        procurement_id=procurement.id,
        items=_dump_items(
            [
                ParsedItem(
                    name=item.name,
                    quantity=item.quantity,
                    unit=item.unit,
                    source_text=item.source_text or item.name,
                    confidence=1.0,
                )
                for item in existing_items
            ]
        ),
        errors=[],
        comment=draft.request.comment,
    )

    header = (
        f"📦 {escape_html(procurement.procurement_number)} — "
        f"{escape_html(procurement.title)}\n\n{ITEMS_PROMPT}"
    )
    await edit_or_send(callback, header, kb.items_prompt())
    await callback.answer()


@router.message(RequestCreation.waiting_items, F.text)
async def receive_items(
    message: Message, session: AsyncSession, user: User, state: FSMContext
) -> None:
    settings = get_settings()
    raw = (message.text or "")[: settings.max_input_length]
    result: ParseResult = _parser().parse(raw)

    if not result.items and not result.errors:
        await answer_html(message, "Не удалось прочитать список. Попробуйте еще раз.")
        return

    await state.update_data(items=_dump_items(result.items), errors=_dump_errors(result.errors))
    await state.set_state(RequestCreation.preview)
    await _render_preview(message, session, user, state)


@router.message(RequestCreation.waiting_items, F.document)
@router.message(RequestCreation.preview, F.document)
async def receive_items_file(
    message: Message, session: AsyncSession, user: User, state: FSMContext
) -> None:
    """Accept the item list as an uploaded Excel workbook."""
    settings = get_settings()
    document = message.document
    if document is None or message.bot is None:  # pragma: no cover - defensive
        return

    file_name = document.file_name or ""
    if not file_name.lower().endswith(EXCEL_EXTENSIONS):
        raise ValidationError(
            "Нужен файл Excel (.xlsx). Либо отправьте список текстом одним сообщением."
        )
    if (document.file_size or 0) > settings.max_upload_size_bytes:
        raise ValidationError(
            f"Файл слишком большой: максимум {settings.max_upload_size_bytes // 1_000_000} МБ."
        )

    buffer = BytesIO()
    await message.bot.download(document, destination=buffer)
    content = buffer.getvalue()
    if len(content) > settings.max_upload_size_bytes:
        raise ValidationError("Файл слишком большой.")

    result = _excel_parser().parse_file(content)
    logger.info(
        "excel list uploaded",
        extra={
            "operation": "parse_excel_list",
            "user_id": user.id,
            "result": f"items={len(result.items)},errors={len(result.errors)}",
        },
    )

    if not result.items and result.errors:
        problems = "\n".join(f"• {error.reason}" for error in result.errors[:5])
        await answer_html(
            message,
            f"⚠️ Не удалось прочитать список из файла.\n\n{problems}\n\n{ITEMS_PROMPT}",
            reply_markup=kb.items_prompt(),
        )
        return

    await state.update_data(items=_dump_items(result.items), errors=_dump_errors(result.errors))
    await state.set_state(RequestCreation.preview)
    await _render_preview(message, session, user, state)


@router.callback_query(ItemCB.filter(F.action == "template"))
async def send_template(callback: CallbackQuery) -> None:
    """Hand the purchaser a ready-to-fill spreadsheet."""
    template = build_items_template()
    if callback.message is not None and isinstance(callback.message, Message):
        await callback.message.answer_document(
            BufferedInputFile(template.content, filename=template.filename),
            caption="Заполните и отправьте этот файл боту.",
        )
    await callback.answer()


async def _render_preview(
    target: Message | CallbackQuery,
    session: AsyncSession,
    user: User,
    state: FSMContext,
) -> None:
    settings = get_settings()
    data = await state.get_data()
    items = _load_items(data.get("items"))
    errors = _load_errors(data.get("errors"))
    procurement_id = int(data.get("procurement_id") or 0)

    procurement = (
        await ProcurementService(session).get_for_purchaser(user, procurement_id)
        if procurement_id
        else None
    )
    text = texts.request_preview(
        procurement,
        items,
        data.get("comment"),
        settings.preview_items_limit,
        subject=data.get("subject"),
    )
    problems = texts.parse_problems(errors)
    if problems:
        text = f"{text}\n\n{problems}"
    if not items:
        text += "\n\n⚠️ Пока нет ни одной корректной позиции."

    markup = kb.draft_preview(has_errors=bool(errors) or not items)
    if isinstance(target, CallbackQuery):
        await edit_or_send(target, text, markup)
    else:
        await answer_html(target, text, reply_markup=markup)


@router.callback_query(RequestCreation.preview, ItemCB.filter(F.action == "restart"))
async def restart_items(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(RequestCreation.waiting_items)
    await edit_or_send(callback, ITEMS_PROMPT, kb.items_prompt())
    await callback.answer()


@router.callback_query(RequestCreation.preview, ItemCB.filter(F.action == "edit_pick"))
async def pick_item_to_edit(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    count = len(data.get("items") or [])
    if not count:
        await callback.answer("Список пуст.", show_alert=True)
        return
    await edit_or_send(
        callback, "Выберите номер позиции для редактирования:", kb.item_picker(count, "edit")
    )
    await callback.answer()


@router.callback_query(RequestCreation.preview, ItemCB.filter(F.action == "delete_pick"))
async def pick_item_to_delete(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    count = len(data.get("items") or [])
    if not count:
        await callback.answer("Список пуст.", show_alert=True)
        return
    await edit_or_send(
        callback, "Выберите номер позиции для удаления:", kb.item_picker(count, "delete")
    )
    await callback.answer()


@router.callback_query(RequestCreation.preview, ItemCB.filter(F.action == "delete"))
async def delete_item(
    callback: CallbackQuery,
    callback_data: ItemCB,
    session: AsyncSession,
    user: User,
    state: FSMContext,
) -> None:
    data = await state.get_data()
    items = list(data.get("items") or [])
    index = callback_data.index - 1
    if not 0 <= index < len(items):
        await callback.answer(texts.STALE_CALLBACK, show_alert=True)
        return
    removed = items.pop(index)
    await state.update_data(items=items)
    await _render_preview(callback, session, user, state)
    await callback.answer(f"Удалено: {removed['name']}")


@router.callback_query(RequestCreation.preview, ItemCB.filter(F.action == "edit"))
async def edit_item(
    callback: CallbackQuery, callback_data: ItemCB, state: FSMContext
) -> None:
    data = await state.get_data()
    items = list(data.get("items") or [])
    index = callback_data.index - 1
    if not 0 <= index < len(items):
        await callback.answer(texts.STALE_CALLBACK, show_alert=True)
        return
    await state.update_data(edit_index=index)
    await state.set_state(RequestCreation.editing_item)
    current = items[index]
    await edit_or_send(
        callback,
        (
            f"Текущая позиция {callback_data.index}:\n"
            f"<code>{current['name']} — {current['quantity']} {current['unit']}</code>\n\n"
            "Отправьте исправленную строку, например:\n"
            "<code>Сахар 50 кг</code>"
        ),
    )
    await callback.answer()


@router.message(RequestCreation.editing_item, F.text)
async def apply_item_edit(
    message: Message, session: AsyncSession, user: User, state: FSMContext
) -> None:
    data = await state.get_data()
    items = list(data.get("items") or [])
    index = int(data.get("edit_index", -1))
    parsed, error = _parser().parse_line(message.text or "")
    if parsed is None:
        reason = error.reason if error else "строка не распознана"
        await answer_html(message, f"⚠️ Не удалось разобрать строку: {reason}. Попробуйте еще раз.")
        return
    if not 0 <= index < len(items):
        await answer_html(message, texts.STALE_CALLBACK)
        await state.set_state(RequestCreation.preview)
        return

    items[index] = _dump_items([parsed])[0]
    # A successful manual fix also clears the corresponding parse error.
    await state.update_data(items=items, errors=[], edit_index=None)
    await state.set_state(RequestCreation.preview)
    await _render_preview(message, session, user, state)


@router.callback_query(RequestCreation.preview, ItemCB.filter(F.action == "add"))
async def add_item_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(RequestCreation.adding_item)
    await edit_or_send(
        callback, "Отправьте новую позицию, например:\n<code>Соль 20 кг</code>"
    )
    await callback.answer()


@router.message(RequestCreation.adding_item, F.text)
async def add_item(
    message: Message, session: AsyncSession, user: User, state: FSMContext
) -> None:
    settings = get_settings()
    data = await state.get_data()
    items = list(data.get("items") or [])
    if len(items) >= settings.max_items_per_request:
        await answer_html(
            message, f"Достигнут лимит позиций: {settings.max_items_per_request}."
        )
        await state.set_state(RequestCreation.preview)
        return

    parsed, error = _parser().parse_line(message.text or "")
    if parsed is None:
        reason = error.reason if error else "строка не распознана"
        await answer_html(message, f"⚠️ Не удалось разобрать строку: {reason}. Попробуйте еще раз.")
        return

    items.append(_dump_items([parsed])[0])
    await state.update_data(items=items)
    await state.set_state(RequestCreation.preview)
    await _render_preview(message, session, user, state)


@router.callback_query(RequestCreation.preview, ItemCB.filter(F.action == "comment"))
async def comment_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(RequestCreation.comment)
    await edit_or_send(callback, "Отправьте комментарий к заявке одним сообщением.")
    await callback.answer()


@router.message(RequestCreation.comment, F.text)
async def set_comment(
    message: Message, session: AsyncSession, user: User, state: FSMContext
) -> None:
    settings = get_settings()
    await state.update_data(comment=(message.text or "")[: settings.max_comment_length])
    await state.set_state(RequestCreation.preview)
    await _render_preview(message, session, user, state)


@router.callback_query(ItemCB.filter(F.action == "back"))
async def back_to_preview(
    callback: CallbackQuery, session: AsyncSession, user: User, state: FSMContext
) -> None:
    await state.set_state(RequestCreation.preview)
    await _render_preview(callback, session, user, state)
    await callback.answer()


@router.callback_query(ItemCB.filter(F.action == "cancel"))
async def cancel_request(callback: CallbackQuery, user: User, state: FSMContext) -> None:
    await state.clear()
    await edit_or_send(callback, texts.CANCELLED)
    if callback.message is not None and isinstance(callback.message, Message):
        await callback.message.answer("Главное меню", reply_markup=main_menu(user.role))
    await callback.answer()


@router.callback_query(RequestCreation.preview, ItemCB.filter(F.action == "submit"))
async def submit_request(
    callback: CallbackQuery, session: AsyncSession, user: User, state: FSMContext
) -> None:
    data = await state.get_data()
    items = _load_items(data.get("items"))
    request_id = int(data.get("request_id", 0))
    if not request_id:
        await callback.answer(texts.STALE_CALLBACK, show_alert=True)
        await state.clear()
        return
    if not items:
        await callback.answer("Нельзя отправить пустую заявку.", show_alert=True)
        return

    service = PurchaseRequestService(session)
    await service.replace_items(user, request_id, items)
    comment = data.get("comment")
    if comment:
        await service.set_comment(user, request_id, comment)

    result = await service.submit(user, request_id)
    await state.clear()

    if result.already_submitted:
        await callback.answer("Заявка уже была отправлена.", show_alert=True)
        await _show_own_request(callback, session, user, request_id)
        return

    source = (
        f"Закупка: {result.procurement.procurement_number}"
        if result.procurement is not None
        else "Заявка отправлена сотруднику тендерного отдела на подтверждение."
    )
    await edit_or_send(
        callback,
        (
            f"✅ Заявка <b>{result.request.public_number}</b> отправлена.\n\n"
            f"{source}\n"
            f"Позиций: {len(result.items)}"
        ),
    )
    await callback.answer("Заявка отправлена")

    # --- everything below happens after the transaction has committed ---
    await _notify_employees(callback, session, user, result)


async def _notify_employees(
    callback: CallbackQuery,
    session: AsyncSession,
    user: User,
    result: SubmitResult,
) -> None:
    if callback.bot is None:  # pragma: no cover - always set in production
        return
    try:
        employees = await UserRepository(session).list_employees()
        if not employees:
            return
        excel = await ExcelExportService(session).export_request(user, result.request.id)
        notifier = NotificationService(callback.bot)
        await notifier.notify_new_request(
            employees,
            result.request,
            result.procurement,
            user,
            result.items,
            excel=excel,
        )
    except Exception:
        logger.exception(
            "failed to notify employees",
            extra={
                "operation": "notify_new_request",
                "purchase_request_id": result.request.id,
                "result": "error",
            },
        )


# --- own requests -----------------------------------------------------------
@router.callback_query(RequestListCB.filter(F.scope == "mine"))
async def my_requests_page(
    callback: CallbackQuery, callback_data: RequestListCB, session: AsyncSession, user: User
) -> None:
    page = await PurchaseRequestService(session).list_own(
        user, page=callback_data.page, statuses=ACTIVE_STATUSES
    )
    await edit_or_send(
        callback,
        f"📋 <b>Мои заявки</b>\nВсего: {page.total}",
        kb.my_requests_list(page, scope="mine"),
    )
    await callback.answer()


@router.callback_query(RequestListCB.filter(F.scope == "history"))
async def history_page(
    callback: CallbackQuery, callback_data: RequestListCB, session: AsyncSession, user: User
) -> None:
    page = await PurchaseRequestService(session).list_own(
        user, page=callback_data.page, statuses=HISTORY_STATUSES
    )
    await edit_or_send(
        callback,
        f"🕘 <b>История заявок</b>\nВсего: {page.total}",
        kb.my_requests_list(page, scope="history"),
    )
    await callback.answer()


@router.callback_query(RequestCB.filter(F.action == "myopen"))
async def open_own_request(
    callback: CallbackQuery, callback_data: RequestCB, session: AsyncSession, user: User
) -> None:
    await _show_own_request(callback, session, user, callback_data.request_id)
    await callback.answer()


async def _show_own_request(
    callback: CallbackQuery, session: AsyncSession, user: User, request_id: int
) -> None:
    settings = get_settings()
    service = PurchaseRequestService(session)
    request = await service.get_for_actor(user, request_id)
    items = await service.list_items(user, request.id)
    procurement = await service.get_procurement(request.id)
    text = texts.request_card(
        request,
        procurement,
        user,
        items,
        settings.timezone,
        settings.preview_items_limit,
        for_employee=False,
    )
    await edit_or_send(callback, text, kb.my_request_card(request, items))


@router.callback_query(RequestCB.filter(F.action == "excel"))
async def download_own_excel(
    callback: CallbackQuery, callback_data: RequestCB, session: AsyncSession, user: User
) -> None:
    excel = await ExcelExportService(session).export_request(user, callback_data.request_id)
    if callback.message is not None and isinstance(callback.message, Message):
        await callback.message.answer_document(
            BufferedInputFile(excel.content, filename=excel.filename)
        )
    await callback.answer()


# --- fallback ---------------------------------------------------------------
@router.message(F.document)
async def document_outside_flow(message: Message, user: User) -> None:
    """A file arrived without an open request — explain what to do with it."""
    await answer_html(
        message,
        "📎 Чтобы отправить список файлом, сначала откройте заявку:\n\n"
        f"• {texts.BTN_ACTIVE_PROCUREMENTS} → нужная закупка → «➕ Подать заявку»\n"
        f"• либо {texts.BTN_CREATE_REQUEST} — своя заявка\n\n"
        "После этого пришлите файл Excel (.xlsx).",
        reply_markup=main_menu(user.role),
    )


@router.message(F.text)
async def fallback(message: Message, user: User, state: FSMContext) -> None:
    if await state.get_state() is not None:
        raise ValidationError("Ожидается другой ввод. Отправьте /cancel для отмены.")
    await answer_html(
        message,
        "Выберите действие в меню ниже.",
        reply_markup=main_menu(user.role),
    )
