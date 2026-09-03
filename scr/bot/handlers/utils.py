import functools
from typing import List, Dict, Any, Optional, Callable
from telegram import Update, InlineKeyboardMarkup
from telegram.error import BadRequest, Forbidden, RetryAfter, TimedOut
from telegram.ext import ContextTypes

from scr.core.logger import logger
from scr.core.users import user_manager
from scr.core.stats import stats_manager
from scr.core.settings import OWNER_ID


def escape_markdown(text: str) -> str:
    """Экранирует специальные символы Markdown"""
    if not text:
        return ""
    escape_chars = r"\_*`["
    for char in escape_chars:
        text = text.replace(char, f"\\{char}")
    return text


def render_progress_bar(current_min: int, start_min: int, end_min: int, length: int = 8) -> str:
    """Генерирует текстовый прогресс-бар для текущей пары"""
    if end_min <= start_min:
        return ""
    total = end_min - start_min
    elapsed = max(0, min(current_min - start_min, total))
    fraction = elapsed / total
    filled_length = int(round(length * fraction))
    bar = "█" * filled_length + "░" * (length - filled_length)
    percent = int(fraction * 100)
    return f"[{bar}] {percent}%"


def split_message_markdown(text: str, max_length: int = 4000) -> List[str]:
    """Разбивает длинный текст на части по строкам, не превышая max_length"""
    if len(text) <= max_length:
        return [text]

    lines = text.split("\n")
    chunks = []
    current_chunk = []
    current_len = 0

    for line in lines:
        line_len = len(line) + 1
        if current_len + line_len > max_length:
            if current_chunk:
                chunks.append("\n".join(current_chunk))
                current_chunk = [line]
                current_len = line_len
            else:
                chunks.append(line[:max_length])
                current_chunk = [line[max_length:]]
                current_len = len(line[max_length:]) + 1
        else:
            current_chunk.append(line)
            current_len += line_len

    if current_chunk:
        chunks.append("\n".join(current_chunk))

    return chunks


async def safe_edit_message(
    query,
    text: str,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
    parse_mode: Optional[str] = "Markdown"
) -> None:
    """Безопасное редактирование сообщения с отказоустойчивостью"""
    user_id = query.from_user.id if query and query.from_user else "unknown"
    chat_id = query.message.chat_id if query and query.message else "unknown"

    try:
        await query.edit_message_text(
            text=text,
            reply_markup=reply_markup,
            parse_mode=parse_mode
        )
        return
    except BadRequest as e:
        error_msg = str(e).lower()
        if "message is not modified" in error_msg:
            return
        elif "parse" in error_msg or "markdown" in error_msg or "entity" in error_msg:
            logger.warning(f"Markdown ошибка для user {user_id}, повторная отправка в plain text.")
        else:
            logger.error(f"BadRequest при редактировании для user {user_id} (chat {chat_id}): {e}")
    except (Forbidden, TimedOut, RetryAfter) as e:
        logger.error(f"Сетевая ошибка при редактировании для user {user_id}: {e}")
    except Exception as e:
        logger.error(f"Неожиданная ошибка при safe_edit_message для user {user_id}: {e}")

    # Резервная попытка без Markdown
    try:
        await query.edit_message_text(
            text=text,
            reply_markup=reply_markup,
            parse_mode=None
        )
    except Exception as e2:
        logger.error(f"Ошибка резервного edit_message_text для user {user_id}: {e2}")
        try:
            if query.message:
                await query.message.reply_text(text=text, reply_markup=reply_markup, parse_mode=None)
        except Exception as e3:
            logger.critical(f"Не удалось отправить reply_text для user {user_id}: {e3}")


def format_lessons(lessons: List[Dict[str, Any]], user_subgroup: str = "all") -> str:
    """Форматирует список пар в Markdown строку с учетом фильтра подгруппы"""
    if not lessons:
        return ""

    # Фильтрация по подгруппе, если задана конкретная (1 или 2)
    filtered_lessons = []
    for l in lessons:
        subgroup = l.get("subgroup")
        if user_subgroup in ("1", "2") and subgroup:
            if user_subgroup == "1" and ("1" in subgroup or "1️⃣" in subgroup):
                filtered_lessons.append(l)
            elif user_subgroup == "2" and ("2" in subgroup or "2️⃣" in subgroup):
                filtered_lessons.append(l)
        else:
            filtered_lessons.append(l)

    if not filtered_lessons:
        return ""

    grouped: Dict[str, List[Dict[str, Any]]] = {}
    order: List[str] = []

    for l in filtered_lessons:
        t = l.get("time", "").strip()
        if t not in grouped:
            grouped[t] = []
            order.append(t)
        grouped[t].append(l)

    output_lines = []
    for t in order:
        output_lines.append(f"⏰ {t}")
        for entry in grouped[t]:
            subgroup = entry.get("subgroup")
            classroom = entry.get("classroom")

            info_lines = [ln.strip() for ln in (entry.get("info") or "").split("\n") if ln.strip()]
            subject = info_lines[0].replace("*", "").strip() if info_lines else ""
            rest = "\n".join(info_lines[1:]) if len(info_lines) > 1 else ""

            if subgroup:
                output_lines.append(f"🔸 {subgroup}")
            if subject:
                output_lines.append(f"📚 *{subject}*")
            if rest:
                output_lines.append(rest)
            if classroom:
                output_lines.append(f"📍 {classroom}")
            output_lines.append("")

    return "\n".join(output_lines).strip()


def format_day_schedule(
    day_title: str,
    lessons: List[Dict[str, Any]],
    user_subgroup: str = "all",
    empty_text: str = "Нет пар.",
    is_backup: bool = False,
    backup_time: Optional[str] = None
) -> str:
    """Форматирует расписание на конкретный день"""
    prefix = ""
    if is_backup and backup_time:
        prefix = f"⚠️ _Сайт расписания недоступен. Копия от {backup_time}_\n\n"
    text = f"{prefix}🔹 {day_title}:\n\n"
    formatted = format_lessons(lessons, user_subgroup=user_subgroup)
    if formatted:
        text += formatted + "\n"
    else:
        text += f"{empty_text}\n"
    return text


def format_week_schedule(
    week_title: str,
    week_data: Dict[str, List[Dict[str, Any]]],
    user_subgroup: str = "all",
    is_backup: bool = False,
    backup_time: Optional[str] = None
) -> str:
    """
    Красиво и наглядно форматирует расписание на всю неделю с четкими визуальными разделителями между днями.
    """
    from scr.core.settings import RU_WEEKDAYS_ORDER

    header = f"📅 *Расписание ({week_title})*\n"
    if is_backup and backup_time:
        header += f"⚠️ _Сайт расписания недоступен. Копия от {backup_time}_\n"

    sections = [header]

    for day in RU_WEEKDAYS_ORDER:
        lessons = week_data.get(day, [])
        formatted = format_lessons(lessons, user_subgroup=user_subgroup)

        day_block = []
        day_block.append("━━━━━━━━━━━━━━━━━━━━")
        day_block.append(f"🗓 *{day.upper()}*")
        day_block.append("")

        if formatted:
            day_block.append(formatted)
        else:
            day_block.append("✨ _Пар нет — выходной_")

        sections.append("\n".join(day_block))

    return "\n\n".join(sections).strip()


def require_auth(func: Callable) -> Callable:
    """Декоратор для проверки авторизации пользователя"""
    @functools.wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user = update.effective_user
        if not user:
            return

        uid = user.id
        username = user.username or user.full_name

        # Логируем активность
        stats_manager.record_activity(uid, is_command=bool(update.message and update.message.text and update.message.text.startswith("/")))
        stats_manager.save()

async def send_unauthorized_message(update: Update, context: ContextTypes.DEFAULT_TYPE, uid: int) -> None:
    """Отправляет стандартное сообщение для неавторизованного пользователя"""
    owner_contact = "администратору"
    try:
        owner_user = await context.bot.get_chat(OWNER_ID) if OWNER_ID else None
        if owner_user and owner_user.username:
            owner_contact = f"@{owner_user.username}"
        elif OWNER_ID:
            owner_contact = f"ID: `{OWNER_ID}`"
    except Exception:
        owner_contact = "администратору"

    if update.message:
        await update.message.reply_text(
            f"Ваш ID: `{uid}`\n\n"
            f"Для использования бота сообщите ваш ID администратору ({owner_contact}).\n\n"
            f"Администратор {owner_contact}",
            parse_mode="Markdown"
        )


def require_auth(func: Callable) -> Callable:
    """Декоратор для проверки авторизации пользователя"""
    @functools.wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user = update.effective_user
        if not user:
            return

        uid = user.id
        username = user.username or user.full_name

        # Логируем активность
        stats_manager.record_activity(uid, is_command=bool(update.message and update.message.text and update.message.text.startswith("/")))
        stats_manager.save()

        if not user_manager.is_allowed(uid):
            logger.warning(f"❌ Неавторизованный пользователь {username} ({uid}) вызвал {func.__name__}.")
            if update.callback_query:
                await update.callback_query.answer("У вас нет доступа к боту.", show_alert=True)
                return
            elif update.message:
                await send_unauthorized_message(update, context, uid)
                return

        return await func(update, context, *args, **kwargs)
    return wrapper


def require_role(*allowed_roles: str) -> Callable:
    """Декоратор для проверки роли пользователя"""
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
            user = update.effective_user
            if not user:
                return

            uid = user.id
            username = user.username or user.full_name
            role = user_manager.get_role(uid)

            if role not in allowed_roles:
                logger.warning(f"❌ {username} ({uid}) [{role}] попытался вызвать {func.__name__} без прав.")
                if update.callback_query:
                    await update.callback_query.answer("У вас нет прав для этого действия.", show_alert=True)
                elif update.message:
                    await update.message.reply_text("У вас нет прав для выполнения этой команды.")
                return

            return await func(update, context, *args, **kwargs)
        return wrapper
    return decorator