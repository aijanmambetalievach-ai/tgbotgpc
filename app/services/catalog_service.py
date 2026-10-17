"""Training content: courses, lessons with quizzes, FAQ and editable texts.

Rich text fields (course descriptions, lesson bodies, FAQ answers, "about" and
"contacts") are stored as Telegram HTML produced by aiogram's
``Message.html_text`` from what an *admin* typed — so bold, italics and links
survive. Clients never write into those fields. Titles are plain text and are
escaped when rendered.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import Settings, get_settings
from app.domain.exceptions import ContentUnavailableError, NotFoundError, ValidationError
from app.domain.permissions import require_active, require_admin
from app.domain.quiz import parse_question
from app.domain.text import normalize_unicode, sanitize_text
from app.models.audit_log import AuditAction
from app.models.content import (
    BotTextKey,
    Course,
    FaqEntry,
    Lesson,
    LessonProgress,
    LessonQuestion,
)
from app.models.enums import (
    CATEGORY_AUDIENCES,
    Audience,
    ContentStatus,
    CourseDelivery,
    MediaType,
)
from app.models.user import User
from app.repositories.audit import AuditRepository
from app.repositories.base import Page
from app.repositories.content import (
    BotTextRepository,
    CourseRepository,
    FaqRepository,
    LessonRepository,
)

logger = logging.getLogger(__name__)

MAX_SHORT_FIELD = 300
MAX_PRICE_LENGTH = 120
MAX_QUESTIONS_PER_LESSON = 20

PUBLISHED = (ContentStatus.PUBLISHED,)
ADMIN_VISIBLE = (ContentStatus.DRAFT, ContentStatus.PUBLISHED)

DEFAULT_TEXTS: dict[str, str] = {
    BotTextKey.ABOUT: (
        "Мы обучаем работе с государственными закупками Кыргызской Республики "
        "и консультируем закупщиков и поставщиков: портал госзакупок, план закупок, "
        "конкурсная документация, подача заявок, договоры и жалобы.\n\n"
        "<i>Этот текст можно изменить в разделе ⚙️ Настройки.</i>"
    ),
    BotTextKey.CONTACTS: (
        "Свяжитесь с нами любым удобным способом или оставьте заявку на консультацию "
        "прямо в боте.\n\n"
        "<i>Контакты можно указать в разделе ⚙️ Настройки.</i>"
    ),
}

COURSE_TEXT_FIELDS = ("title", "description", "schedule", "price", "location")


@dataclass(slots=True)
class CourseInput:
    title: str
    description: str = ""
    audience: Audience = Audience.ALL
    delivery: CourseDelivery = CourseDelivery.ONLINE
    schedule: str = ""
    price: str = ""
    location: str = ""


@dataclass(slots=True)
class LessonInput:
    title: str
    body: str = ""
    audience: Audience = Audience.ALL
    media_type: MediaType | None = None
    media_file_id: str | None = None


@dataclass(frozen=True, slots=True)
class CourseCard:
    course: Course
    enrollments: int


@dataclass(frozen=True, slots=True)
class LessonListing:
    page: Page[Lesson]
    completed: set[int] = field(default_factory=set)
    question_counts: dict[int, int] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class LessonView:
    lesson: Lesson
    questions: list[LessonQuestion]
    progress: LessonProgress | None
    index: int
    total: int
    prev_id: int | None
    next_id: int | None


def clean_rich_text(raw: str | None, max_length: int, *, required: bool = True) -> str:
    """Validate admin-provided Telegram HTML.

    Unlike plain text it is never truncated — cutting HTML could leave an
    unclosed tag and make Telegram reject the whole message.
    """
    value = normalize_unicode(raw or "").strip()
    if required and not value:
        raise ValidationError("Текст не может быть пустым.")
    if len(value) > max_length:
        raise ValidationError(
            f"Текст слишком длинный ({len(value)} символов, максимум {max_length}). "
            "Сократите его или разделите на несколько уроков."
        )
    return value


class CatalogService:
    def __init__(self, session: AsyncSession, settings: Settings | None = None) -> None:
        self.session = session
        self.settings = settings or get_settings()
        self.courses = CourseRepository(session)
        self.lessons = LessonRepository(session)
        self.faq = FaqRepository(session)
        self.texts = BotTextRepository(session)
        self.audit = AuditRepository(session)

    # ======================================================================
    # Courses
    # ======================================================================
    async def list_courses(self, user: User, page: int = 1, show_all: bool = False) -> Page[Course]:
        """Published courses for clients (filtered by category); everything
        but the archive for admins."""
        require_active(user)
        if user.is_admin:
            return await self.courses.list_page(
                statuses=ADMIN_VISIBLE, page=page, page_size=self.settings.page_size
            )
        return await self.courses.list_page(
            statuses=PUBLISHED,
            audiences=None if show_all else CATEGORY_AUDIENCES[user.category],
            page=page,
            page_size=self.settings.page_size,
        )

    async def list_archived_courses(self, actor: User, page: int = 1) -> Page[Course]:
        require_admin(actor)
        return await self.courses.list_page(
            statuses=(ContentStatus.ARCHIVED,), page=page, page_size=self.settings.page_size
        )

    async def get_course(self, user: User, course_id: int) -> CourseCard:
        require_active(user)
        course = await self.courses.get(course_id)
        if course is None:
            raise NotFoundError("Курс не найден.")
        if not user.is_admin and course.status is not ContentStatus.PUBLISHED:
            raise ContentUnavailableError("Запись на этот курс закрыта.")
        enrollments = await self.courses.count_enrollments(course_id) if user.is_admin else 0
        return CourseCard(course=course, enrollments=enrollments)

    async def create_course(self, actor: User, data: CourseInput) -> Course:
        require_admin(actor)
        course = Course(
            title=self._title(data.title),
            description=clean_rich_text(
                data.description, self.settings.max_text_length, required=False
            ),
            audience=data.audience,
            delivery=data.delivery,
            schedule=sanitize_text(data.schedule, MAX_SHORT_FIELD),
            price=sanitize_text(data.price, MAX_PRICE_LENGTH),
            location=sanitize_text(data.location, MAX_SHORT_FIELD),
            status=ContentStatus.DRAFT,
            created_by=actor.id,
        )
        self.courses.add(course)
        await self.session.flush()
        self._log(actor, AuditAction.COURSE_SAVED, "course", course.id, {"title": course.title})
        await self.session.commit()
        return course

    async def update_course_text(
        self, actor: User, course_id: int, field_name: str, value: str
    ) -> Course:
        require_admin(actor)
        if field_name not in COURSE_TEXT_FIELDS:
            raise ValidationError("Это поле нельзя изменить.")
        course = await self._course(course_id)
        if field_name == "title":
            course.title = self._title(value)
        elif field_name == "description":
            course.description = clean_rich_text(
                value, self.settings.max_text_length, required=False
            )
        elif field_name == "price":
            course.price = sanitize_text(value, MAX_PRICE_LENGTH)
        else:
            setattr(course, field_name, sanitize_text(value, MAX_SHORT_FIELD))
        self._log(actor, AuditAction.COURSE_SAVED, "course", course.id, {"field": field_name})
        await self.session.commit()
        return course

    async def update_course_options(
        self,
        actor: User,
        course_id: int,
        *,
        audience: Audience | None = None,
        delivery: CourseDelivery | None = None,
    ) -> Course:
        require_admin(actor)
        course = await self._course(course_id)
        if audience is not None:
            course.audience = audience
        if delivery is not None:
            course.delivery = delivery
        self._log(actor, AuditAction.COURSE_SAVED, "course", course.id, {"options": True})
        await self.session.commit()
        return course

    async def set_course_status(self, actor: User, course_id: int, status: ContentStatus) -> Course:
        require_admin(actor)
        course = await self._course(course_id)
        course.status = status
        self._log(
            actor, AuditAction.COURSE_STATUS_CHANGED, "course", course.id, {"status": str(status)}
        )
        await self.session.commit()
        return course

    async def _course(self, course_id: int) -> Course:
        course = await self.courses.get(course_id)
        if course is None:
            raise NotFoundError("Курс не найден.")
        return course

    # ======================================================================
    # Lessons
    # ======================================================================
    def _lesson_scope(
        self, user: User, show_all: bool
    ) -> tuple[Sequence[ContentStatus], Sequence[Audience] | None]:
        if user.is_admin:
            return ADMIN_VISIBLE, None
        return PUBLISHED, None if show_all else CATEGORY_AUDIENCES[user.category]

    async def list_lessons(
        self, user: User, page: int = 1, show_all: bool = False
    ) -> LessonListing:
        require_active(user)
        statuses, audiences = self._lesson_scope(user, show_all)
        listing = await self.lessons.list_page(
            statuses=statuses, audiences=audiences, page=page, page_size=self.settings.page_size
        )
        ids = [lesson.id for lesson in listing.items]
        return LessonListing(
            page=listing,
            completed=await self.lessons.completed_ids(user.id, ids),
            question_counts=await self.lessons.count_questions(ids),
        )

    async def question_counts(self, lesson_ids: Sequence[int]) -> dict[int, int]:
        return await self.lessons.count_questions(lesson_ids)

    async def list_archived_lessons(self, actor: User, page: int = 1) -> Page[Lesson]:
        require_admin(actor)
        return await self.lessons.list_page(
            statuses=(ContentStatus.ARCHIVED,), page=page, page_size=self.settings.page_size
        )

    async def view_lesson(self, user: User, lesson_id: int, show_all: bool = False) -> LessonView:
        require_active(user)
        lesson = await self.lessons.get(lesson_id)
        if lesson is None:
            raise NotFoundError("Урок не найден.")
        if not user.is_admin and lesson.status is not ContentStatus.PUBLISHED:
            raise ContentUnavailableError("Этот урок сейчас недоступен.")

        statuses, audiences = self._lesson_scope(user, show_all)
        ids = await self.lessons.list_ids(statuses=statuses, audiences=audiences)
        if lesson.id not in ids:
            # Opened from outside the client's filtered list (e.g. "show all"
            # was switched off) — navigate through the full published list.
            ids = await self.lessons.list_ids(statuses=statuses)
        index = ids.index(lesson.id) if lesson.id in ids else 0
        return LessonView(
            lesson=lesson,
            questions=await self.lessons.questions(lesson.id),
            progress=await self.lessons.progress(user.id, lesson.id),
            index=index + 1,
            total=max(len(ids), 1),
            prev_id=ids[index - 1] if lesson.id in ids and index > 0 else None,
            next_id=ids[index + 1] if lesson.id in ids and index + 1 < len(ids) else None,
        )

    async def complete_lesson(
        self,
        user: User,
        lesson_id: int,
        quiz_score: int | None = None,
        quiz_total: int | None = None,
    ) -> LessonProgress:
        """Mark a lesson as finished; re-taking a quiz keeps the best score."""
        require_active(user)
        lesson = await self.lessons.get(lesson_id)
        if lesson is None or (not user.is_admin and lesson.status is not ContentStatus.PUBLISHED):
            raise ContentUnavailableError("Этот урок сейчас недоступен.")
        progress = await self.lessons.progress(user.id, lesson_id)
        if progress is None:
            progress = self.lessons.add_progress(
                LessonProgress(
                    user_id=user.id,
                    lesson_id=lesson_id,
                    quiz_score=quiz_score,
                    quiz_total=quiz_total,
                )
            )
        elif quiz_score is not None and (
            progress.quiz_score is None or quiz_score >= progress.quiz_score
        ):
            progress.quiz_score = quiz_score
            progress.quiz_total = quiz_total
        try:
            await self.session.commit()
        except IntegrityError:
            # Double tap on "finish": the first one already recorded it.
            await self.session.rollback()
            existing = await self.lessons.progress(user.id, lesson_id)
            if existing is None:  # pragma: no cover - defensive
                raise
            return existing
        return progress

    async def create_lesson(self, actor: User, data: LessonInput) -> Lesson:
        require_admin(actor)
        lesson = Lesson(
            title=self._title(data.title),
            body=clean_rich_text(data.body, self.settings.max_text_length, required=False),
            audience=data.audience,
            media_type=data.media_type if data.media_file_id else None,
            media_file_id=data.media_file_id,
            position=await self.lessons.next_position(),
            status=ContentStatus.DRAFT,
            created_by=actor.id,
        )
        if not lesson.body and not lesson.media_file_id:
            raise ValidationError("Добавьте в урок текст или файл.")
        self.lessons.add(lesson)
        await self.session.flush()
        self._log(actor, AuditAction.LESSON_SAVED, "lesson", lesson.id, {"title": lesson.title})
        await self.session.commit()
        return lesson

    async def update_lesson(
        self,
        actor: User,
        lesson_id: int,
        *,
        title: str | None = None,
        body: str | None = None,
        audience: Audience | None = None,
        position: int | None = None,
        media: tuple[MediaType, str] | None = None,
        remove_media: bool = False,
    ) -> Lesson:
        require_admin(actor)
        lesson = await self._lesson(lesson_id)
        if title is not None:
            lesson.title = self._title(title)
        if body is not None:
            lesson.body = clean_rich_text(body, self.settings.max_text_length, required=False)
        if audience is not None:
            lesson.audience = audience
        if position is not None:
            if not 0 <= position <= 100_000:
                raise ValidationError("Порядковый номер должен быть от 0 до 100000.")
            lesson.position = position
        if media is not None:
            lesson.media_type, lesson.media_file_id = media
        elif remove_media:
            lesson.media_type = None
            lesson.media_file_id = None
        if not lesson.body and not lesson.media_file_id:
            raise ValidationError("В уроке должен остаться текст или файл.")
        self._log(actor, AuditAction.LESSON_SAVED, "lesson", lesson.id, {"edited": True})
        await self.session.commit()
        return lesson

    async def set_lesson_status(self, actor: User, lesson_id: int, status: ContentStatus) -> Lesson:
        require_admin(actor)
        lesson = await self._lesson(lesson_id)
        lesson.status = status
        self._log(
            actor, AuditAction.LESSON_STATUS_CHANGED, "lesson", lesson.id, {"status": str(status)}
        )
        await self.session.commit()
        return lesson

    async def delete_lesson(self, actor: User, lesson_id: int) -> None:
        require_admin(actor)
        lesson = await self._lesson(lesson_id)
        self._log(actor, AuditAction.LESSON_DELETED, "lesson", lesson.id, {"title": lesson.title})
        await self.lessons.delete(lesson)
        await self.session.commit()

    async def add_question(self, actor: User, lesson_id: int, raw: str) -> LessonQuestion:
        require_admin(actor)
        lesson = await self._lesson(lesson_id)
        existing = await self.lessons.questions(lesson.id)
        if len(existing) >= MAX_QUESTIONS_PER_LESSON:
            raise ValidationError(
                f"В одном уроке может быть не больше {MAX_QUESTIONS_PER_LESSON} вопросов."
            )
        parsed = parse_question(raw)
        question = self.lessons.add_question(
            LessonQuestion(
                lesson_id=lesson.id,
                question=parsed.question,
                options=list(parsed.options),
                correct_option=parsed.correct_option,
                position=len(existing) + 1,
            )
        )
        self._log(actor, AuditAction.QUIZ_CHANGED, "lesson", lesson.id, {"added": 1})
        await self.session.commit()
        return question

    async def clear_quiz(self, actor: User, lesson_id: int) -> None:
        require_admin(actor)
        lesson = await self._lesson(lesson_id)
        await self.lessons.clear_questions(lesson.id)
        self._log(actor, AuditAction.QUIZ_CHANGED, "lesson", lesson.id, {"cleared": True})
        await self.session.commit()

    async def _lesson(self, lesson_id: int) -> Lesson:
        lesson = await self.lessons.get(lesson_id)
        if lesson is None:
            raise NotFoundError("Урок не найден.")
        return lesson

    # ======================================================================
    # FAQ
    # ======================================================================
    async def list_faq(self, user: User, page: int = 1) -> Page[FaqEntry]:
        require_active(user)
        return await self.faq.list_page(
            published_only=not user.is_admin, page=page, page_size=self.settings.page_size
        )

    async def get_faq(self, user: User, entry_id: int) -> FaqEntry:
        require_active(user)
        entry = await self.faq.get(entry_id)
        if entry is None or (not user.is_admin and not entry.is_published):
            raise NotFoundError("Вопрос не найден.")
        return entry

    async def save_faq(
        self,
        actor: User,
        *,
        entry_id: int | None = None,
        question: str | None = None,
        answer: str | None = None,
    ) -> FaqEntry:
        require_admin(actor)
        if entry_id is None:
            if question is None or answer is None:
                raise ValidationError("Нужны и вопрос, и ответ.")
            entry = self.faq.add(
                FaqEntry(
                    question=self._title(question),
                    answer=clean_rich_text(answer, self.settings.max_text_length),
                    position=await self.faq.next_position(),
                    is_published=True,
                )
            )
        else:
            entry = await self._faq(entry_id)
            if question is not None:
                entry.question = self._title(question)
            if answer is not None:
                entry.answer = clean_rich_text(answer, self.settings.max_text_length)
        await self.session.flush()
        self._log(actor, AuditAction.FAQ_CHANGED, "faq", entry.id, {"saved": True})
        await self.session.commit()
        return entry

    async def toggle_faq(self, actor: User, entry_id: int) -> FaqEntry:
        require_admin(actor)
        entry = await self._faq(entry_id)
        entry.is_published = not entry.is_published
        self._log(
            actor, AuditAction.FAQ_CHANGED, "faq", entry.id, {"published": entry.is_published}
        )
        await self.session.commit()
        return entry

    async def delete_faq(self, actor: User, entry_id: int) -> None:
        require_admin(actor)
        entry = await self._faq(entry_id)
        self._log(actor, AuditAction.FAQ_CHANGED, "faq", entry.id, {"deleted": True})
        await self.faq.delete(entry)
        await self.session.commit()

    async def _faq(self, entry_id: int) -> FaqEntry:
        entry = await self.faq.get(entry_id)
        if entry is None:
            raise NotFoundError("Вопрос не найден.")
        return entry

    # ======================================================================
    # Editable texts
    # ======================================================================
    async def get_text(self, key: str) -> str:
        stored = await self.texts.get(key)
        return stored if stored else DEFAULT_TEXTS.get(key, "")

    async def set_text(self, actor: User, key: str, value: str) -> str:
        require_admin(actor)
        if key not in DEFAULT_TEXTS:
            raise ValidationError("Неизвестный раздел.")
        clean = clean_rich_text(value, self.settings.max_text_length)
        await self.texts.set(key, clean)
        self._log(actor, AuditAction.BOT_TEXT_CHANGED, "bot_text", None, {"key": key})
        await self.session.commit()
        return clean

    # ======================================================================
    # helpers
    # ======================================================================
    def _title(self, raw: str) -> str:
        title = sanitize_text(raw, self.settings.max_title_length)
        if not title:
            raise ValidationError("Название не может быть пустым.")
        return title

    def _log(
        self,
        actor: User,
        action: str,
        entity_type: str,
        entity_id: int | None,
        payload: dict[str, object],
    ) -> None:
        self.audit.log(
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            actor_user_id=actor.id,
            payload=payload,
        )
