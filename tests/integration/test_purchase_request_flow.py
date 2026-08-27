"""Purchase request lifecycle: draft, submit, moderation."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.exceptions import (
    DeadlineExpiredError,
    InvalidStatusTransitionError,
    LimitExceededError,
    NotAParticipantError,
    PermissionDeniedError,
    ProcurementNotAcceptingError,
    ValidationError,
)
from app.domain.timeutils import utcnow
from app.models.enums import ProcurementStatus, PurchaseRequestStatus
from app.models.user import User
from app.parsers.base import ParsedItem
from app.parsers.purchase_list_parser import RegexPurchaseListParser
from app.services.procurement_service import ProcurementService
from app.services.purchase_request_service import PurchaseRequestService
from tests.integration.conftest import make_open_procurement

pytestmark = pytest.mark.integration

ITEMS_TEXT = "1. Сахар — 50 кг\n2. Масло — 60 л\n3. Мука — 100 кг\n4. Яйца — 200 шт"


def parse_items(text: str = ITEMS_TEXT) -> list[ParsedItem]:
    result = RegexPurchaseListParser().parse(text)
    assert result.errors == []
    return result.items


async def submit_request(
    session: AsyncSession, purchaser: User, procurement_id: int, text: str = ITEMS_TEXT
):
    service = PurchaseRequestService(session)
    draft = await service.get_or_create_draft(purchaser, procurement_id)
    await service.replace_items(purchaser, draft.request.id, parse_items(text))
    return await service.submit(purchaser, draft.request.id)


async def test_draft_creation_and_reuse(
    session: AsyncSession, employee: User, purchasers: list[User]
) -> None:
    procurement = await make_open_procurement(session, employee, purchasers)
    service = PurchaseRequestService(session)

    first = await service.get_or_create_draft(purchasers[0], procurement.id)
    second = await service.get_or_create_draft(purchasers[0], procurement.id)

    assert first.is_new is True
    assert second.is_new is False
    assert first.request.id == second.request.id
    assert first.request.status is PurchaseRequestStatus.DRAFT


async def test_submit_creates_number_and_items(
    session: AsyncSession, employee: User, purchasers: list[User]
) -> None:
    procurement = await make_open_procurement(session, employee, purchasers)
    result = await submit_request(session, purchasers[0], procurement.id)

    assert result.request.status is PurchaseRequestStatus.SUBMITTED
    assert result.request.submitted_at is not None
    assert result.request.request_number is not None
    assert result.request.request_number.startswith("REQ-")
    assert result.request.request_number.endswith("000001")
    assert len(result.items) == 4
    assert [item.name for item in result.items] == ["Сахар", "Масло", "Мука", "Яйца"]
    assert result.items[0].quantity == Decimal("50.000")
    assert result.items[0].unit == "кг"
    assert result.items[0].position == 1
    assert result.items[0].normalized_name == "сахар"


async def test_double_submit_is_idempotent(
    session: AsyncSession, employee: User, purchasers: list[User]
) -> None:
    procurement = await make_open_procurement(session, employee, purchasers)
    service = PurchaseRequestService(session)

    draft = await service.get_or_create_draft(purchasers[0], procurement.id)
    await service.replace_items(purchasers[0], draft.request.id, parse_items())

    first = await service.submit(purchasers[0], draft.request.id)
    second = await service.submit(purchasers[0], draft.request.id)

    assert first.already_submitted is False
    assert second.already_submitted is True
    assert first.request.request_number == second.request.request_number
    assert first.request.submitted_at == second.request.submitted_at


async def test_one_request_per_purchaser_per_procurement(
    session: AsyncSession, employee: User, purchasers: list[User]
) -> None:
    procurement = await make_open_procurement(session, employee, purchasers)
    result = await submit_request(session, purchasers[0], procurement.id)

    service = PurchaseRequestService(session)
    again = await service.get_or_create_draft(purchasers[0], procurement.id)
    assert again.already_submitted is True
    assert again.request.id == result.request.id

    # And the submitted request can no longer be edited through the draft path.
    with pytest.raises(ValidationError):
        await service.replace_items(purchasers[0], result.request.id, parse_items())


async def test_several_purchasers_one_procurement(
    session: AsyncSession, employee: User, purchasers: list[User]
) -> None:
    procurement = await make_open_procurement(session, employee, purchasers)

    await submit_request(session, purchasers[0], procurement.id, "Сахар 50 кг\nМасло 60 л")
    await submit_request(session, purchasers[1], procurement.id, "Рис 80 кг\nМолоко 100 л")
    await submit_request(session, purchasers[2], procurement.id, "Яйца 500 шт\nКартофель 150 кг")

    stats = await ProcurementService(session).procurements.stats(procurement.id)
    assert stats.participants == 3
    assert stats.responded == 3
    assert stats.total_items == 6
    assert stats.pending == 0
    assert stats.response_rate == 100

    numbers = {
        request.request_number
        for request in (
            await PurchaseRequestService(session).list_by_procurement(employee, procurement.id)
        ).items
    }
    assert len(numbers) == 3


async def test_non_participant_cannot_create_draft(
    session: AsyncSession, employee: User, purchasers: list[User]
) -> None:
    procurement = await make_open_procurement(session, employee, [purchasers[0]])
    with pytest.raises(NotAParticipantError):
        await PurchaseRequestService(session).get_or_create_draft(
            purchasers[1], procurement.id
        )


async def test_expired_deadline_blocks_submission(
    session: AsyncSession, employee: User, purchasers: list[User]
) -> None:
    procurement = await make_open_procurement(session, employee, purchasers)
    service = PurchaseRequestService(session)
    draft = await service.get_or_create_draft(purchasers[0], procurement.id)
    await service.replace_items(purchasers[0], draft.request.id, parse_items())

    # Move the deadline into the past directly (the service refuses to do it).
    procurement.deadline = utcnow() - dt.timedelta(minutes=1)
    await session.commit()

    with pytest.raises(DeadlineExpiredError):
        await service.submit(purchasers[0], draft.request.id)

    # Employee extends the deadline -> submission works again.
    await ProcurementService(session).extend_deadline(
        employee, procurement.id, utcnow() + dt.timedelta(days=1)
    )
    result = await service.submit(purchasers[0], draft.request.id)
    assert result.request.status is PurchaseRequestStatus.SUBMITTED


async def test_closed_procurement_blocks_submission(
    session: AsyncSession, employee: User, purchasers: list[User]
) -> None:
    procurement = await make_open_procurement(session, employee, purchasers)
    service = PurchaseRequestService(session)
    draft = await service.get_or_create_draft(purchasers[0], procurement.id)
    await service.replace_items(purchasers[0], draft.request.id, parse_items())

    await ProcurementService(session).change_status(
        employee, procurement.id, ProcurementStatus.CLOSED
    )
    with pytest.raises(ProcurementNotAcceptingError):
        await service.submit(purchasers[0], draft.request.id)


async def test_blocked_purchaser_cannot_submit(
    session: AsyncSession, employee: User, purchasers: list[User]
) -> None:
    procurement = await make_open_procurement(session, employee, purchasers)
    service = PurchaseRequestService(session)
    draft = await service.get_or_create_draft(purchasers[0], procurement.id)
    await service.replace_items(purchasers[0], draft.request.id, parse_items())

    purchasers[0].is_active = False
    await session.commit()

    with pytest.raises(PermissionDeniedError):
        await service.submit(purchasers[0], draft.request.id)


async def test_empty_request_cannot_be_submitted(
    session: AsyncSession, employee: User, purchasers: list[User]
) -> None:
    procurement = await make_open_procurement(session, employee, purchasers)
    service = PurchaseRequestService(session)
    draft = await service.get_or_create_draft(purchasers[0], procurement.id)
    with pytest.raises(ValidationError):
        await service.submit(purchasers[0], draft.request.id)


async def test_purchaser_cannot_touch_another_request(
    session: AsyncSession, employee: User, purchasers: list[User]
) -> None:
    procurement = await make_open_procurement(session, employee, purchasers)
    result = await submit_request(session, purchasers[0], procurement.id)
    service = PurchaseRequestService(session)

    with pytest.raises(PermissionDeniedError):
        await service.get_for_actor(purchasers[1], result.request.id)
    with pytest.raises(PermissionDeniedError):
        await service.submit(purchasers[1], result.request.id)
    with pytest.raises(PermissionDeniedError):
        await service.change_status(
            purchasers[1], result.request.id, PurchaseRequestStatus.COMPLETED
        )
    with pytest.raises(PermissionDeniedError):
        await service.list_new(purchasers[1])


async def test_status_workflow_and_history(
    session: AsyncSession, employee: User, purchasers: list[User]
) -> None:
    procurement = await make_open_procurement(session, employee, purchasers)
    submitted = await submit_request(session, purchasers[0], procurement.id)
    service = PurchaseRequestService(session)
    request_id = submitted.request.id

    viewed = await service.change_status(employee, request_id, PurchaseRequestStatus.VIEWED)
    assert viewed.changed is True
    in_progress = await service.change_status(
        employee, request_id, PurchaseRequestStatus.IN_PROGRESS
    )
    assert in_progress.new_status is PurchaseRequestStatus.IN_PROGRESS
    completed = await service.change_status(
        employee, request_id, PurchaseRequestStatus.COMPLETED
    )
    assert completed.new_status is PurchaseRequestStatus.COMPLETED

    history = await service.requests.list_history(request_id)
    assert [row.new_status for row in history] == [
        PurchaseRequestStatus.SUBMITTED,
        PurchaseRequestStatus.VIEWED,
        PurchaseRequestStatus.IN_PROGRESS,
        PurchaseRequestStatus.COMPLETED,
    ]
    assert history[-1].old_status is PurchaseRequestStatus.IN_PROGRESS
    assert history[-1].changed_by == employee.id


async def test_repeated_status_change_is_a_no_op(
    session: AsyncSession, employee: User, purchasers: list[User]
) -> None:
    procurement = await make_open_procurement(session, employee, purchasers)
    submitted = await submit_request(session, purchasers[0], procurement.id)
    service = PurchaseRequestService(session)

    await service.change_status(employee, submitted.request.id, PurchaseRequestStatus.VIEWED)
    repeat = await service.change_status(
        employee, submitted.request.id, PurchaseRequestStatus.VIEWED
    )
    assert repeat.changed is False
    assert len(await service.requests.list_history(submitted.request.id)) == 2


async def test_rejection_requires_a_reason(
    session: AsyncSession, employee: User, purchasers: list[User]
) -> None:
    procurement = await make_open_procurement(session, employee, purchasers)
    submitted = await submit_request(session, purchasers[0], procurement.id)
    service = PurchaseRequestService(session)

    with pytest.raises(ValidationError):
        await service.change_status(
            employee, submitted.request.id, PurchaseRequestStatus.REJECTED
        )
    with pytest.raises(ValidationError):
        await service.change_status(
            employee, submitted.request.id, PurchaseRequestStatus.REJECTED, comment="  "
        )

    rejected = await service.change_status(
        employee,
        submitted.request.id,
        PurchaseRequestStatus.REJECTED,
        comment="Некорректно указано количество товара.",
    )
    assert rejected.new_status is PurchaseRequestStatus.REJECTED
    assert rejected.request.rejection_reason == "Некорректно указано количество товара."


async def test_invalid_request_transition_is_rejected(
    session: AsyncSession, employee: User, purchasers: list[User]
) -> None:
    procurement = await make_open_procurement(session, employee, purchasers)
    submitted = await submit_request(session, purchasers[0], procurement.id)
    service = PurchaseRequestService(session)

    await service.change_status(employee, submitted.request.id, PurchaseRequestStatus.COMPLETED)
    with pytest.raises(InvalidStatusTransitionError):
        await service.change_status(
            employee, submitted.request.id, PurchaseRequestStatus.VIEWED
        )


async def test_items_are_replaced_not_appended(
    session: AsyncSession, employee: User, purchasers: list[User]
) -> None:
    procurement = await make_open_procurement(session, employee, purchasers)
    service = PurchaseRequestService(session)
    draft = await service.get_or_create_draft(purchasers[0], procurement.id)

    await service.replace_items(purchasers[0], draft.request.id, parse_items())
    await service.replace_items(
        purchasers[0], draft.request.id, parse_items("Соль 10 кг")
    )

    items = await service.requests.list_items(draft.request.id)
    assert len(items) == 1
    assert items[0].name == "Соль"
    assert items[0].position == 1


async def test_item_limit_is_enforced(
    session: AsyncSession, employee: User, purchasers: list[User], settings
) -> None:
    procurement = await make_open_procurement(session, employee, purchasers)
    service = PurchaseRequestService(session)
    service.settings = settings.model_copy(update={"max_items_per_request": 2})
    draft = await service.get_or_create_draft(purchasers[0], procurement.id)

    with pytest.raises(LimitExceededError) as exc:
        await service.replace_items(purchasers[0], draft.request.id, parse_items())
    assert "максимум" in str(exc.value)


async def test_non_responders_are_listed(
    session: AsyncSession, employee: User, purchasers: list[User]
) -> None:
    procurement = await make_open_procurement(session, employee, purchasers)
    await submit_request(session, purchasers[0], procurement.id)

    pending = await ProcurementService(session).list_non_responders(employee, procurement.id)
    assert {user.id for user in pending} == {purchasers[1].id, purchasers[2].id}
