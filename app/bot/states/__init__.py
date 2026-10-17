"""FSM state groups for multi-step dialogs."""

from __future__ import annotations

from aiogram.fsm.state import State, StatesGroup


class ClientFlow(StatesGroup):
    """Creating an application (course sign-up, individual training, consultation)."""

    course_comment = State()
    individual_goal = State()
    consultation_question = State()
    support_task = State()
    preferred_time = State()
    contact_method = State()
    name = State()
    phone = State()
    confirm = State()


class ClientChat(StatesGroup):
    writing = State()


class ProfileEdit(StatesGroup):
    name = State()
    phone = State()
    organization = State()


class Quiz(StatesGroup):
    answering = State()


class AdminReply(StatesGroup):
    writing = State()
    reject_reason = State()


class CourseEditor(StatesGroup):
    title = State()
    description = State()
    audience = State()
    delivery = State()
    schedule = State()
    price = State()
    location = State()
    edit_field = State()


class LessonEditor(StatesGroup):
    title = State()
    content = State()
    text_after_media = State()
    audience = State()
    edit_title = State()
    edit_body = State()
    edit_media = State()
    edit_position = State()
    add_question = State()


class FaqEditor(StatesGroup):
    question = State()
    answer = State()
    edit_question = State()
    edit_answer = State()


class Broadcast(StatesGroup):
    message = State()
    confirm = State()


class SettingsEditor(StatesGroup):
    text = State()
