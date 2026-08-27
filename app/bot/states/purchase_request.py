"""FSM states for purchaser request creation and moderation."""

from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class RequestCreation(StatesGroup):
    #: only for self-initiated requests: what the purchaser needs
    subject = State()
    waiting_items = State()
    preview = State()
    editing_item = State()
    adding_item = State()
    comment = State()


class RequestModeration(StatesGroup):
    """Employee-side flows that need free-text input."""

    reject_reason = State()
