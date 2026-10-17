"""Typed callback data.

``CallbackData`` gives structural validation for free: a malformed or forged
payload fails to parse and simply never reaches a handler. Authorization is
still re-checked server-side in the service layer for every action.

Telegram limits callback data to 64 bytes, so prefixes and field names are short.
"""

from __future__ import annotations

from aiogram.filters.callback_data import CallbackData


# --- client ------------------------------------------------------------------
class MenuCB(CallbackData, prefix="m"):
    """Navigation between client sections."""

    to: str


class CategoryCB(CallbackData, prefix="cat"):
    value: str
    #: ``1`` when changed from the profile screen (no welcome message).
    edit: int = 0


class CourseCB(CallbackData, prefix="c"):
    action: str
    id: int = 0
    page: int = 1
    all: int = 0


class LessonCB(CallbackData, prefix="l"):
    action: str
    id: int = 0
    page: int = 1
    all: int = 0


class QuizCB(CallbackData, prefix="q"):
    lesson: int
    number: int
    option: int


class FaqCB(CallbackData, prefix="f"):
    action: str
    id: int = 0
    page: int = 1


class AppCB(CallbackData, prefix="a"):
    """Actions on one application (both client and admin)."""

    action: str
    id: int = 0
    page: int = 1
    scope: str = ""


class FlowCB(CallbackData, prefix="w"):
    """Buttons inside multi-step dialogs: skip, confirm, choices."""

    action: str
    value: str = ""


class ProfileCB(CallbackData, prefix="p"):
    action: str


# --- admin -------------------------------------------------------------------
class AdminAppListCB(CallbackData, prefix="aal"):
    scope: str = "new"
    page: int = 1


class AdminCourseCB(CallbackData, prefix="ac"):
    action: str
    id: int = 0
    page: int = 1
    value: str = ""


class AdminLessonCB(CallbackData, prefix="al"):
    action: str
    id: int = 0
    page: int = 1
    value: str = ""


class AdminFaqCB(CallbackData, prefix="af"):
    action: str
    id: int = 0
    page: int = 1


class AdminClientCB(CallbackData, prefix="acl"):
    action: str
    id: int = 0
    page: int = 1
    cat: str = "all"


class BroadcastCB(CallbackData, prefix="b"):
    action: str
    value: str = ""


class SettingsCB(CallbackData, prefix="s"):
    action: str
    key: str = ""


class NoopCB(CallbackData, prefix="noop"):
    """Inert button (page indicators)."""

    tag: str = "x"
