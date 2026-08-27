"""User administration and onboarding against a real database."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.exceptions import InviteError, PermissionDeniedError, ValidationError
from app.models.enums import UserRole
from app.models.user import User
from app.services.auth_service import AuthService
from app.services.user_service import UserService

pytestmark = pytest.mark.integration


async def test_add_purchaser_by_telegram_id(session: AsyncSession, employee: User) -> None:
    service = UserService(session)
    created = await service.add_purchaser_by_telegram_id(employee, 555001, "Иван Иванов")

    assert created.id is not None
    assert created.role is UserRole.PURCHASER
    assert created.is_active is True
    assert created.created_by == employee.id


async def test_duplicate_telegram_id_is_rejected(
    session: AsyncSession, employee: User
) -> None:
    service = UserService(session)
    await service.add_purchaser_by_telegram_id(employee, 555002, "Иван Иванов")
    with pytest.raises(ValidationError):
        await service.add_purchaser_by_telegram_id(employee, 555002, "Другой Человек")


async def test_short_name_is_rejected(session: AsyncSession, employee: User) -> None:
    with pytest.raises(ValidationError):
        await UserService(session).add_purchaser_by_telegram_id(employee, 555003, "X")


async def test_block_unblock_and_revoke(session: AsyncSession, employee: User) -> None:
    service = UserService(session)
    target = await service.add_purchaser_by_telegram_id(employee, 555004, "Азамат Садыков")

    blocked = await service.block(employee, target.id)
    assert blocked.is_active is False
    assert blocked.can_use_bot is False

    unblocked = await service.unblock(employee, target.id)
    assert unblocked.is_active is True
    assert unblocked.can_use_bot is True

    revoked = await service.revoke(employee, target.id)
    assert revoked.revoked_at is not None
    assert revoked.can_use_bot is False
    # Soft revoke: the row (and its history) survives.
    assert await service.users.get_by_id(target.id) is not None


async def test_revoke_is_idempotent(session: AsyncSession, employee: User) -> None:
    service = UserService(session)
    target = await service.add_purchaser_by_telegram_id(employee, 555005, "Данияр Алиев")
    first = await service.revoke(employee, target.id)
    second = await service.revoke(employee, target.id)
    assert first.revoked_at == second.revoked_at


async def test_employee_cannot_change_own_access(
    session: AsyncSession, employee: User
) -> None:
    with pytest.raises(ValidationError):
        await UserService(session).block(employee, employee.id)


async def test_purchaser_cannot_manage_users(
    session: AsyncSession, employee: User, purchasers: list[User]
) -> None:
    service = UserService(session)
    attacker, victim = purchasers[0], purchasers[1]

    with pytest.raises(PermissionDeniedError):
        await service.add_purchaser_by_telegram_id(attacker, 555006, "Кто-то")
    with pytest.raises(PermissionDeniedError):
        await service.block(attacker, victim.id)
    with pytest.raises(PermissionDeniedError):
        await service.revoke(attacker, victim.id)
    with pytest.raises(PermissionDeniedError):
        await service.list_purchasers(attacker)
    with pytest.raises(PermissionDeniedError):
        await service.create_invite(attacker, "Кто-то Ещё")


async def test_invite_flow(session: AsyncSession, employee: User) -> None:
    invite = await UserService(session).create_invite(employee, "Алексей Петров")
    assert invite.code
    assert invite.used_at is None

    joined = await AuthService(session).accept_invite(
        invite.code, telegram_id=777001, telegram_username="alex"
    )
    assert joined.role is UserRole.PURCHASER
    assert joined.full_name == "Алексей Петров"
    assert joined.telegram_id == 777001
    assert joined.telegram_username == "alex"


async def test_invite_is_single_use(session: AsyncSession, employee: User) -> None:
    invite = await UserService(session).create_invite(employee, "Алексей Петров")
    await AuthService(session).accept_invite(invite.code, telegram_id=777002)

    with pytest.raises(InviteError):
        await AuthService(session).accept_invite(invite.code, telegram_id=777003)


async def test_unknown_invite_code_is_rejected(session: AsyncSession) -> None:
    with pytest.raises(InviteError):
        await AuthService(session).accept_invite("nope", telegram_id=777004)


async def test_resolve_user_refreshes_username(
    session: AsyncSession, purchasers: list[User]
) -> None:
    auth = AuthService(session)
    user = await auth.resolve_user(
        purchasers[0].telegram_id, telegram_username="ivan_new"
    )
    assert user is not None
    assert user.telegram_username == "ivan_new"


async def test_resolve_unknown_user_returns_none(session: AsyncSession) -> None:
    assert await AuthService(session).resolve_user(999999) is None


async def test_bootstrap_is_idempotent(session: AsyncSession, settings_env) -> None:
    auth = AuthService(session, settings_env)
    created_first = await auth.bootstrap_employees()
    created_second = await auth.bootstrap_employees()

    assert len(created_first) == 1
    assert created_second == []
    user = await auth.users.get_by_telegram_id(424242)
    assert user is not None
    assert user.role is UserRole.TENDER_EMPLOYEE


@pytest.fixture
def settings_env(settings):
    """Settings copy with one bootstrap id configured."""
    return settings.model_copy(update={"bootstrap_admin_telegram_ids": "424242"})
