"""Persistence for courses, lessons, quizzes, progress, FAQ and editable texts."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import Select, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.application import Application
from app.models.content import (
    BotText,
    Course,
    FaqEntry,
    Lesson,
    LessonProgress,
    LessonQuestion,
)
from app.models.enums import ApplicationType, Audience, ContentStatus
from app.repositories.base import Page, normalize_page, offset_for


async def _page[T](
    session: AsyncSession, stmt: Select[tuple[T]], page: int, page_size: int
) -> Page[T]:
    total = int(
        (await session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    )
    page = normalize_page(page, page_size, total)
    rows = list(
        (await session.execute(stmt.offset(offset_for(page, page_size)).limit(page_size)))
        .scalars()
        .all()
    )
    return Page(items=rows, total=total, page=page, page_size=page_size)


class CourseRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, course_id: int) -> Course | None:
        return await self.session.get(Course, course_id)

    async def list_page(
        self,
        *,
        statuses: Sequence[ContentStatus],
        audiences: Sequence[Audience] | None = None,
        page: int = 1,
        page_size: int = 10,
    ) -> Page[Course]:
        stmt = select(Course).where(Course.status.in_(list(statuses)))
        if audiences is not None:
            stmt = stmt.where(Course.audience.in_(list(audiences)))
        stmt = stmt.order_by(Course.position.asc(), Course.id.desc())
        return await _page(self.session, stmt, page, page_size)

    async def count_enrollments(self, course_id: int) -> int:
        stmt = select(func.count(Application.id)).where(
            Application.course_id == course_id, Application.type == ApplicationType.COURSE
        )
        return int((await self.session.execute(stmt)).scalar_one())

    def add(self, course: Course) -> Course:
        self.session.add(course)
        return course


class LessonRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, lesson_id: int) -> Lesson | None:
        return await self.session.get(Lesson, lesson_id)

    async def list_page(
        self,
        *,
        statuses: Sequence[ContentStatus],
        audiences: Sequence[Audience] | None = None,
        page: int = 1,
        page_size: int = 10,
    ) -> Page[Lesson]:
        return await _page(self.session, self._stmt(statuses, audiences), page, page_size)

    async def list_ids(
        self, *, statuses: Sequence[ContentStatus], audiences: Sequence[Audience] | None = None
    ) -> list[int]:
        """Ordered ids, used for "previous / next lesson" navigation."""
        stmt = self._stmt(statuses, audiences).with_only_columns(Lesson.id)
        return [int(row) for row in (await self.session.execute(stmt)).scalars().all()]

    @staticmethod
    def _stmt(
        statuses: Sequence[ContentStatus], audiences: Sequence[Audience] | None
    ) -> Select[tuple[Lesson]]:
        stmt = select(Lesson).where(Lesson.status.in_(list(statuses)))
        if audiences is not None:
            stmt = stmt.where(Lesson.audience.in_(list(audiences)))
        return stmt.order_by(Lesson.position.asc(), Lesson.id.asc())

    async def next_position(self) -> int:
        stmt = select(func.coalesce(func.max(Lesson.position), 0))
        return int((await self.session.execute(stmt)).scalar_one()) + 1

    def add(self, lesson: Lesson) -> Lesson:
        self.session.add(lesson)
        return lesson

    async def delete(self, lesson: Lesson) -> None:
        await self.session.delete(lesson)

    # -- quiz ----------------------------------------------------------------
    async def questions(self, lesson_id: int) -> list[LessonQuestion]:
        stmt = (
            select(LessonQuestion)
            .where(LessonQuestion.lesson_id == lesson_id)
            .order_by(LessonQuestion.position.asc(), LessonQuestion.id.asc())
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def count_questions(self, lesson_ids: Sequence[int]) -> dict[int, int]:
        if not lesson_ids:
            return {}
        stmt = (
            select(LessonQuestion.lesson_id, func.count(LessonQuestion.id))
            .where(LessonQuestion.lesson_id.in_(list(lesson_ids)))
            .group_by(LessonQuestion.lesson_id)
        )
        return {int(lid): int(count) for lid, count in await self.session.execute(stmt)}

    def add_question(self, question: LessonQuestion) -> LessonQuestion:
        self.session.add(question)
        return question

    async def clear_questions(self, lesson_id: int) -> None:
        await self.session.execute(
            delete(LessonQuestion).where(LessonQuestion.lesson_id == lesson_id)
        )

    # -- progress ------------------------------------------------------------
    async def progress(self, user_id: int, lesson_id: int) -> LessonProgress | None:
        stmt = select(LessonProgress).where(
            LessonProgress.user_id == user_id, LessonProgress.lesson_id == lesson_id
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def completed_ids(self, user_id: int, lesson_ids: Sequence[int]) -> set[int]:
        if not lesson_ids:
            return set()
        stmt = select(LessonProgress.lesson_id).where(
            LessonProgress.user_id == user_id, LessonProgress.lesson_id.in_(list(lesson_ids))
        )
        return {int(row) for row in (await self.session.execute(stmt)).scalars().all()}

    def add_progress(self, progress: LessonProgress) -> LessonProgress:
        self.session.add(progress)
        return progress

    async def count_completions(self) -> int:
        stmt = select(func.count(LessonProgress.id))
        return int((await self.session.execute(stmt)).scalar_one())


class FaqRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, entry_id: int) -> FaqEntry | None:
        return await self.session.get(FaqEntry, entry_id)

    async def list_page(
        self, *, published_only: bool, page: int = 1, page_size: int = 10
    ) -> Page[FaqEntry]:
        stmt = select(FaqEntry)
        if published_only:
            stmt = stmt.where(FaqEntry.is_published.is_(True))
        stmt = stmt.order_by(FaqEntry.position.asc(), FaqEntry.id.asc())
        return await _page(self.session, stmt, page, page_size)

    async def next_position(self) -> int:
        stmt = select(func.coalesce(func.max(FaqEntry.position), 0))
        return int((await self.session.execute(stmt)).scalar_one()) + 1

    def add(self, entry: FaqEntry) -> FaqEntry:
        self.session.add(entry)
        return entry

    async def delete(self, entry: FaqEntry) -> None:
        await self.session.delete(entry)


class BotTextRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, key: str) -> str | None:
        row = await self.session.get(BotText, key)
        return row.value if row is not None else None

    async def set(self, key: str, value: str) -> None:
        row = await self.session.get(BotText, key)
        if row is None:
            self.session.add(BotText(key=key, value=value))
        else:
            row.value = value
