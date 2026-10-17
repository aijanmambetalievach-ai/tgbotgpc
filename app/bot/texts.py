"""All user-facing Russian text in one place.

Pure presentation: no I/O, no aiogram imports, so it can be unit-tested and
reused by the notification service. Messages use Telegram HTML parse mode:
plain values go through :func:`escape_html`; fields documented as rich text
(admin-written course descriptions, lesson bodies, FAQ answers, consultant
replies) are already Telegram HTML and are embedded as is — never truncated,
because cutting HTML could leave an unclosed tag.
"""

from __future__ import annotations

from collections.abc import Sequence
from zoneinfo import ZoneInfo

from app.domain.text import escape_html, html_to_plain, truncate
from app.domain.timeutils import format_date, format_datetime
from app.models.application import Application, ApplicationMessage
from app.models.content import Course, FaqEntry, Lesson, LessonProgress, LessonQuestion
from app.models.enums import (
    APPLICATION_STATUS_ICONS,
    APPLICATION_STATUS_LABELS,
    APPLICATION_TYPE_ICONS,
    APPLICATION_TYPE_LABELS,
    AUDIENCE_LABELS,
    CATEGORY_ICONS,
    CATEGORY_LABELS,
    CONTACT_METHOD_LABELS,
    CONTENT_STATUS_LABELS,
    DELIVERY_LABELS,
    TOPIC_LABELS,
    ApplicationStatus,
    ApplicationType,
    ClientCategory,
    ContentStatus,
    MediaType,
)
from app.models.user import User

# --- client reply keyboard ---------------------------------------------------
BTN_TRAINING = "📚 Обучение"
BTN_CONSULTATION = "💬 Консультация"
BTN_MY_APPLICATIONS = "📋 Мои заявки"
BTN_FAQ = "❓ Частые вопросы"
BTN_ABOUT = "ℹ️ О нас и контакты"
BTN_PROFILE = "👤 Мои данные"

# --- admin reply keyboard ----------------------------------------------------
BTN_ADMIN_APPLICATIONS = "📥 Заявки"
BTN_ADMIN_STATS = "📊 Статистика"
BTN_ADMIN_COURSES = "🗓 Курсы"
BTN_ADMIN_LESSONS = "📖 Уроки"
BTN_ADMIN_FAQ = "❓ FAQ"
BTN_ADMIN_CLIENTS = "👥 Клиенты"
BTN_ADMIN_BROADCAST = "📣 Рассылка"
BTN_ADMIN_SETTINGS = "⚙️ Настройки"

BTN_SHARE_PHONE = "📱 Отправить мой номер"
BTN_CANCEL = "❌ Отмена"

# --- generic -------------------------------------------------------------------
ACCESS_BLOCKED = "Ваш доступ к боту приостановлен."
CANCELLED = "Действие отменено."
NOTHING_TO_CANCEL = "Сейчас нечего отменять."
STALE_CALLBACK = "Это сообщение устарело. Откройте раздел заново."
GENERIC_ERROR = "Произошла ошибка. Попробуйте еще раз или начните заново: /start"
RATE_LIMITED = "Слишком много действий подряд. Подождите несколько секунд."
EMPTY = "Пока пусто."
SKIP_HINT = "<i>Можно пропустить — кнопка ниже.</i>"
UNSUPPORTED_CONTENT = "Пришлите, пожалуйста, текст, фото или документ."
USE_BUTTONS = "Выберите вариант кнопкой выше или нажмите «Отмена»."


def welcome(name: str, brand: str) -> str:
    return (
        f"👋 Здравствуйте, {escape_html(name)}!\n\n"
        f"Это бот <b>{escape_html(brand)}</b> — обучение государственным закупкам "
        "и консультации для закупщиков и поставщиков.\n\n"
        f"{BTN_TRAINING} — живые курсы, уроки прямо в Telegram, индивидуальные занятия.\n"
        f"{BTN_CONSULTATION} — задайте вопрос специалисту.\n"
        f"{BTN_FAQ} — быстрые ответы на популярные вопросы."
    )


ASK_CATEGORY = (
    "Расскажите немного о себе, чтобы мы показывали подходящие материалы.\n\n<b>Кто вы?</b>"
)


def welcome_admin(name: str) -> str:
    return (
        f"👋 Здравствуйте, {escape_html(name)}!\n\n"
        "Вы вошли как <b>администратор</b>.\n"
        "Новые заявки и сообщения клиентов будут приходить сюда.\n\n"
        "Посмотреть бот глазами клиента: /client\nВернуться в админ-меню: /admin"
    )


HELP_CLIENT = (
    "<b>Что умеет бот</b>\n\n"
    f"{BTN_TRAINING}\n"
    "• 🗓 Живые курсы — занятия офлайн или в Zoom, запись в пару нажатий.\n"
    "• 📖 Уроки в боте — видео, тексты и тесты, проходите в своем темпе.\n"
    "• 🎯 Индивидуальное обучение — занятия один на один.\n\n"
    f"{BTN_CONSULTATION} — опишите вопрос, можно приложить скриншот или документ. "
    "Ответ специалиста придет сюда же.\n\n"
    f"{BTN_MY_APPLICATIONS} — статус ваших заявок и переписка.\n"
    f"{BTN_PROFILE} — имя, телефон и организация.\n\n"
    "Команды: /start, /help, /cancel"
)

HELP_ADMIN = (
    "<b>Админ-панель</b>\n\n"
    f"{BTN_ADMIN_APPLICATIONS} — записи на курсы, индивидуальное обучение и консультации. "
    "Отвечайте клиентам прямо из карточки заявки.\n"
    f"{BTN_ADMIN_COURSES} — живые курсы: создание, публикация, архив.\n"
    f"{BTN_ADMIN_LESSONS} — уроки в боте и тесты к ним.\n"
    f"{BTN_ADMIN_FAQ} — частые вопросы.\n"
    f"{BTN_ADMIN_CLIENTS} — список клиентов, блокировка, выгрузка в Excel.\n"
    f"{BTN_ADMIN_BROADCAST} — сообщение всем клиентам или одной категории.\n"
    f"{BTN_ADMIN_SETTINGS} — тексты «О нас» и «Контакты».\n\n"
    "Форматирование (жирный, курсив, ссылки) в описаниях, уроках и ответах сохраняется.\n\n"
    "Команды: /start, /help, /cancel, /client, /admin"
)


# =============================================================================
# Labels
# =============================================================================
def category_label(category: ClientCategory | None) -> str:
    if category is None:
        return "не указано"
    return f"{CATEGORY_ICONS[category]} {CATEGORY_LABELS[category]}"


def application_status(status: ApplicationStatus) -> str:
    return f"{APPLICATION_STATUS_ICONS[status]} {APPLICATION_STATUS_LABELS[status]}"


def application_subject(application: Application) -> str:
    """Course title or consultation topic — the "what" of an application."""
    if application.type is ApplicationType.COURSE:
        return application.course_title or "Курс"
    if application.topic is not None:
        return TOPIC_LABELS[application.topic]
    return APPLICATION_TYPE_LABELS[application.type]


# =============================================================================
# Training
# =============================================================================
TRAINING_MENU = (
    "📚 <b>Обучение</b>\n\n"
    "🗓 <b>Живые курсы</b> — групповые занятия офлайн или в Zoom по расписанию.\n"
    "📖 <b>Уроки в боте</b> — короткие уроки с видео и тестами, в своем темпе.\n"
    "🎯 <b>Индивидуальное обучение</b> — программа под ваши задачи, один на один."
)
NO_COURSES = (
    "🗓 Сейчас нет открытых наборов на курсы.\n\n"
    "Оставьте заявку на индивидуальное обучение или загляните позже."
)
NO_LESSONS = "📖 Уроки скоро появятся. Загляните позже!"


def courses_header(total: int, filtered: bool) -> str:
    note = "\n<i>Показаны курсы для вас.</i>" if filtered else ""
    return f"🗓 <b>Живые курсы</b>\nОткрыт набор: {total}{note}"


def course_row(course: Course) -> str:
    return truncate(course.title, 60)


def course_card(course: Course) -> str:
    lines = [f"🗓 <b>{escape_html(course.title)}</b>", ""]
    if course.description:
        lines += [course.description, ""]
    lines.append(f"👥 {AUDIENCE_LABELS[course.audience]}")
    lines.append(f"📍 Формат: {DELIVERY_LABELS[course.delivery]}")
    if course.schedule:
        lines.append(f"🗓 Расписание: {escape_html(course.schedule)}")
    if course.location:
        lines.append(f"🏫 Место: {escape_html(course.location)}")
    if course.price:
        lines.append(f"💳 Стоимость: {escape_html(course.price)}")
    return "\n".join(lines)


def lessons_header(total: int, done: int, filtered: bool) -> str:
    note = "\n<i>Показаны уроки для вас.</i>" if filtered else ""
    return f"📖 <b>Уроки в боте</b>\nВсего: {total} · пройдено на этой странице: {done}{note}"


def lesson_row(lesson: Lesson, completed: bool, questions: int) -> str:
    mark = "✅" if completed else MEDIA_ICONS.get(lesson.media_type, "📄")
    quiz = " · 📝" if questions else ""
    return f"{mark} {truncate(lesson.title, 50)}{quiz}"


MEDIA_ICONS: dict[MediaType | None, str] = {
    MediaType.VIDEO: "🎬",
    MediaType.PHOTO: "🖼",
    MediaType.DOCUMENT: "📎",
    None: "📄",
}


def lesson_text(
    lesson: Lesson,
    index: int,
    total: int,
    questions: int,
    progress: LessonProgress | None,
) -> str:
    lines = [f"📖 <b>Урок {index} из {total}</b>", f"<b>{escape_html(lesson.title)}</b>"]
    if lesson.body:
        lines += ["", lesson.body]
    lines.append("")
    if progress is not None:
        if progress.quiz_total:
            lines.append(f"✅ Урок пройден · тест: {progress.quiz_score}/{progress.quiz_total}")
        else:
            lines.append("✅ Урок пройден")
    elif questions:
        lines.append(f"📝 В конце урока — тест из {questions} вопр.")
    return "\n".join(lines)


def quiz_question(question: LessonQuestion, options: Sequence[str], number: int, total: int) -> str:
    lines = [f"📝 <b>Вопрос {number} из {total}</b>", "", escape_html(question.question), ""]
    lines += [f"{index}. {escape_html(option)}" for index, option in enumerate(options, start=1)]
    return "\n".join(lines)


def quiz_answer_feedback(
    question: LessonQuestion, options: Sequence[str], chosen: int, number: int, total: int
) -> str:
    correct = question.correct_option
    verdict = "✅ Верно!" if chosen == correct else "❌ Неверно."
    lines = [
        f"📝 <b>Вопрос {number} из {total}</b>",
        "",
        escape_html(question.question),
        "",
        verdict,
    ]
    if chosen != correct and 0 <= correct < len(options):
        lines.append(f"Правильный ответ: <b>{escape_html(options[correct])}</b>")
    return "\n".join(lines)


def quiz_result(score: int, total: int) -> str:
    ratio = score / total if total else 0
    if ratio == 1:
        praise = "🏆 Отлично — все ответы верные!"
    elif ratio >= 0.7:
        praise = "👍 Хороший результат!"
    else:
        praise = "📚 Стоит перечитать урок и попробовать еще раз."
    return f"📝 <b>Тест завершен</b>\n\nПравильных ответов: <b>{score} из {total}</b>\n{praise}"


LESSON_COMPLETED = "✅ Урок отмечен как пройденный."
ALL_LESSONS_DONE = "🎉 Это был последний урок. Отличная работа!"


# =============================================================================
# Applications — client side
# =============================================================================
INDIVIDUAL_INTRO = (
    "🎯 <b>Индивидуальное обучение</b>\n\n"
    "Занятия один на один по вашей программе: офлайн или в Zoom.\n\n"
    "Напишите, <b>что хотите изучить</b> — например: «Работа на портале с нуля, "
    "как создать объявление и провести оценку»."
)
ASK_PREFERRED_TIME = (
    "Когда вам удобно заниматься или созвониться?\n"
    "Например: «будни после 15:00» или «в субботу утром».\n\n" + SKIP_HINT
)
CONSULTATION_INTRO = "💬 <b>Консультация специалиста</b>\n\nВыберите тему вопроса:"


def consultation_ask_question(topic_label: str) -> str:
    return (
        f"Тема: <b>{escape_html(topic_label)}</b>\n\n"
        "Опишите ваш вопрос одним сообщением. Можно приложить скриншот или документ "
        "(подпись к файлу станет текстом вопроса).\n\n"
        "<i>Чем подробнее опишете ситуацию, тем точнее будет ответ.</i>"
    )


ASK_CONTACT_METHOD = "Как с вами удобнее связаться?"


def ask_course_comment(course_title: str) -> str:
    return (
        f"Запись на курс «{escape_html(course_title)}».\n\n"
        "Есть вопросы или пожелания? Напишите их сообщением.\n\n" + SKIP_HINT
    )


ASK_NAME = "Как к вам обращаться? Напишите имя и фамилию."
ASK_PHONE = (
    "Оставьте номер телефона, чтобы специалист мог связаться с вами.\n\n"
    f"Нажмите «{BTN_SHARE_PHONE}» внизу или напишите номер, например "
    "<code>0555 123 456</code>."
)
ASK_ORGANIZATION = "Укажите организацию (необязательно).\n\n" + SKIP_HINT


def confirm_application(
    kind: ApplicationType,
    user: User,
    *,
    subject: str | None = None,
    description: str = "",
    preferred_time: str = "",
    contact_method_label: str | None = None,
    has_attachment: bool = False,
) -> str:
    lines = [f"{APPLICATION_TYPE_ICONS[kind]} <b>Проверьте заявку</b>", ""]
    lines.append(f"Тип: {APPLICATION_TYPE_LABELS[kind]}")
    if subject:
        lines.append(
            f"{'Курс' if kind is ApplicationType.COURSE else 'Тема'}: {escape_html(subject)}"
        )
    if description:
        lines += ["", escape_html(truncate(description, 1500))]
    if has_attachment:
        lines.append("📎 Файл приложен")
    if preferred_time:
        lines.append(f"\n🕒 Удобное время: {escape_html(preferred_time)}")
    if contact_method_label:
        lines.append(f"Связь: {escape_html(contact_method_label)}")
    lines += [
        "",
        f"👤 {escape_html(user.full_name)}",
        f"📱 {escape_html(user.phone or '—')}",
    ]
    return "\n".join(lines)


def application_created(application: Application) -> str:
    return (
        f"✅ <b>Заявка {escape_html(application.number)} принята!</b>\n\n"
        "Специалист свяжется с вами в ближайшее время. Ответ придет сюда, в этот чат.\n"
        f"Статус заявки — в разделе {BTN_MY_APPLICATIONS}."
    )


def my_applications_header(total: int) -> str:
    return f"📋 <b>Мои заявки</b>\nВсего: {total}"


NO_APPLICATIONS = (
    "📋 У вас пока нет заявок.\n\n"
    f"Запишитесь на курс в разделе {BTN_TRAINING} или задайте вопрос в {BTN_CONSULTATION}."
)


def application_row(application: Application, client_name: str | None = None) -> str:
    icon = APPLICATION_STATUS_ICONS[application.status]
    kind = APPLICATION_TYPE_ICONS[application.type]
    who = f" · {truncate(client_name, 18)}" if client_name else ""
    return f"{icon} {kind} {truncate(application_subject(application), 28)}{who}"


THREAD_MESSAGE_PREVIEW = 600
THREAD_BUDGET = 2400


def _render_thread(
    messages: Sequence[ApplicationMessage], tz: ZoneInfo, client_label: str
) -> list[str]:
    """Newest messages that fit the budget, oldest first, always as plain text."""
    rendered: list[str] = []
    used = 0
    for message in reversed(messages):
        author = "👩‍💼 Специалист" if message.from_staff else client_label
        raw = html_to_plain(message.text) if message.from_staff else message.text
        body = escape_html(truncate(raw, THREAD_MESSAGE_PREVIEW)) if raw else ""
        attachment = f" {MEDIA_ICONS[message.media_type]}" if message.media_type else ""
        block = f"<b>{author}</b> · {format_datetime(message.created_at, tz)}{attachment}"
        if body:
            block += f"\n{body}"
        if used + len(block) > THREAD_BUDGET and rendered:
            rendered.append("<i>…более ранние сообщения скрыты</i>")
            break
        rendered.append(block)
        used += len(block)
    rendered.reverse()
    return rendered


def application_card(
    application: Application,
    messages: Sequence[ApplicationMessage],
    tz: ZoneInfo,
    *,
    client: User | None = None,
    assignee: User | None = None,
) -> str:
    """Thread view. ``client`` is passed for admins (shows contact details)."""
    icon = APPLICATION_TYPE_ICONS[application.type]
    lines = [
        f"{icon} <b>Заявка {escape_html(application.number)}</b>",
        f"{APPLICATION_TYPE_LABELS[application.type]}: "
        f"{escape_html(application_subject(application))}",
        f"Статус: {application_status(application.status)}",
        f"Создана: {format_datetime(application.created_at, tz)}",
    ]
    if client is not None:
        lines += [
            "",
            f"👤 {escape_html(client.full_name)}"
            + (f" (@{escape_html(client.telegram_username)})" if client.telegram_username else ""),
            f"📱 {escape_html(client.phone or '—')}",
            f"Категория: {category_label(client.category)}",
        ]
        if client.organization:
            lines.append(f"🏢 {escape_html(client.organization)}")
        lines.append(f"Связь: {CONTACT_METHOD_LABELS[application.contact_method]}")
        if assignee is not None:
            lines.append(f"Ведет: {escape_html(assignee.full_name)}")
    if application.preferred_time:
        lines.append(f"🕒 Удобное время: {escape_html(application.preferred_time)}")
    if application.status is ApplicationStatus.REJECTED and application.rejection_reason:
        lines.append(f"Причина: {escape_html(application.rejection_reason)}")

    client_label = "👤 Клиент" if client is not None else "👤 Вы"
    thread = _render_thread(messages, tz, client_label)
    if thread:
        lines += ["", "<b>Переписка</b>", "", "\n\n".join(thread)]
    return "\n".join(lines)


ASK_CLIENT_MESSAGE = "Напишите сообщение специалисту. Можно приложить фото или документ."
MESSAGE_SENT = "✅ Сообщение отправлено специалисту."
CONFIRM_CANCEL_APPLICATION = "Отменить заявку? Специалист увидит, что она больше не нужна."
APPLICATION_CANCELLED = "🚫 Заявка отменена."


def staff_reply_notification(application: Application, text_html: str) -> str:
    header = f"💬 <b>Ответ специалиста</b> по заявке {escape_html(application.number)}"
    return f"{header}\n\n{text_html}" if text_html else header


def status_notification(application: Application) -> str:
    number = escape_html(application.number)
    status = application.status
    if status is ApplicationStatus.IN_PROGRESS:
        return f"🟡 Заявка {number} взята в работу. Специалист скоро свяжется с вами."
    if status is ApplicationStatus.DONE:
        return (
            f"✅ Заявка {number} завершена.\n\n"
            f"Спасибо за обращение! Если появятся новые вопросы — {BTN_CONSULTATION}."
        )
    if status is ApplicationStatus.REJECTED:
        reason = escape_html(application.rejection_reason or "")
        return f"❌ Заявка {number} отклонена.\n\nПричина: {reason}"
    return f"Статус заявки {number}: {application_status(status)}"


# =============================================================================
# Applications — admin side
# =============================================================================
ADMIN_SCOPE_LABELS: dict[str, str] = {
    "new": "🆕 Новые",
    "active": "🟡 В работе",
    "closed": "📁 Закрытые",
    "all": "Все",
}


def admin_applications_header(scope: str, total: int) -> str:
    return f"📥 <b>Заявки · {ADMIN_SCOPE_LABELS.get(scope, '')}</b>\nНайдено: {total}"


def new_application_notification(application: Application, client: User) -> str:
    lines = [
        f"🔔 <b>Новая заявка {escape_html(application.number)}</b>",
        "",
        f"{APPLICATION_TYPE_ICONS[application.type]} {APPLICATION_TYPE_LABELS[application.type]}: "
        f"{escape_html(application_subject(application))}",
        "",
        f"👤 {escape_html(client.full_name)}"
        + (f" (@{escape_html(client.telegram_username)})" if client.telegram_username else ""),
        f"📱 {escape_html(client.phone or '—')}",
        f"Категория: {category_label(client.category)}",
        f"Связь: {CONTACT_METHOD_LABELS[application.contact_method]}",
    ]
    if application.preferred_time:
        lines.append(f"🕒 {escape_html(application.preferred_time)}")
    if application.description:
        lines += ["", escape_html(truncate(application.description, 1500))]
    return "\n".join(lines)


def client_message_notification(application: Application, client: User, text: str) -> str:
    header = (
        f"💬 <b>Сообщение по заявке {escape_html(application.number)}</b>\n"
        f"от {escape_html(client.full_name)}"
    )
    return f"{header}\n\n{escape_html(truncate(text, 3000))}" if text else header


def client_cancelled_notification(application: Application, client: User) -> str:
    return (
        f"🚫 Клиент {escape_html(client.full_name)} отменил заявку "
        f"{escape_html(application.number)}."
    )


ASK_STAFF_REPLY = (
    "✍️ Напишите ответ клиенту. Можно приложить фото, видео или документ.\n"
    "Форматирование (жирный, ссылки) сохранится."
)
ASK_REJECT_REASON = "Укажите причину отклонения — клиент увидит ее в уведомлении."


def reply_delivered(delivered: bool) -> str:
    if delivered:
        return "✅ Ответ отправлен клиенту."
    return "⚠️ Ответ сохранен, но доставить его не удалось — возможно, клиент остановил бота."


# =============================================================================
# FAQ / about / profile
# =============================================================================
NO_FAQ = f"❓ Раздел пока наполняется.\n\nЗадайте свой вопрос специалисту — {BTN_CONSULTATION}."
FAQ_HEADER = "❓ <b>Частые вопросы</b>\nВыберите вопрос:"


def faq_answer(entry: FaqEntry) -> str:
    return f"❓ <b>{escape_html(entry.question)}</b>\n\n{entry.answer}"


def about(about_html: str, contacts_html: str) -> str:
    return f"ℹ️ <b>О нас</b>\n\n{about_html}\n\n📞 <b>Контакты</b>\n\n{contacts_html}"


def profile(user: User) -> str:
    return (
        "👤 <b>Мои данные</b>\n\n"
        f"Имя: {escape_html(user.full_name)}\n"
        f"Телефон: {escape_html(user.phone or '—')}\n"
        f"Организация: {escape_html(user.organization or '—')}\n"
        f"Кто вы: {category_label(user.category)}"
    )


PROFILE_SAVED = "✅ Данные сохранены."


# =============================================================================
# Admin: content management
# =============================================================================
def admin_courses_header(total: int, archived: bool = False) -> str:
    title = "🗄 Архив курсов" if archived else "🗓 Курсы"
    return f"<b>{title}</b>\nВсего: {total}"


def admin_course_row(course: Course) -> str:
    icon = CONTENT_STATUS_LABELS[course.status].split(" ", 1)[0]
    return f"{icon} {truncate(course.title, 50)}"


def admin_course_card(course: Course, enrollments: int, share_link: str | None) -> str:
    lines = [
        course_card(course),
        "",
        "———",
        f"Статус: {CONTENT_STATUS_LABELS[course.status]}",
        f"Заявок на курс: {enrollments}",
    ]
    if share_link and course.status is ContentStatus.PUBLISHED:
        lines.append(f"Ссылка для рекламы: {escape_html(share_link)}")
    return "\n".join(lines)


COURSE_ASK_TITLE = "🗓 <b>Новый курс</b>\n\nШаг 1/7. Название курса:"
COURSE_ASK_DESCRIPTION = (
    "Шаг 2/7. Описание: программа, чему научатся, кто ведет.\n"
    "Форматирование сохранится.\n\n" + SKIP_HINT
)
COURSE_ASK_AUDIENCE = "Шаг 3/7. Для кого курс?"
COURSE_ASK_DELIVERY = "Шаг 4/7. Формат занятий:"
COURSE_ASK_SCHEDULE = (
    "Шаг 5/7. Расписание — как его увидит клиент.\n"
    "Например: <code>15–17 ноября, 10:00–13:00</code>\n\n" + SKIP_HINT
)
COURSE_ASK_PRICE = (
    "Шаг 6/7. Стоимость. Например: <code>4 500 сом</code> или <code>бесплатно</code>.\n\n"
    + SKIP_HINT
)
COURSE_ASK_LOCATION = (
    "Шаг 7/7. Адрес или «ссылка Zoom будет отправлена после записи».\n\n" + SKIP_HINT
)
COURSE_CREATED = (
    "✅ Курс создан как <b>черновик</b>. Проверьте карточку и нажмите «🟢 Опубликовать», "
    "чтобы клиенты его увидели."
)

CONTENT_STATUS_ANSWERS: dict[ContentStatus, str] = {
    ContentStatus.PUBLISHED: "🟢 Опубликовано — клиенты видят",
    ContentStatus.DRAFT: "📝 Черновик — клиенты не видят",
    ContentStatus.ARCHIVED: "🗄 Перенесено в архив",
}

COURSE_FIELD_PROMPTS: dict[str, str] = {
    "title": "Новое название курса:",
    "description": "Новое описание (форматирование сохранится):",
    "schedule": "Новое расписание:",
    "price": "Новая стоимость:",
    "location": "Новое место или ссылка:",
}


def admin_lessons_header(total: int, archived: bool = False) -> str:
    title = "🗄 Архив уроков" if archived else "📖 Уроки"
    return f"<b>{title}</b>\nВсего: {total}\nУроки идут по порядковому номеру."


def admin_lesson_row(lesson: Lesson, questions: int) -> str:
    icon = CONTENT_STATUS_LABELS[lesson.status].split(" ", 1)[0]
    quiz = f" · 📝{questions}" if questions else ""
    return f"{icon} {lesson.position}. {truncate(lesson.title, 40)}{quiz}"


def admin_lesson_card(lesson: Lesson, questions: Sequence[LessonQuestion]) -> str:
    media = {
        MediaType.VIDEO: "🎬 видео",
        MediaType.PHOTO: "🖼 фото",
        MediaType.DOCUMENT: "📎 документ",
    }
    lines = [
        f"📖 <b>{escape_html(lesson.title)}</b>",
        "",
        f"Статус: {CONTENT_STATUS_LABELS[lesson.status]}",
        f"Порядковый номер: {lesson.position}",
        f"Аудитория: {AUDIENCE_LABELS[lesson.audience]}",
        f"Файл: {media[lesson.media_type] if lesson.media_type else 'нет'}",
        f"Текст: {len(html_to_plain(lesson.body))} символов",
        f"Тест: {len(questions)} вопр.",
    ]
    if lesson.body:
        lines += ["", escape_html(truncate(html_to_plain(lesson.body), 500))]
    return "\n".join(lines)


LESSON_ASK_TITLE = "📖 <b>Новый урок</b>\n\nШаг 1/3. Название урока:"
LESSON_ASK_CONTENT = (
    "Шаг 2/3. Пришлите материал урока:\n"
    "• текст (форматирование сохранится), или\n"
    "• видео / фото / документ — подпись к файлу станет текстом урока."
)
LESSON_ASK_TEXT_AFTER_MEDIA = (
    "Файл получен. Добавьте текст к уроку (конспект, пояснения).\n\n" + SKIP_HINT
)
LESSON_ASK_AUDIENCE = "Шаг 3/3. Для кого урок?"
LESSON_CREATED = (
    "✅ Урок создан как <b>черновик</b>. Добавьте тест (по желанию) и нажмите «🟢 Опубликовать»."
)
LESSON_ASK_NEW_TITLE = "Новое название урока:"
LESSON_ASK_NEW_BODY = "Новый текст урока (форматирование сохранится):"
LESSON_ASK_NEW_MEDIA = "Пришлите новое видео, фото или документ для урока:"
LESSON_ASK_POSITION = "Порядковый номер урока (число). Уроки показываются по возрастанию:"
CONFIRM_DELETE_LESSON = "Удалить урок вместе с тестом и прогрессом клиентов? Это необратимо."
LESSON_DELETED = "🗑 Урок удален."


def admin_quiz(lesson: Lesson, questions: Sequence[LessonQuestion]) -> str:
    lines = [f"📝 <b>Тест к уроку «{escape_html(lesson.title)}»</b>", ""]
    if not questions:
        lines.append("Вопросов пока нет.")
    for number, question in enumerate(questions, start=1):
        lines.append(f"<b>{number}. {escape_html(truncate(question.question, 200))}</b>")
        for index, option in enumerate(question.options):
            mark = "✅" if index == question.correct_option else "▫️"
            lines.append(f"   {mark} {escape_html(truncate(str(option), 100))}")
    return "\n".join(lines)


QUIZ_ASK_QUESTION = (
    "Отправьте вопрос в таком виде:\n\n"
    "<code>Сколько членов должно быть в закупочной комиссии?\n"
    "- Четное число\n"
    "+ Нечетное число, не менее трех\n"
    "- Любое</code>\n\n"
    "Первая строка — вопрос. Дальше варианты: «+» — правильный, «-» — неправильные."
)


def question_added(total: int) -> str:
    return (
        f"✅ Вопрос добавлен. В тесте: {total}.\n\nОтправьте следующий вопрос или нажмите «Готово»."
    )


def admin_faq_header(total: int) -> str:
    return f"❓ <b>Частые вопросы</b>\nВсего: {total}"


def admin_faq_row(entry: FaqEntry) -> str:
    icon = "👁" if entry.is_published else "🙈"
    return f"{icon} {truncate(entry.question, 50)}"


def admin_faq_card(entry: FaqEntry) -> str:
    state = "👁 показывается клиентам" if entry.is_published else "🙈 скрыт"
    return f"{faq_answer(entry)}\n\n———\n{state}"


FAQ_ASK_QUESTION = "Текст вопроса:"
FAQ_ASK_ANSWER = "Ответ (форматирование сохранится):"
FAQ_DELETED = "🗑 Вопрос удален."


# =============================================================================
# Admin: clients, broadcast, settings, statistics
# =============================================================================
CLIENT_FILTER_LABELS: dict[str, str] = {
    "all": "Все",
    ClientCategory.PURCHASER: "🏛 Закупщики",
    ClientCategory.SUPPLIER: "🏢 Поставщики",
    ClientCategory.BEGINNER: "🌱 Новички",
}


def admin_clients_header(total: int, filter_key: str) -> str:
    return f"👥 <b>Клиенты · {CLIENT_FILTER_LABELS.get(filter_key, 'Все')}</b>\nВсего: {total}"


def admin_client_row(user: User) -> str:
    icon = CATEGORY_ICONS[user.category] if user.category else "👤"
    blocked = " 🚫" if not user.is_active else ""
    return f"{icon} {truncate(user.full_name, 40)}{blocked}"


def admin_client_card(user: User, applications: int, tz: ZoneInfo) -> str:
    lines = [
        f"👤 <b>{escape_html(user.full_name)}</b>",
        "",
        f"Категория: {category_label(user.category)}",
        f"Телефон: {escape_html(user.phone or '—')}",
        f"Организация: {escape_html(user.organization or '—')}",
        "Telegram: "
        + (f"@{escape_html(user.telegram_username)}" if user.telegram_username else "—"),
        f"С нами с: {format_date(user.created_at, tz)}",
        f"Заявок: {applications}",
        f"Доступ: {'✅ активен' if user.is_active else '🚫 заблокирован'}",
    ]
    return "\n".join(lines)


BROADCAST_CHOOSE_AUDIENCE = "📣 <b>Рассылка</b>\n\nКому отправить сообщение?"


def broadcast_ask_message(audience_label: str) -> str:
    return (
        f"Получатели: <b>{escape_html(audience_label)}</b>\n\n"
        "Отправьте сообщение для рассылки: текст, фото, видео или документ с подписью. "
        "Оно уйдет клиентам ровно в таком виде."
    )


def broadcast_preview(audience_label: str, recipients: int) -> str:
    return (
        "👆 Так сообщение увидят клиенты.\n\n"
        f"Получатели: <b>{escape_html(audience_label)}</b> — {recipients} чел.\n"
        "Отправить?"
    )


def broadcast_done(delivered: int, total: int) -> str:
    return f"📣 Рассылка завершена: доставлено {delivered} из {total}."


BROADCAST_STARTED = "⏳ Рассылка началась. Сообщу, когда закончится."
BROADCAST_NO_RECIPIENTS = "В этой категории пока нет клиентов."

SETTINGS_MENU = (
    f"⚙️ <b>Настройки</b>\n\nИзмените тексты, которые клиенты видят в разделе «{BTN_ABOUT}»."
)
SETTINGS_ASK: dict[str, str] = {
    "about": "Отправьте новый текст «О нас» (форматирование сохранится):",
    "contacts": "Отправьте новые контакты: телефон, адрес, сайт, соцсети:",
}
SETTINGS_SAVED = "✅ Сохранено. Так это увидят клиенты:"


def statistics(
    clients_total: int,
    by_category: dict[ClientCategory | None, int],
    by_status: dict[ApplicationStatus, int],
    last_7_days: dict[ApplicationType, int],
    lessons_completed: int,
) -> str:
    lines = ["📊 <b>Статистика</b>", "", f"👥 Клиентов: <b>{clients_total}</b>"]
    for category in ClientCategory:
        lines.append(f"   {category_label(category)}: {by_category.get(category, 0)}")
    if by_category.get(None):
        lines.append(f"   не указали: {by_category[None]}")
    lines += ["", "📥 <b>Заявки</b>"]
    for status in ApplicationStatus:
        lines.append(f"   {application_status(status)}: {by_status.get(status, 0)}")
    lines += ["", "🗓 <b>За 7 дней</b>"]
    for kind in ApplicationType:
        lines.append(
            f"   {APPLICATION_TYPE_ICONS[kind]} {APPLICATION_TYPE_LABELS[kind]}: "
            f"{last_7_days.get(kind, 0)}"
        )
    lines += ["", f"📖 Пройдено уроков: {lessons_completed}"]
    return "\n".join(lines)
