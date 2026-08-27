"""Tender employee flows: procurements, requests, purchasers, statistics."""

from __future__ import annotations

import datetime as dt
import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

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
from app.bot.filters import EmployeeFilter
from app.bot.handlers.helpers import answer_html, edit_or_send
from app.bot.keyboards import tender_employee as kb
from app.bot.keyboards.common import main_menu
from app.bot.keyboards.tender_employee import STATUS_FILTERS
from app.bot.states.procurement import ProcurementCreation, ProcurementEditing
from app.bot.states.purchase_request import RequestModeration
from app.bot.states.users import AddPurchaser
from app.config.settings import get_settings
from app.domain.exceptions import NotFoundError, ValidationError
from app.domain.timeutils import parse_deadline, utcnow
from app.models.enums import ParticipantSelectionMode, ProcurementStatus, PurchaseRequestStatus
from app.models.user import User
from app.parsers.procurement_parser import RegexProcurementParser
from app.services.excel_export_service import ExcelExportService
from app.services.notification_service import NotificationService
from app.services.procurement_service import ProcurementDraftInput, ProcurementService
from app.services.purchase_request_service import PurchaseRequestService
from app.services.statistics_service import StatisticsService
from app.services.user_service import UserService

logger = logging.getLogger(__name__)

router = Router(name="tender_employee")
router.message.filter(EmployeeFilter)
router.callback_query.filter(EmployeeFilter)

DEADLINE_PROMPT = (
    "Укажите крайний срок приема заявок.\n\n"
    "Например:\n"
    "<code>25.08.2026</code>\n"
    "<code>25.08.2026 18:00</code>\n"
    "<code>до 30 августа 17:00</code>"
)
QUICK_PROMPT = (
    "Отправьте информацию о закупке одним сообщением.\n\n"
    "Например:\n"
    "<code>Название: Канцелярские товары\n"
    "Срок: 30.08.2026 17:00\n"
    "Описание: Необходимо собрать потребность подразделений.</code>\n\n"
    "Или свободно:\n"
    "<code>Канцелярские товары\n"
    "до 30 августа 17:00\n"
    "Собрать потребность всех отделов</code>"
)


def _procurement_parser() -> RegexProcurementParser:
    settings = get_settings()
    return RegexProcurementParser(
        timezone=settings.timezone,
        default_deadline_time=settings.default_deadline_time_obj,
        max_title_length=settings.max_procurement_title_length,
        max_description_length=settings.max_procurement_description_length,
    )


# ===========================================================================
# Main menu
# ===========================================================================
@router.message(F.text == texts.BTN_PROCUREMENTS)
async def menu_procurements(
    message: Message, session: AsyncSession, user: User, state: FSMContext
) -> None:
    await state.clear()
    await _render_procurement_list(message, session, user, "active", 1)


@router.message(F.text == texts.BTN_NEW_REQUESTS)
async def menu_new_requests(
    message: Message, session: AsyncSession, user: User, state: FSMContext
) -> None:
    await state.clear()
    page = await PurchaseRequestService(session).list_new(user, page=1)
    if page.is_empty:
        await answer_html(message, "📥 Новых заявок нет.")
        return
    await answer_html(
        message,
        f"📥 <b>Новые заявки</b>\nВсего: {page.total}",
        reply_markup=kb.request_list(page, scope="new"),
    )


@router.message(F.text == texts.BTN_STATISTICS)
async def menu_statistics(
    message: Message, session: AsyncSession, user: User, state: FSMContext
) -> None:
    await state.clear()
    stats = await StatisticsService(session).dashboard(user)
    await answer_html(
        message,
        texts.statistics_text(
            stats.open_procurements,
            stats.procurements_this_month,
            stats.active_purchasers,
            stats.requests_today,
            stats.requests_this_week,
            stats.new_requests,
            stats.in_progress_requests,
            stats.completed_requests,
        ),
    )


@router.message(F.text == texts.BTN_SETTINGS)
async def menu_settings(message: Message, state: FSMContext) -> None:
    await state.clear()
    settings = get_settings()
    await answer_html(
        message,
        texts.settings_text(
            settings.app_timezone, settings.default_deadline_time, settings.page_size
        ),
    )


@router.message(F.text == texts.BTN_PURCHASERS)
async def menu_purchasers(
    message: Message, session: AsyncSession, user: User, state: FSMContext
) -> None:
    await state.clear()
    await _render_users(message, session, user, page=1, include_revoked=False)


# ===========================================================================
# Procurement creation
# ===========================================================================
@router.message(F.text == texts.BTN_CREATE_PROCUREMENT)
async def menu_create_procurement(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(ProcurementCreation.choosing_mode)
    await answer_html(message, "Как создать закупку?", reply_markup=kb.create_mode())


@router.callback_query(WizardCB.filter(F.action == "mode_step"))
async def wizard_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(ProcurementCreation.title)
    await state.update_data(mode="wizard")
    await edit_or_send(
        callback,
        "Шаг 1 из 4\n\nВведите название закупки:\n\n"
        "<i>Например: Продукты питания на сентябрь</i>",
        kb.cancel_only(),
    )
    await callback.answer()


@router.message(ProcurementCreation.title, F.text)
async def wizard_title(message: Message, state: FSMContext) -> None:
    settings = get_settings()
    title = (message.text or "").strip()[: settings.max_procurement_title_length]
    if len(title) < 3:
        raise ValidationError("Название должно содержать минимум 3 символа.")
    await state.update_data(title=title)
    await state.set_state(ProcurementCreation.description)
    await answer_html(
        message, "Шаг 2 из 4\n\nДобавьте описание закупки:", reply_markup=kb.skip_or_cancel()
    )


@router.callback_query(ProcurementCreation.description, WizardCB.filter(F.action == "skip"))
async def wizard_skip_description(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(description=None)
    await state.set_state(ProcurementCreation.deadline)
    await edit_or_send(callback, f"Шаг 3 из 4\n\n{DEADLINE_PROMPT}", kb.cancel_only())
    await callback.answer()


@router.message(ProcurementCreation.description, F.text)
async def wizard_description(message: Message, state: FSMContext) -> None:
    settings = get_settings()
    await state.update_data(
        description=(message.text or "").strip()[: settings.max_procurement_description_length]
    )
    await state.set_state(ProcurementCreation.deadline)
    await answer_html(message, f"Шаг 3 из 4\n\n{DEADLINE_PROMPT}", reply_markup=kb.cancel_only())


@router.message(ProcurementCreation.deadline, F.text)
async def wizard_deadline(
    message: Message, session: AsyncSession, user: User, state: FSMContext
) -> None:
    settings = get_settings()
    parsed = parse_deadline(
        message.text or "", settings.timezone, settings.default_deadline_time_obj
    )
    if parsed is None:
        raise ValidationError("Не удалось распознать дату. Попробуйте формат 25.08.2026 18:00")
    if parsed.value <= utcnow():
        raise ValidationError("Срок должен быть в будущем.")

    await state.update_data(
        deadline=parsed.value.isoformat(), deadline_explicit=parsed.time_was_explicit
    )
    await state.set_state(ProcurementCreation.participants)
    await state.update_data(selected=[], all_selected=False)
    await _render_participants(message, session, user, state, page=1)


# --- participant picker -----------------------------------------------------
async def _render_participants(
    target: Message | CallbackQuery,
    session: AsyncSession,
    user: User,
    state: FSMContext,
    page: int,
) -> None:
    data = await state.get_data()
    selected = set(data.get("selected") or [])
    all_selected = bool(data.get("all_selected"))

    users_page = await UserService(session).list_purchasers(user, page=page)
    if users_page.is_empty:
        text = (
            "👥 Нет активных закупщиков.\n\n"
            "Сначала добавьте закупщиков в разделе «👥 Закупщики»."
        )
        if isinstance(target, CallbackQuery):
            await edit_or_send(target, text, kb.cancel_only())
        else:
            await answer_html(target, text, reply_markup=kb.cancel_only())
        return

    chosen = users_page.total if all_selected else len(selected)
    text = (
        "Шаг 4 из 4\n\n"
        "Кому доступна закупка?\n\n"
        f"Выбрано: {chosen} из {users_page.total}"
    )
    markup = kb.participants_picker(users_page, selected, all_selected)
    if isinstance(target, CallbackQuery):
        await edit_or_send(target, text, markup)
    else:
        await answer_html(target, text, reply_markup=markup)


@router.callback_query(WizardCB.filter(F.action == "ppage"))
async def participants_page(
    callback: CallbackQuery,
    callback_data: WizardCB,
    session: AsyncSession,
    user: User,
    state: FSMContext,
) -> None:
    await _render_participants(callback, session, user, state, callback_data.page)
    await callback.answer()


@router.callback_query(WizardCB.filter(F.action == "toggle"))
async def participants_toggle(
    callback: CallbackQuery,
    callback_data: WizardCB,
    session: AsyncSession,
    user: User,
    state: FSMContext,
) -> None:
    data = await state.get_data()
    selected = set(data.get("selected") or [])
    all_selected = bool(data.get("all_selected"))

    if all_selected:
        # Materialise "all" into an explicit list before removing anyone.
        everyone = await UserService(session).list_active_purchasers(user)
        selected = {item.id for item in everyone}
        all_selected = False

    try:
        target_id = int(callback_data.value)
    except ValueError:
        await callback.answer(texts.STALE_CALLBACK, show_alert=True)
        return

    if target_id in selected:
        selected.discard(target_id)
    else:
        selected.add(target_id)

    await state.update_data(selected=sorted(selected), all_selected=all_selected)
    await _render_participants(callback, session, user, state, callback_data.page)
    await callback.answer()


@router.callback_query(WizardCB.filter(F.action == "select_all"))
async def participants_select_all(
    callback: CallbackQuery,
    callback_data: WizardCB,
    session: AsyncSession,
    user: User,
    state: FSMContext,
) -> None:
    await state.update_data(all_selected=True, selected=[])
    await _render_participants(callback, session, user, state, callback_data.page)
    await callback.answer("Выбраны все активные закупщики")


@router.callback_query(WizardCB.filter(F.action == "select_none"))
async def participants_select_none(
    callback: CallbackQuery,
    callback_data: WizardCB,
    session: AsyncSession,
    user: User,
    state: FSMContext,
) -> None:
    await state.update_data(all_selected=False, selected=[])
    await _render_participants(callback, session, user, state, callback_data.page)
    await callback.answer("Выбор снят")


@router.callback_query(WizardCB.filter(F.action == "participants_done"))
async def participants_done(
    callback: CallbackQuery, session: AsyncSession, user: User, state: FSMContext
) -> None:
    data = await state.get_data()
    if not data.get("all_selected") and not (data.get("selected") or []):
        await callback.answer("Выберите хотя бы одного закупщика.", show_alert=True)
        return
    await _show_preview(callback, session, user, state)
    await callback.answer()


# --- quick mode -------------------------------------------------------------
@router.callback_query(WizardCB.filter(F.action == "mode_quick"))
async def quick_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(ProcurementCreation.quick_input)
    await state.update_data(mode="quick")
    await edit_or_send(callback, QUICK_PROMPT, kb.cancel_only())
    await callback.answer()


@router.message(ProcurementCreation.quick_input, F.text)
async def quick_parse(
    message: Message, session: AsyncSession, user: User, state: FSMContext
) -> None:
    settings = get_settings()
    parsed = _procurement_parser().parse((message.text or "")[: settings.max_input_length])

    if parsed.title is None or parsed.deadline is None:
        problems = "\n".join(f"• {error.reason}" for error in parsed.errors)
        await answer_html(
            message,
            f"⚠️ Не удалось разобрать сообщение.\n\n{problems}\n\n{QUICK_PROMPT}",
            reply_markup=kb.cancel_only(),
        )
        return
    if parsed.deadline <= utcnow():
        raise ValidationError("Срок должен быть в будущем.")

    await state.update_data(
        title=parsed.title,
        description=parsed.description,
        deadline=parsed.deadline.isoformat(),
        deadline_explicit=parsed.deadline_time_was_explicit,
        all_selected=True,
        selected=[],
    )
    await _show_preview(message, session, user, state)


# --- preview / publish ------------------------------------------------------
async def _show_preview(
    target: Message | CallbackQuery,
    session: AsyncSession,
    user: User,
    state: FSMContext,
) -> None:
    """Materialise a DRAFT (so the real number can be shown) and preview it."""
    settings = get_settings()
    data = await state.get_data()
    title = str(data.get("title") or "")
    description = data.get("description")
    deadline = dt.datetime.fromisoformat(str(data["deadline"]))
    all_selected = bool(data.get("all_selected"))
    selected = [int(value) for value in (data.get("selected") or [])]
    mode = (
        ParticipantSelectionMode.ALL_ACTIVE if all_selected else ParticipantSelectionMode.MANUAL
    )

    service = ProcurementService(session)
    procurement_id = data.get("procurement_id")
    if procurement_id:
        procurement = await service.update_fields(
            user,
            int(procurement_id),
            title=title,
            description=description,
            deadline=deadline,
        )
        if not all_selected and selected:
            await service.set_participants(user, procurement.id, selected)
    else:
        procurement = await service.create_draft(
            user,
            ProcurementDraftInput(
                title=title,
                deadline=deadline,
                description=description,
                participant_mode=mode,
                participant_ids=selected,
            ),
        )
        await state.update_data(procurement_id=procurement.id)

    if all_selected:
        total = len(await UserService(session).list_active_purchasers(user))
        participants_label = f"Все активные закупщики ({total})"
    else:
        participants_label = f"{len(selected)} закупщиков"

    text = texts.procurement_preview(
        procurement.procurement_number,
        procurement.title,
        procurement.description,
        procurement.deadline,
        settings.timezone,
        participants_label,
        deadline_time_assumed=not bool(data.get("deadline_explicit", True)),
    )
    markup = kb.quick_preview() if data.get("mode") == "quick" else kb.wizard_preview()

    await state.set_state(ProcurementCreation.preview)
    if isinstance(target, CallbackQuery):
        await edit_or_send(target, text, markup)
    else:
        await answer_html(target, text, reply_markup=markup)


@router.callback_query(ProcurementCreation.preview, WizardCB.filter(F.action == "publish"))
async def wizard_publish(
    callback: CallbackQuery, session: AsyncSession, user: User, state: FSMContext
) -> None:
    data = await state.get_data()
    procurement_id = int(data.get("procurement_id") or 0)
    if not procurement_id:
        await callback.answer(texts.STALE_CALLBACK, show_alert=True)
        await state.clear()
        return

    all_selected = bool(data.get("all_selected"))
    selected = [int(value) for value in (data.get("selected") or [])]
    mode = (
        ParticipantSelectionMode.ALL_ACTIVE if all_selected else ParticipantSelectionMode.MANUAL
    )

    service = ProcurementService(session)
    result = await service.publish(user, procurement_id, mode, selected)
    await state.clear()

    if result.already_published:
        await callback.answer("Закупка уже опубликована.", show_alert=True)
    else:
        await callback.answer("Закупка опубликована")

    await edit_or_send(
        callback,
        (
            f"✅ Закупка <b>{result.procurement.procurement_number}</b> опубликована.\n\n"
            f"Участников: {len(result.participants)}"
        ),
    )

    # --- notifications, strictly after commit ---
    if callback.bot is not None and not result.already_published:
        notifier = NotificationService(callback.bot)
        delivered = await notifier.notify_new_procurement(
            result.participants, result.procurement
        )
        if callback.message is not None and isinstance(callback.message, Message):
            await callback.message.answer(
                f"📣 Уведомления доставлены: {delivered} из {len(result.participants)}"
            )


@router.callback_query(ProcurementCreation.preview, WizardCB.filter(F.action == "edit"))
async def wizard_edit_menu(callback: CallbackQuery) -> None:
    await edit_or_send(callback, "Что изменить?", kb.wizard_edit_fields())
    await callback.answer()


@router.callback_query(WizardCB.filter(F.action == "back"))
async def wizard_back(
    callback: CallbackQuery, session: AsyncSession, user: User, state: FSMContext
) -> None:
    await _show_preview(callback, session, user, state)
    await callback.answer()


@router.callback_query(WizardCB.filter(F.action == "edit_title"))
async def wizard_edit_title(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(ProcurementCreation.edit_title)
    await edit_or_send(callback, "Введите новое название:", kb.cancel_only())
    await callback.answer()


@router.message(ProcurementCreation.edit_title, F.text)
async def wizard_apply_title(
    message: Message, session: AsyncSession, user: User, state: FSMContext
) -> None:
    settings = get_settings()
    title = (message.text or "").strip()[: settings.max_procurement_title_length]
    if len(title) < 3:
        raise ValidationError("Название должно содержать минимум 3 символа.")
    await state.update_data(title=title)
    await _show_preview(message, session, user, state)


@router.callback_query(WizardCB.filter(F.action == "edit_description"))
async def wizard_edit_description(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(ProcurementCreation.edit_description)
    await edit_or_send(callback, "Введите новое описание:", kb.cancel_only())
    await callback.answer()


@router.message(ProcurementCreation.edit_description, F.text)
async def wizard_apply_description(
    message: Message, session: AsyncSession, user: User, state: FSMContext
) -> None:
    settings = get_settings()
    await state.update_data(
        description=(message.text or "").strip()[: settings.max_procurement_description_length]
    )
    await _show_preview(message, session, user, state)


@router.callback_query(WizardCB.filter(F.action == "edit_deadline"))
async def wizard_edit_deadline(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(ProcurementCreation.edit_deadline)
    await edit_or_send(callback, DEADLINE_PROMPT, kb.cancel_only())
    await callback.answer()


@router.message(ProcurementCreation.edit_deadline, F.text)
async def wizard_apply_deadline(
    message: Message, session: AsyncSession, user: User, state: FSMContext
) -> None:
    settings = get_settings()
    parsed = parse_deadline(
        message.text or "", settings.timezone, settings.default_deadline_time_obj
    )
    if parsed is None:
        raise ValidationError("Не удалось распознать дату. Попробуйте формат 25.08.2026 18:00")
    if parsed.value <= utcnow():
        raise ValidationError("Срок должен быть в будущем.")
    await state.update_data(
        deadline=parsed.value.isoformat(), deadline_explicit=parsed.time_was_explicit
    )
    await _show_preview(message, session, user, state)


@router.callback_query(WizardCB.filter(F.action == "choose_participants"))
async def wizard_choose_participants(
    callback: CallbackQuery, session: AsyncSession, user: User, state: FSMContext
) -> None:
    await state.set_state(ProcurementCreation.participants)
    await _render_participants(callback, session, user, state, page=1)
    await callback.answer()


@router.callback_query(WizardCB.filter(F.action == "cancel"))
async def wizard_cancel(
    callback: CallbackQuery, session: AsyncSession, user: User, state: FSMContext
) -> None:
    data = await state.get_data()
    procurement_id = data.get("procurement_id")
    await state.clear()
    if procurement_id:
        # The draft already exists in the database — mark it cancelled instead
        # of leaving a mystery record behind.
        service = ProcurementService(session)
        try:
            await service.change_status(
                user, int(procurement_id), ProcurementStatus.CANCELLED
            )
        except Exception:
            logger.warning("could not cancel draft procurement %s", procurement_id)
    await edit_or_send(callback, texts.CANCELLED)
    if callback.message is not None and isinstance(callback.message, Message):
        await callback.message.answer("Главное меню", reply_markup=main_menu(user.role))
    await callback.answer()


# ===========================================================================
# Procurement lists and cards
# ===========================================================================
async def _render_procurement_list(
    target: Message | CallbackQuery,
    session: AsyncSession,
    user: User,
    status_key: str,
    page: int,
) -> None:
    label, statuses = STATUS_FILTERS.get(status_key, STATUS_FILTERS["active"])
    service = ProcurementService(session)
    result = await service.list_for_employee(user, list(statuses), page=page)
    stats = await service.stats_for([item.id for item in result.items])

    header = f"📦 <b>Закупки</b> · {label}\nВсего: {result.total}"
    if result.is_empty:
        header += "\n\nСписок пуст."
    markup = kb.procurement_list(result, stats, status_key)

    if isinstance(target, CallbackQuery):
        await edit_or_send(target, header, markup)
    else:
        await answer_html(target, header, reply_markup=markup)


@router.callback_query(ProcurementListCB.filter())
async def procurement_list_page(
    callback: CallbackQuery,
    callback_data: ProcurementListCB,
    session: AsyncSession,
    user: User,
) -> None:
    await _render_procurement_list(
        callback, session, user, callback_data.status, callback_data.page
    )
    await callback.answer()


async def _show_procurement_card(
    target: Message | CallbackQuery, session: AsyncSession, user: User, procurement_id: int
) -> None:
    settings = get_settings()
    card = await ProcurementService(session).get_card(user, procurement_id)
    text = texts.procurement_card_employee(
        card.procurement, card.stats, settings.timezone, utcnow()
    )
    markup = kb.procurement_card(card.procurement)
    if isinstance(target, CallbackQuery):
        await edit_or_send(target, text, markup)
    else:
        await answer_html(target, text, reply_markup=markup)


@router.callback_query(ProcurementCB.filter(F.action == "open"))
async def open_procurement(
    callback: CallbackQuery, callback_data: ProcurementCB, session: AsyncSession, user: User
) -> None:
    await _show_procurement_card(callback, session, user, callback_data.procurement_id)
    await callback.answer()


@router.callback_query(ProcurementCB.filter(F.action == "participants"))
async def procurement_participants(
    callback: CallbackQuery, callback_data: ProcurementCB, session: AsyncSession, user: User
) -> None:
    page = await ProcurementService(session).list_participants(
        user, callback_data.procurement_id, page=callback_data.page
    )
    lines = [f"👥 <b>Участники</b>\nВсего: {page.total}", ""]
    for participant in page.items:
        mark = "✅" if participant.can_use_bot else "🚫"
        lines.append(f"{mark} {participant.display_name}")
    await edit_or_send(
        callback, "\n".join(lines), kb.participants_view(page, callback_data.procurement_id)
    )
    await callback.answer()


@router.callback_query(ProcurementCB.filter(F.action == "excel"))
async def procurement_excel(
    callback: CallbackQuery, callback_data: ProcurementCB, session: AsyncSession, user: User
) -> None:
    await callback.answer("Готовлю файл…")
    excel = await ExcelExportService(session).export_procurement(
        user, callback_data.procurement_id
    )
    if callback.message is not None and isinstance(callback.message, Message):
        await callback.message.answer_document(
            BufferedInputFile(excel.content, filename=excel.filename),
            caption="📊 Сводный отчет по закупке",
        )


@router.callback_query(ProcurementCB.filter(F.action == "publish"))
async def publish_existing(
    callback: CallbackQuery, callback_data: ProcurementCB, session: AsyncSession, user: User
) -> None:
    service = ProcurementService(session)
    result = await service.publish(user, callback_data.procurement_id)
    await _show_procurement_card(callback, session, user, callback_data.procurement_id)
    await callback.answer(
        "Уже опубликована" if result.already_published else "Опубликована"
    )
    if callback.bot is not None and not result.already_published:
        await NotificationService(callback.bot).notify_new_procurement(
            result.participants, result.procurement
        )


@router.callback_query(ProcurementCB.filter(F.action.in_({"close", "cancel", "complete"})))
async def procurement_confirm(
    callback: CallbackQuery, callback_data: ProcurementCB
) -> None:
    labels = {
        "close": ("🔒 Закрыть закупку", "Закрыть закупку? Новые заявки приниматься не будут."),
        "cancel": ("❌ Отменить закупку", "Отменить закупку? Действие необратимо."),
        "complete": ("✅ Завершить закупку", "Отметить закупку завершенной?"),
    }
    label, question = labels[callback_data.action]
    await edit_or_send(
        callback,
        question,
        kb.confirm_action(callback_data.action, callback_data.procurement_id, label),
    )
    await callback.answer()


@router.callback_query(
    ProcurementCB.filter(F.action.in_({"close_yes", "cancel_yes", "complete_yes"}))
)
async def procurement_apply_status(
    callback: CallbackQuery, callback_data: ProcurementCB, session: AsyncSession, user: User
) -> None:
    mapping = {
        "close_yes": ProcurementStatus.CLOSED,
        "cancel_yes": ProcurementStatus.CANCELLED,
        "complete_yes": ProcurementStatus.COMPLETED,
    }
    await ProcurementService(session).change_status(
        user, callback_data.procurement_id, mapping[callback_data.action]
    )
    await _show_procurement_card(callback, session, user, callback_data.procurement_id)
    await callback.answer("Статус обновлен")


@router.callback_query(ProcurementCB.filter(F.action == "remind"))
async def procurement_remind(
    callback: CallbackQuery, callback_data: ProcurementCB, session: AsyncSession, user: User
) -> None:
    service = ProcurementService(session)
    card = await service.get_card(user, callback_data.procurement_id)
    pending = await service.list_non_responders(user, callback_data.procurement_id)
    if not pending:
        await callback.answer("Все участники уже подали заявки.", show_alert=True)
        return

    await callback.answer(f"Отправляю напоминание: {len(pending)}")
    delivered = 0
    if callback.bot is not None:
        delivered = await NotificationService(callback.bot).notify_reminder(
            pending, card.procurement
        )
    await service.mark_reminder_sent(user, callback_data.procurement_id, delivered)
    if callback.message is not None and isinstance(callback.message, Message):
        await callback.message.answer(
            f"🔔 Напоминание отправлено: {delivered} из {len(pending)}"
        )


@router.callback_query(ProcurementCB.filter(F.action == "edit"))
async def procurement_edit_menu(
    callback: CallbackQuery, callback_data: ProcurementCB
) -> None:
    await edit_or_send(
        callback, "Что изменить?", kb.procurement_edit_fields(callback_data.procurement_id)
    )
    await callback.answer()


@router.callback_query(ProcurementCB.filter(F.action == "edit_title"))
async def procurement_edit_title(
    callback: CallbackQuery, callback_data: ProcurementCB, state: FSMContext
) -> None:
    await state.set_state(ProcurementEditing.title)
    await state.update_data(procurement_id=callback_data.procurement_id)
    await edit_or_send(callback, "Введите новое название закупки:")
    await callback.answer()


@router.message(ProcurementEditing.title, F.text)
async def procurement_apply_title(
    message: Message, session: AsyncSession, user: User, state: FSMContext
) -> None:
    data = await state.get_data()
    await state.clear()
    await ProcurementService(session).update_fields(
        user, int(data["procurement_id"]), title=(message.text or "").strip()
    )
    await answer_html(message, "✅ Название обновлено.")
    await _show_procurement_card(message, session, user, int(data["procurement_id"]))


@router.callback_query(ProcurementCB.filter(F.action == "edit_description"))
async def procurement_edit_description(
    callback: CallbackQuery, callback_data: ProcurementCB, state: FSMContext
) -> None:
    await state.set_state(ProcurementEditing.description)
    await state.update_data(procurement_id=callback_data.procurement_id)
    await edit_or_send(callback, "Введите новое описание закупки:")
    await callback.answer()


@router.message(ProcurementEditing.description, F.text)
async def procurement_apply_description(
    message: Message, session: AsyncSession, user: User, state: FSMContext
) -> None:
    data = await state.get_data()
    await state.clear()
    await ProcurementService(session).update_fields(
        user, int(data["procurement_id"]), description=(message.text or "").strip()
    )
    await answer_html(message, "✅ Описание обновлено.")
    await _show_procurement_card(message, session, user, int(data["procurement_id"]))


@router.callback_query(ProcurementCB.filter(F.action == "extend"))
async def procurement_extend_prompt(
    callback: CallbackQuery, callback_data: ProcurementCB, state: FSMContext
) -> None:
    await state.set_state(ProcurementEditing.deadline)
    await state.update_data(procurement_id=callback_data.procurement_id)
    await edit_or_send(callback, f"⏰ Новый срок подачи заявок.\n\n{DEADLINE_PROMPT}")
    await callback.answer()


@router.message(ProcurementEditing.deadline, F.text)
async def procurement_apply_deadline(
    message: Message, session: AsyncSession, user: User, state: FSMContext
) -> None:
    settings = get_settings()
    data = await state.get_data()
    parsed = parse_deadline(
        message.text or "", settings.timezone, settings.default_deadline_time_obj
    )
    if parsed is None:
        raise ValidationError("Не удалось распознать дату. Попробуйте формат 25.08.2026 18:00")

    procurement_id = int(data["procurement_id"])
    await state.clear()
    await ProcurementService(session).extend_deadline(user, procurement_id, parsed.value)
    await answer_html(message, "✅ Срок обновлен.")
    await _show_procurement_card(message, session, user, procurement_id)


# ===========================================================================
# Requests
# ===========================================================================
@router.callback_query(RequestListCB.filter(F.scope == "new"))
async def requests_new_page(
    callback: CallbackQuery, callback_data: RequestListCB, session: AsyncSession, user: User
) -> None:
    page = await PurchaseRequestService(session).list_new(user, page=callback_data.page)
    await edit_or_send(
        callback,
        f"📥 <b>Новые заявки</b>\nВсего: {page.total}",
        kb.request_list(page, scope="new"),
    )
    await callback.answer()


@router.callback_query(RequestListCB.filter(F.scope == "proc"))
async def requests_of_procurement(
    callback: CallbackQuery, callback_data: RequestListCB, session: AsyncSession, user: User
) -> None:
    page = await PurchaseRequestService(session).list_by_procurement(
        user, callback_data.procurement_id, page=callback_data.page
    )
    await edit_or_send(
        callback,
        f"📋 <b>Заявки по закупке</b>\nВсего: {page.total}",
        kb.request_list(page, scope="proc", procurement_id=callback_data.procurement_id),
    )
    await callback.answer()


async def _show_request_card(
    target: Message | CallbackQuery, session: AsyncSession, user: User, request_id: int
) -> None:
    settings = get_settings()
    service = PurchaseRequestService(session)
    request = await service.get_for_actor(user, request_id)
    items = await service.list_items(user, request_id)
    procurement = await service.get_procurement(request_id)
    purchaser = await session.get(User, request.purchaser_id)
    if purchaser is None:  # pragma: no cover - FK guarantees
        raise NotFoundError("Закупщик не найден.")
    text = texts.request_card(
        request,
        procurement,
        purchaser,
        items,
        settings.timezone,
        settings.preview_items_limit,
        for_employee=True,
    )
    markup = kb.request_card(request)
    if isinstance(target, CallbackQuery):
        await edit_or_send(target, text, markup)
    else:
        await answer_html(target, text, reply_markup=markup)


@router.callback_query(RequestCB.filter(F.action == "open"))
async def open_request(
    callback: CallbackQuery, callback_data: RequestCB, session: AsyncSession, user: User
) -> None:
    await _show_request_card(callback, session, user, callback_data.request_id)
    await callback.answer()


@router.callback_query(RequestCB.filter(F.action == "excel"))
async def request_excel(
    callback: CallbackQuery, callback_data: RequestCB, session: AsyncSession, user: User
) -> None:
    await callback.answer("Готовлю файл…")
    excel = await ExcelExportService(session).export_request(user, callback_data.request_id)
    if callback.message is not None and isinstance(callback.message, Message):
        await callback.message.answer_document(
            BufferedInputFile(excel.content, filename=excel.filename)
        )


@router.callback_query(RequestCB.filter(F.action == "status"))
async def request_change_status(
    callback: CallbackQuery,
    callback_data: RequestCB,
    session: AsyncSession,
    user: User,
    state: FSMContext,
) -> None:
    try:
        new_status = PurchaseRequestStatus(callback_data.value)
    except ValueError:
        await callback.answer(texts.STALE_CALLBACK, show_alert=True)
        return

    if new_status is PurchaseRequestStatus.REJECTED:
        await state.set_state(RequestModeration.reject_reason)
        await state.update_data(request_id=callback_data.request_id)
        await edit_or_send(callback, "Укажите причину отклонения заявки:")
        await callback.answer()
        return

    result = await PurchaseRequestService(session).change_status(
        user, callback_data.request_id, new_status
    )
    await _show_request_card(callback, session, user, callback_data.request_id)
    await callback.answer("Статус обновлен" if result.changed else "Статус уже установлен")

    if result.changed and callback.bot is not None:
        await NotificationService(callback.bot).notify_request_status(
            result.purchaser, result.request, result.new_status
        )


@router.message(RequestModeration.reject_reason, F.text)
async def request_reject(
    message: Message, session: AsyncSession, user: User, state: FSMContext
) -> None:
    data = await state.get_data()
    request_id = int(data.get("request_id") or 0)
    await state.clear()
    if not request_id:
        raise NotFoundError("Заявка не найдена.")

    reason = (message.text or "").strip()
    result = await PurchaseRequestService(session).change_status(
        user, request_id, PurchaseRequestStatus.REJECTED, comment=reason
    )
    await answer_html(message, "❌ Заявка отклонена, закупщик уведомлен.")
    await _show_request_card(message, session, user, request_id)

    if result.changed and message.bot is not None:
        await NotificationService(message.bot).notify_request_status(
            result.purchaser, result.request, result.new_status, reason
        )


# ===========================================================================
# Purchasers
# ===========================================================================
async def _render_users(
    target: Message | CallbackQuery,
    session: AsyncSession,
    user: User,
    page: int,
    include_revoked: bool,
) -> None:
    result = await UserService(session).list_purchasers(
        user, page=page, include_revoked=include_revoked
    )
    header = f"👥 <b>Закупщики</b>\nВсего: {result.total}"
    if result.is_empty:
        header += "\n\nПока никого нет. Добавьте первого закупщика."
    markup = kb.users_list(result, include_revoked)
    if isinstance(target, CallbackQuery):
        await edit_or_send(target, header, markup)
    else:
        await answer_html(target, header, reply_markup=markup)


@router.callback_query(UserListCB.filter())
async def users_page(
    callback: CallbackQuery, callback_data: UserListCB, session: AsyncSession, user: User
) -> None:
    await _render_users(
        callback, session, user, callback_data.page, bool(callback_data.revoked)
    )
    await callback.answer()


@router.callback_query(UserCB.filter(F.action == "add"))
async def user_add_menu(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await edit_or_send(callback, "Как добавить закупщика?", kb.add_purchaser_mode())
    await callback.answer()


@router.callback_query(UserCB.filter(F.action == "add_invite"))
async def user_add_invite(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AddPurchaser.invite_name)
    await edit_or_send(
        callback,
        "Введите имя и фамилию закупщика.\n\n<i>Например: Иван Иванов</i>",
    )
    await callback.answer()


@router.message(AddPurchaser.invite_name, F.text)
async def user_create_invite(
    message: Message, session: AsyncSession, user: User, state: FSMContext
) -> None:
    settings = get_settings()
    await state.clear()
    service = UserService(session)
    invite = await service.create_invite(user, (message.text or "").strip())

    bot_username = None
    if message.bot is not None:
        me = await message.bot.me()
        bot_username = me.username

    await answer_html(
        message,
        texts.invite_created(
            invite.code, invite.full_name, bot_username, settings.invite_ttl_hours
        ),
    )


@router.callback_query(UserCB.filter(F.action == "add_id"))
async def user_add_by_id(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AddPurchaser.telegram_id)
    await edit_or_send(
        callback,
        "Отправьте Telegram ID закупщика (только цифры).\n\n"
        "<i>ID можно узнать, например, через @userinfobot.</i>",
    )
    await callback.answer()


@router.message(AddPurchaser.telegram_id, F.text)
async def user_receive_telegram_id(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    if not raw.isdigit():
        raise ValidationError("Telegram ID должен состоять только из цифр.")
    await state.update_data(telegram_id=int(raw))
    await state.set_state(AddPurchaser.telegram_id_name)
    await answer_html(message, "Введите имя и фамилию закупщика:")


@router.message(AddPurchaser.telegram_id_name, F.text)
async def user_create_by_id(
    message: Message, session: AsyncSession, user: User, state: FSMContext
) -> None:
    data = await state.get_data()
    await state.clear()
    created = await UserService(session).add_purchaser_by_telegram_id(
        user, int(data["telegram_id"]), (message.text or "").strip()
    )
    await answer_html(
        message,
        f"✅ Закупщик <b>{created.full_name}</b> добавлен.\n"
        f"Telegram ID: <code>{created.telegram_id}</code>\n\n"
        "Попросите его отправить боту /start.",
    )


@router.callback_query(UserCB.filter(F.action == "open"))
async def user_card(
    callback: CallbackQuery, callback_data: UserCB, session: AsyncSession, user: User
) -> None:
    settings = get_settings()
    card = await UserService(session).get_card(user, callback_data.user_id)
    await edit_or_send(
        callback,
        texts.purchaser_card(card.user, card.requests_count, settings.timezone),
        kb.user_card(card.user, callback_data.page),
    )
    await callback.answer()


@router.callback_query(UserCB.filter(F.action.in_({"block", "unblock", "revoke"})))
async def user_access(
    callback: CallbackQuery, callback_data: UserCB, session: AsyncSession, user: User
) -> None:
    settings = get_settings()
    service = UserService(session)
    if callback_data.action == "block":
        await service.block(user, callback_data.user_id)
        note = "Доступ заблокирован"
    elif callback_data.action == "unblock":
        await service.unblock(user, callback_data.user_id)
        note = "Доступ восстановлен"
    else:
        await service.revoke(user, callback_data.user_id)
        note = "Доступ отозван"

    card = await service.get_card(user, callback_data.user_id)
    await edit_or_send(
        callback,
        texts.purchaser_card(card.user, card.requests_count, settings.timezone),
        kb.user_card(card.user, callback_data.page),
    )
    await callback.answer(note)


@router.callback_query(UserCB.filter(F.action == "requests"))
async def user_requests(
    callback: CallbackQuery, callback_data: UserCB, session: AsyncSession, user: User
) -> None:
    page = await PurchaseRequestService(session).list_of_purchaser(
        user, callback_data.user_id, page=callback_data.page
    )
    await edit_or_send(
        callback,
        f"📋 <b>Заявки закупщика</b>\nВсего: {page.total}",
        kb.user_requests_list(page, callback_data.user_id),
    )
    await callback.answer()


# ===========================================================================
# Fallback
# ===========================================================================
@router.message(F.text)
async def fallback(message: Message, user: User, state: FSMContext) -> None:
    if await state.get_state() is not None:
        raise ValidationError("Ожидается другой ввод. Отправьте /cancel для отмены.")
    await answer_html(
        message, "Выберите действие в меню ниже.", reply_markup=main_menu(user.role)
    )
