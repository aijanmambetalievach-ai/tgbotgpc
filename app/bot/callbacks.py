"""Typed callback data.

``CallbackData`` gives structural validation for free: a malformed or forged
payload fails to parse and simply never reaches a handler. Authorization is
still re-checked server-side in the service layer for every action.
"""

from __future__ import annotations

from aiogram.filters.callback_data import CallbackData


class ProcurementCB(CallbackData, prefix="proc"):
    """Actions on a single procurement."""

    action: str
    procurement_id: int = 0
    page: int = 1


class ProcurementListCB(CallbackData, prefix="proclist"):
    """Paginated / filtered procurement lists."""

    status: str = "active"
    page: int = 1


class RequestCB(CallbackData, prefix="req"):
    """Actions on a single purchase request."""

    action: str
    request_id: int = 0
    page: int = 1
    value: str = ""


class RequestListCB(CallbackData, prefix="reqlist"):
    """Paginated request lists (new / own / by procurement)."""

    scope: str = "new"
    procurement_id: int = 0
    page: int = 1


class UserCB(CallbackData, prefix="user"):
    """Actions on a single purchaser."""

    action: str
    user_id: int = 0
    page: int = 1


class UserListCB(CallbackData, prefix="userlist"):
    page: int = 1
    revoked: int = 0


class WizardCB(CallbackData, prefix="wiz"):
    """Procurement creation wizard / quick mode."""

    action: str
    value: str = ""
    page: int = 1


class ItemCB(CallbackData, prefix="item"):
    """Editing the item list of a draft request."""

    action: str
    index: int = 0


class NoopCB(CallbackData, prefix="noop"):
    """Inert button (page indicators)."""

    tag: str = "x"
