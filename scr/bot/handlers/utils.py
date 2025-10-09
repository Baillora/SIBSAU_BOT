from telegram.error import BadRequest, Forbidden, RetryAfter, TimedOut
from scr.core.logger import logger
from telegram import InlineKeyboardMarkup

async def safe_edit_message(query, text, reply_markup: InlineKeyboardMarkup = None):
    user_id = query.from_user.id if query and query.from_user else "unknown"
    chat_id = query.message.chat_id if query and query.message else "unknown"

    try:
        await query.edit_message_text(
            text=text,
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
        return
    except BadRequest as e:
        error_msg = str(e).lower()
        if "message is not modified" in error_msg:
            return
        elif "parse" in error_msg or "markdown" in error_msg:
            # Если сломался Markdown — отправляем plain text
            logger.warning(f"Markdown ошибка для пользователя {user_id}, переключаемся на plain text.")
        else:
            logger.error(f"BadRequest при редактировании для user {user_id} (chat {chat_id}): {e}")
    except (Forbidden, TimedOut, RetryAfter) as e:
        logger.error(f"Сетевая/доступ ошибка при редактировании для user {user_id}: {e}")
    except Exception as e:
        logger.error(f"Неожиданная ошибка при редактировании для user {user_id}: {e}")

    # Резерв: plain text
    try:
        await query.edit_message_text(
            text=text,
            reply_markup=reply_markup,
            parse_mode=None
        )
    except Exception as e2:
        logger.error(f"Полный провал safe_edit_message для user {user_id}: {e2}")
        try:
            await query.message.reply_text(text, reply_markup=reply_markup)
        except Exception as e3:
            logger.critical(f"Невозможно отправить даже новое сообщение для user {user_id}: {e3}")