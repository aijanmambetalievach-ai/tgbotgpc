"""FSM states for procurement creation and editing."""

from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class ProcurementCreation(StatesGroup):
    """Both creation flows share one group so /cancel always cleans up."""

    choosing_mode = State()

    # step-by-step wizard
    title = State()
    description = State()
    deadline = State()
    participants = State()

    # quick free-text mode
    quick_input = State()

    # shared confirmation / correction
    preview = State()
    edit_title = State()
    edit_description = State()
    edit_deadline = State()


class ProcurementEditing(StatesGroup):
    """Editing an already stored procurement."""

    title = State()
    description = State()
    deadline = State()
