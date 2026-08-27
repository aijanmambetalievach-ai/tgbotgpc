"""Bot wiring: dispatcher, callback data and keyboard/text rendering."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from pydantic import SecretStr

from app.bot import texts
from app.bot.bot import create_bot, create_dispatcher
from app.bot.callbacks import ProcurementCB, RequestCB, UserCB, WizardCB
from app.bot.keyboards import common as common_kb
from app.bot.keyboards import purchaser as purchaser_kb
from app.bot.keyboards import tender_employee as employee_kb
from app.config.settings import get_settings
from app.models.enums import (
    ParticipantSelectionMode,
    ProcurementStatus,
    PurchaseRequestStatus,
    UserRole,
)
from app.models.procurement import Procurement
from app.models.purchase_request import PurchaseRequest
from app.parsers.base import ParsedItem
from app.repositories.base import Page
from app.repositories.procurements import ProcurementStats
from tests.conftest import make_user

TZ = ZoneInfo("Asia/Bishkek")
NOW = dt.datetime(2026, 8, 22, 9, 0, tzinfo=dt.UTC)

TELEGRAM_CALLBACK_DATA_LIMIT = 64


def make_procurement(procurement_id: int = 1) -> Procurement:
    procurement = Procurement(
        procurement_number="TENDER-2026-000123",
        title="Продукты питания на сентябрь",
        description="Сбор потребности подразделений.",
        status=ProcurementStatus.OPEN,
        deadline=dt.datetime(2026, 8, 25, 12, 0, tzinfo=dt.UTC),
        participant_mode=ParticipantSelectionMode.MANUAL,
        created_by=1,
    )
    procurement.id = procurement_id
    return procurement


def test_dispatcher_wires_middlewares_and_routers() -> None:
    dispatcher = create_dispatcher()
    assert len(dispatcher.update.outer_middleware) >= 4
    names = {router.name for router in dispatcher.sub_routers[0].sub_routers}
    assert {"common", "tender_employee", "purchaser", "errors"} <= names


def test_create_bot_requires_a_token() -> None:
    settings = get_settings().model_copy(update={"bot_token": SecretStr("")})
    with pytest.raises(RuntimeError, match="BOT_TOKEN"):
        create_bot(settings)


def test_callback_data_round_trip_and_size() -> None:
    payloads = [
        ProcurementCB(action="open", procurement_id=987654321).pack(),
        RequestCB(action="status", request_id=123456, value="IN_PROGRESS").pack(),
        UserCB(action="revoke", user_id=987654, page=12).pack(),
        WizardCB(action="toggle", value="987654321", page=9).pack(),
    ]
    for payload in payloads:
        assert len(payload.encode()) <= TELEGRAM_CALLBACK_DATA_LIMIT

    unpacked = ProcurementCB.unpack(payloads[0])
    assert unpacked.action == "open"
    assert unpacked.procurement_id == 987654321


def test_main_menus_differ_per_role() -> None:
    employee_menu = common_kb.main_menu(UserRole.TENDER_EMPLOYEE)
    purchaser_menu = common_kb.main_menu(UserRole.PURCHASER)

    employee_labels = {
        button.text for row in employee_menu.keyboard for button in row
    }
    purchaser_labels = {
        button.text for row in purchaser_menu.keyboard for button in row
    }

    assert texts.BTN_CREATE_PROCUREMENT in employee_labels
    assert texts.BTN_PURCHASERS in employee_labels
    assert texts.BTN_CREATE_PROCUREMENT not in purchaser_labels
    assert texts.BTN_ACTIVE_PROCUREMENTS in purchaser_labels
    # A purchaser can start a request on their own.
    assert texts.BTN_CREATE_REQUEST in purchaser_labels
    assert texts.BTN_CREATE_REQUEST not in employee_labels


def test_self_initiated_request_is_rendered_without_a_procurement() -> None:
    items = [
        ParsedItem(name="Бумага", quantity=Decimal(20), unit="пач", source_text="Бумага 20 пач")
    ]
    rendered = texts.request_preview(
        None, items, comment=None, limit=10, subject="Канцелярия на сентябрь"
    )
    assert "Канцелярия на сентябрь" in rendered
    assert "инициативе закупщика" in rendered
    assert "Бумага" in rendered


def test_request_list_row_falls_back_to_subject() -> None:
    request = PurchaseRequest(
        procurement_id=None,
        purchaser_id=1,
        status=PurchaseRequestStatus.SUBMITTED,
        subject="Канцелярия на сентябрь",
        request_number="REQ-2026-000007",
    )
    row = texts.request_list_row(request, None, "Иван Иванов")
    assert "REQ-2026-000007" in row
    assert "Канцелярия" in row


def test_pagination_row_is_hidden_for_single_page() -> None:
    assert common_kb.pagination_row(lambda page: f"p{page}", 1, 1) == []
    row = common_kb.pagination_row(lambda page: f"p{page}", 2, 5)
    assert [button.text for button in row] == ["‹", "2/5", "›"]


def test_participants_picker_marks_selection() -> None:
    users = [make_user(index) for index in (1, 2, 3)]
    page: Page[object] = Page(items=list(users), total=3, page=1, page_size=10)
    markup = employee_kb.participants_picker(page, selected={users[1].id}, all_selected=False)
    labels = [row[0].text for row in markup.inline_keyboard[:3]]
    assert labels[0].startswith("☐")
    assert labels[1].startswith("☑")

    all_marked = employee_kb.participants_picker(page, selected=set(), all_selected=True)
    assert all(row[0].text.startswith("☑") for row in all_marked.inline_keyboard[:3])


def test_procurement_card_buttons_follow_status() -> None:
    open_buttons = _button_texts(employee_kb.procurement_card(make_procurement()))
    assert "🔒 Закрыть" in open_buttons
    assert "📊 Сводный Excel" in open_buttons
    assert "✅ Завершить" not in open_buttons

    draft = make_procurement()
    draft.status = ProcurementStatus.DRAFT
    draft_buttons = _button_texts(employee_kb.procurement_card(draft))
    assert "🚀 Опубликовать" in draft_buttons
    assert "🔒 Закрыть" not in draft_buttons

    closed = make_procurement()
    closed.status = ProcurementStatus.CLOSED
    closed_buttons = _button_texts(employee_kb.procurement_card(closed))
    assert "✅ Завершить" in closed_buttons


def test_purchaser_card_offers_submit_only_when_allowed() -> None:
    procurement = make_procurement()
    allowed = _button_texts(purchaser_kb.procurement_card(procurement, None, can_submit=True))
    blocked = _button_texts(purchaser_kb.procurement_card(procurement, None, can_submit=False))
    assert "➕ Подать заявку" in allowed
    assert "➕ Подать заявку" not in blocked


def test_item_picker_is_bounded() -> None:
    markup = purchaser_kb.item_picker(500, "delete")
    buttons = [button for row in markup.inline_keyboard for button in row]
    assert len(buttons) <= purchaser_kb.MAX_ITEM_BUTTONS + 1


# --- text rendering ---------------------------------------------------------
def test_procurement_card_text() -> None:
    stats = ProcurementStats(participants=15, responded=9, total_items=64)
    rendered = texts.procurement_card_employee(make_procurement(), stats, TZ, NOW)
    assert "TENDER-2026-000123" in rendered
    assert "Участников: 15" in rendered
    assert "Подали заявки: 9 / 15" in rendered
    assert "Не подали: 6" in rendered
    assert "Процент ответов: 60%" in rendered
    assert "Всего позиций: 64" in rendered
    assert "25.08.2026 18:00" in rendered


def test_request_preview_truncates_long_lists() -> None:
    items = [
        ParsedItem(name=f"Товар {index}", quantity=Decimal(index), unit="шт", source_text="")
        for index in range(1, 51)
    ]
    rendered = texts.request_preview(make_procurement(), items, comment=None, limit=10)
    assert "Позиций: 50" in rendered
    assert "и еще 40" in rendered
    assert rendered.count("\n") < 60


def test_html_is_escaped_in_user_content() -> None:
    procurement = make_procurement()
    procurement.title = "<script>alert(1)</script>"
    rendered = texts.procurement_card_employee(
        procurement, ProcurementStats(1, 0, 0), TZ, NOW
    )
    assert "<script>" not in rendered
    assert "&lt;script&gt;" in rendered


def test_parse_problems_lists_errors() -> None:
    from app.parsers.base import ParseError

    rendered = texts.parse_problems(
        [ParseError(line="Масло несколько бутылок", reason="не удалось определить количество")]
    )
    assert "Масло несколько бутылок" in rendered
    assert "Исправьте" in rendered


def test_statistics_text_contains_all_metrics() -> None:
    rendered = texts.statistics_text(1, 2, 3, 4, 5, 6, 7, 8)
    for label in (
        "Активных закупок: 1",
        "Закупок за месяц: 2",
        "Активных закупщиков: 3",
        "Заявок сегодня: 4",
        "Заявок за неделю: 5",
        "Новых заявок: 6",
        "В работе: 7",
        "Завершенных: 8",
    ):
        assert label in rendered


def test_invite_message_builds_deep_link() -> None:
    rendered = texts.invite_created("abc123", "Иван Иванов", "tender_bot", 72)
    assert "https://t.me/tender_bot?start=abc123" in rendered
    assert "одноразовая" in rendered


def _button_texts(markup: object) -> set[str]:
    return {
        button.text
        for row in markup.inline_keyboard  # type: ignore[attr-defined]
        for button in row
    }
