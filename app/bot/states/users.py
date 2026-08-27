"""FSM states for purchaser onboarding."""

from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class AddPurchaser(StatesGroup):
    invite_name = State()
    telegram_id = State()
    telegram_id_name = State()
