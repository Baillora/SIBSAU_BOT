from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from scr.core.users import user_manager
from scr.core.logger import logger
from scr.core.auth_tokens import auth_token_manager
from scr.bot.handlers.utils import require_auth


@require_auth
async def web_auth_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /web для быстрой авторизации в веб-панели через Telegram"""
    user = update.effective_user
    if not user:
        return

    uid = user.id
    username = user.username or user.full_name
    role = user_manager.get_role(uid)

    # Генерация токена и одноразового кода
    token, otp_code, error_msg = auth_token_manager.create_auth_token(uid, username, role)
    if error_msg:
        if update.callback_query:
            await update.callback_query.answer(error_msg, show_alert=True)
        elif update.message:
            await update.message.reply_text(f"⏳ {error_msg}")
        return

    role_labels = {
        "owner": "👑 Владелец",
        "admin": "🛡️ Администратор",
        "mod": "👮 Модератор",
        "user": "🎓 Студент"
    }
    role_title = role_labels.get(role, "Пользователь")

    # Формируем подсказку с кодом и инструкцией
    text = (
        "🔐 *Авторизация в Веб-панели SIBSAU_BOT*\n\n"
        f"👤 Пользователь: *{username}* (ID: `{uid}`)\n"
        f"🎭 Роль в системе: *{role_title}*\n\n"
        f"🔑 Ваш одноразовый код для входа:\n"
        f"👉 `{otp_code}`\n\n"
        "⏱ _Код действует 5 минут и может быть использован только один раз._\n\n"
        "💻 Откройте страницу входа веб-панели в браузере, введите ваш Telegram ID и этот 6-значный код."
    )

    if update.callback_query:
        await update.callback_query.answer("Код авторизации отправлен!", show_alert=False)
        await update.callback_query.message.reply_text(text, parse_mode="Markdown")
    elif update.message:
        await update.message.reply_text(text, parse_mode="Markdown")

    logger.info(f"🔑 {username} ({uid}) [{role}] запросил токен авторизации в веб-панели.")
