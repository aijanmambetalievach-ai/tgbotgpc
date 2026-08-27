"""Procurement lifecycle against a real database."""

from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.exceptions import (
    InvalidStatusTransitionError,
    LimitExceededError,
    NotAParticipantError,
    PermissionDeniedError,
    ValidationError,
)
from app.domain.timeutils import utcnow
from app.models.audit_log import AuditAction
from app.models.enums import ParticipantSelectionMode, ProcurementStatus
from app.models.user import User
from app.repositories.audit import AuditRepository
from app.services.procurement_service import ProcurementDraftInput, ProcurementService
from tests.integration.conftest import create_user, make_open_procurement

pytestmark = pytest.mark.integration


def _draft(
    participants: list[User], mode: ParticipantSelectionMode = ParticipantSelectionMode.MANUAL
) -> ProcurementDraftInput:
    return ProcurementDraftInput(
        title="Продукты питания на сентябрь",
        deadline=utcnow() + dt.timedelta(days=3),
        description="Сбор потребности подразделений.",
        participant_mode=mode,
        participant_ids=[user.id for user in participants],
    )


async def test_create_draft_allocates_number(
    session: AsyncSession, employee: User, purchasers: list[User]
) -> None:
    procurement = await ProcurementService(session).create_draft(employee, _draft(purchasers))

    assert procurement.status is ProcurementStatus.DRAFT
    assert procurement.procurement_number.startswith("TENDER-")
    assert procurement.procurement_number.endswith("000001")
    assert procurement.published_at is None


async def test_numbers_are_sequential_and_unique(
    session: AsyncSession, employee: User, purchasers: list[User]
) -> None:
    service = ProcurementService(session)
    numbers = [
        (await service.create_draft(employee, _draft(purchasers))).procurement_number
        for _ in range(5)
    ]
    assert len(set(numbers)) == 5
    assert numbers == sorted(numbers)


async def test_publish_freezes_participants(
    session: AsyncSession, employee: User, purchasers: list[User]
) -> None:
    service = ProcurementService(session)
    procurement = await service.create_draft(employee, _draft(purchasers))
    result = await service.publish(employee, procurement.id)

    assert result.procurement.status is ProcurementStatus.OPEN
    assert result.procurement.published_at is not None
    assert {user.id for user in result.participants} == {user.id for user in purchasers}
    assert result.already_published is False


async def test_publish_all_active_materialises_current_purchasers(
    session: AsyncSession, employee: User, purchasers: list[User]
) -> None:
    service = ProcurementService(session)
    procurement = await service.create_draft(
        employee, _draft([], ParticipantSelectionMode.ALL_ACTIVE)
    )
    result = await service.publish(
        employee, procurement.id, ParticipantSelectionMode.ALL_ACTIVE
    )
    assert len(result.participants) == len(purchasers)

    # A purchaser added *after* publication must not change history.
    await create_user(session, telegram_id=2099, full_name="Новый Закупщик")
    frozen = await service.procurements.list_participant_user_ids(procurement.id)
    assert len(frozen) == len(purchasers)


async def test_publish_is_idempotent(
    session: AsyncSession, employee: User, purchasers: list[User]
) -> None:
    service = ProcurementService(session)
    procurement = await service.create_draft(employee, _draft(purchasers))

    first = await service.publish(employee, procurement.id)
    second = await service.publish(employee, procurement.id)

    assert first.already_published is False
    assert second.already_published is True
    assert len(second.participants) == len(purchasers)
    assert await service.procurements.count_participants(procurement.id) == len(purchasers)


async def test_duplicate_participants_are_deduplicated(
    session: AsyncSession, employee: User, purchasers: list[User]
) -> None:
    service = ProcurementService(session)
    procurement = await service.create_draft(employee, _draft(purchasers))
    duplicated = [user.id for user in purchasers] + [purchasers[0].id, purchasers[0].id]

    await service.set_participants(employee, procurement.id, duplicated)
    assert await service.procurements.count_participants(procurement.id) == len(purchasers)


async def test_publish_without_participants_fails(
    session: AsyncSession, employee: User
) -> None:
    service = ProcurementService(session)
    procurement = await service.create_draft(
        employee, _draft([], ParticipantSelectionMode.ALL_ACTIVE)
    )
    with pytest.raises(ValidationError):
        await service.publish(employee, procurement.id, ParticipantSelectionMode.ALL_ACTIVE)


async def test_publish_with_past_deadline_fails(
    session: AsyncSession, employee: User, purchasers: list[User]
) -> None:
    service = ProcurementService(session)
    data = _draft(purchasers)
    data.deadline = utcnow() - dt.timedelta(hours=1)
    procurement = await service.create_draft(employee, data)

    with pytest.raises(ValidationError):
        await service.publish(employee, procurement.id)


async def test_close_cancel_and_complete(
    session: AsyncSession, employee: User, purchasers: list[User]
) -> None:
    service = ProcurementService(session)
    procurement = await make_open_procurement(session, employee, purchasers)

    closed = await service.change_status(employee, procurement.id, ProcurementStatus.CLOSED)
    assert closed.status is ProcurementStatus.CLOSED
    assert closed.closed_at is not None

    completed = await service.change_status(
        employee, procurement.id, ProcurementStatus.COMPLETED
    )
    assert completed.status is ProcurementStatus.COMPLETED

    # Terminal state: nothing else is allowed.
    with pytest.raises(InvalidStatusTransitionError):
        await service.change_status(employee, procurement.id, ProcurementStatus.OPEN)


async def test_invalid_transition_is_rejected(
    session: AsyncSession, employee: User, purchasers: list[User]
) -> None:
    service = ProcurementService(session)
    procurement = await service.create_draft(employee, _draft(purchasers))
    with pytest.raises(InvalidStatusTransitionError):
        await service.change_status(employee, procurement.id, ProcurementStatus.COMPLETED)


async def test_status_change_is_idempotent(
    session: AsyncSession, employee: User, purchasers: list[User]
) -> None:
    service = ProcurementService(session)
    procurement = await make_open_procurement(session, employee, purchasers)
    await service.change_status(employee, procurement.id, ProcurementStatus.CLOSED)
    again = await service.change_status(employee, procurement.id, ProcurementStatus.CLOSED)
    assert again.status is ProcurementStatus.CLOSED


async def test_extend_deadline_is_audited_and_reopens_closed(
    session: AsyncSession, employee: User, purchasers: list[User]
) -> None:
    service = ProcurementService(session)
    procurement = await make_open_procurement(session, employee, purchasers)
    await service.change_status(employee, procurement.id, ProcurementStatus.CLOSED)

    new_deadline = utcnow() + dt.timedelta(days=10)
    extended = await service.extend_deadline(employee, procurement.id, new_deadline)

    assert extended.status is ProcurementStatus.OPEN
    assert extended.deadline == new_deadline
    assert extended.closed_at is None

    records = await AuditRepository(session).list_for_entity("procurement", procurement.id)
    assert any(r.action == AuditAction.PROCUREMENT_DEADLINE_EXTENDED for r in records)
    assert any("old_deadline" in r.payload for r in records)


async def test_extend_deadline_into_the_past_fails(
    session: AsyncSession, employee: User, purchasers: list[User]
) -> None:
    procurement = await make_open_procurement(session, employee, purchasers)
    with pytest.raises(ValidationError):
        await ProcurementService(session).extend_deadline(
            employee, procurement.id, utcnow() - dt.timedelta(days=1)
        )


async def test_purchaser_cannot_create_or_publish(
    session: AsyncSession, employee: User, purchasers: list[User]
) -> None:
    service = ProcurementService(session)
    attacker = purchasers[0]

    with pytest.raises(PermissionDeniedError):
        await service.create_draft(attacker, _draft(purchasers))

    procurement = await make_open_procurement(session, employee, purchasers)
    with pytest.raises(PermissionDeniedError):
        await service.publish(attacker, procurement.id)
    with pytest.raises(PermissionDeniedError):
        await service.change_status(attacker, procurement.id, ProcurementStatus.CLOSED)
    with pytest.raises(PermissionDeniedError):
        await service.get_card(attacker, procurement.id)
    with pytest.raises(PermissionDeniedError):
        await service.extend_deadline(
            attacker, procurement.id, utcnow() + dt.timedelta(days=5)
        )


async def test_purchaser_only_sees_own_procurements(
    session: AsyncSession, employee: User, purchasers: list[User]
) -> None:
    service = ProcurementService(session)
    invited, not_invited = purchasers[0], purchasers[2]
    procurement = await make_open_procurement(session, employee, [invited])

    visible = await service.list_for_purchaser(invited)
    assert [item.id for item in visible.items] == [procurement.id]

    hidden = await service.list_for_purchaser(not_invited)
    assert hidden.items == []

    with pytest.raises(NotAParticipantError):
        await service.get_for_purchaser(not_invited, procurement.id)


async def test_draft_is_invisible_to_purchasers(
    session: AsyncSession, employee: User, purchasers: list[User]
) -> None:
    service = ProcurementService(session)
    procurement = await service.create_draft(employee, _draft(purchasers))
    with pytest.raises(NotAParticipantError):
        await service.get_for_purchaser(purchasers[0], procurement.id)


async def test_participant_limit_is_enforced(
    session: AsyncSession, employee: User, purchasers: list[User], settings
) -> None:
    service = ProcurementService(session)
    service.settings = settings.model_copy(update={"max_participants_per_procurement": 2})
    with pytest.raises(LimitExceededError):
        await service.create_draft(employee, _draft(purchasers))


async def test_audit_trail_records_creation_and_publication(
    session: AsyncSession, employee: User, purchasers: list[User]
) -> None:
    procurement = await make_open_procurement(session, employee, purchasers)
    records = await AuditRepository(session).list_for_entity("procurement", procurement.id)
    actions = {record.action for record in records}
    assert AuditAction.PROCUREMENT_CREATED in actions
    assert AuditAction.PROCUREMENT_PUBLISHED in actions
    assert all(record.actor_user_id == employee.id for record in records)
