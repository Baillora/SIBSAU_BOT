import os
import json
import asyncio
import time
import pyotp
import qrcode
import io
from functools import wraps
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
from flask import Flask, render_template, redirect, url_for, request, flash, session, send_file
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_wtf import CSRFProtect
from dotenv import load_dotenv
from .forms import LoginForm, TwoFAForm

# ----- Настройки из окружения -----
load_dotenv()

FLASK_SECRET = os.environ.get("FLASK_SECRET")  # Для подписи cookies
PANEL_USER = os.environ.get("PANEL_USER")      # Для логина
PANEL_PASS = os.environ.get("PANEL_PASS")      # Для пароля

OWNER_ID = os.environ.get("PANEL_OWNER_ID")    # ID владельца

SSL_CERT = os.environ.get("SSL_CERT")          # ssl сертификат .crt
SSL_KEY = os.environ.get("SSL_KEY")            # ssl ключ .key

# Проверка обязательных переменных
missing = []
if not FLASK_SECRET:
    missing.append("FLASK_SECRET")
if not PANEL_USER:
    missing.append("PANEL_USER")
if not PANEL_PASS:
    missing.append("PANEL_PASS")

if missing:
    raise RuntimeError(
        f"Ошибка: отсутствуют обязательные переменные окружения: {', '.join(missing)}. "
        f"Укажите их в файле .env"
    )

# Пути к файлам проекта
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
USERS_FILE = os.path.join(PROJECT_ROOT, "allowed_users.json")
STATS_FILE = os.path.join(PROJECT_ROOT, "stats.json")
LOG_FILE   = os.path.join(PROJECT_ROOT, "warning.log")

# ----- Flask -----
app = Flask(__name__, template_folder="templates", static_folder="static")
app.secret_key = FLASK_SECRET

# Безопасные настройки сессий
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SECURE=True,     # cookie только по HTTPS
    SESSION_COOKIE_SAMESITE="Strict",
    PERMANENT_SESSION_LIFETIME=timedelta(minutes=30)
)

# CSRF защита
csrf = CSRFProtect(app)

# Ограничитель запросов (anti-bruteforce)
limiter = Limiter(get_remote_address, app=app, default_limits=["10 per minute"])

# ----- Глобальные ссылки на бота -----
application = None
bot_loop: Optional[asyncio.AbstractEventLoop] = None

@app.before_request
def warn_if_not_https():
    if not request.is_secure:
        flash("⚠️ Соединение не защищено! Используйте HTTPS", "danger")

# ================== УТИЛИТЫ ==================
def login_required(f):
    @wraps(f)
    def _wrap(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return _wrap

def read_json(path: str, default: Any) -> Any:
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        app.logger.warning(f"read_json error for {path}: {e}")
    return default

def write_json(path: str, data: Any) -> None:
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        app.logger.error(f"write_json error for {path}: {e}")
        raise

def load_users() -> Dict[str, Dict[str, str]]:
    data = read_json(USERS_FILE, {})
    users = {}

    if isinstance(data, dict) and "users" in data:
        raw = data["users"]
        for uid, val in raw.items():
            if isinstance(val, dict):
                users[uid] = {"role": val.get("role", "user"), "username": val.get("username", "")}
            else:
                # старый формат: uid: role
                users[uid] = {"role": str(val), "username": ""}
    elif isinstance(data, dict):
        # если весь файл — это старый формат {id: role}
        for uid, val in data.items():
            users[uid] = {"role": str(val), "username": ""}

    # сразу перезаписываем в новом формате
    if users:
        save_users(users)

    return users


def save_users(users: Dict[str, Dict[str, str]]) -> None:
    write_json(USERS_FILE, {"users": users})

def load_stats() -> Dict[str, Any]:
    data = read_json(STATS_FILE, {})
    return data if isinstance(data, dict) else {}

def tail_log(path: str, max_lines: int = 500) -> str:
    if not os.path.exists(path):
        return ""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        last_lines = lines[-max_lines:]
        return "".join(reversed(last_lines))
    except Exception as e:
        return f"Ошибка чтения лога: {e}"

def schedule_coro(coro, retries: int = 10, delay: float = 0.5) -> None:
    global bot_loop
    for _ in range(retries):
        if bot_loop is not None and bot_loop.is_running():
            asyncio.run_coroutine_threadsafe(coro, bot_loop)
            return
        time.sleep(delay)
    raise RuntimeError("Loop бота недоступен")

# ================== АВТОРИЗАЦИЯ ==================
def check_login(username: str, password: str) -> bool:
    return username.strip() == PANEL_USER and password.strip() == PANEL_PASS

@app.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute")
def login():
    form = LoginForm()
    if form.validate_on_submit():
        username = form.username.data.strip()
        password = form.password.data.strip()
        if check_login(username, password):
            session["pre_2fa"] = True
            session["username"] = username
            return redirect(url_for("twofa"))
        else:
            # уведомление владельцу через бота
            try:
                if OWNER_ID and application:
                    schedule_coro(application.bot.send_message(
                        chat_id=int(OWNER_ID),
                        text=f"🚨 Неудачная попытка входа\nЛогин: {username}\nIP: {request.remote_addr}"
                    ))
            except Exception as e:
                app.logger.warning(f"Не удалось отправить уведомление owner: {e}")

            flash("Неверный логин или пароль", "danger")
    return render_template("login.html", form=form)

@app.route("/")
@login_required
def index():
    stats = load_stats()
    unique_users = stats.get("unique_users")
    if isinstance(unique_users, (list, dict)):
        uniq_count = len(unique_users)
    else:
        try:
            uniq_count = int(unique_users)
        except Exception:
            uniq_count = 0

    totals = {
        "unique_users_count": uniq_count,
        "total_messages": stats.get("total_messages", 0),
        "schedule_requests": stats.get("schedule_requests", 0),
        "commands_executed": stats.get("commands_executed", 0),
        "search_queries": stats.get("search_queries", 0),
        "errors": stats.get("errors", 0),
    }

    return render_template(
        "index.html",
        stats=stats,
        totals=totals,
        peak_usage=stats.get("peak_usage", {}),
        commands_per_user=stats.get("commands_per_user", {}),
        daily_active_users=stats.get("daily_active_users", {}),
    )

@app.route("/logout")
def logout():
    session.pop("logged_in", None)
    return redirect(url_for("login"))

# ================== USERS ==================
@app.route("/users", methods=["GET"])
@login_required
def users_page():
    users = load_users()

    # Гарантируем наличие владельца
    if OWNER_ID:
        if str(OWNER_ID) not in users:
            users[str(OWNER_ID)] = {"role": "owner", "username": "Owner"}
            save_users(users)

    # Сортируем: сначала owner → admin → mod → user
    role_order = {"owner": 0, "admin": 1, "mod": 2, "user": 3, "unknown": 9}
    sorted_users = sorted(
        users.items(),
        key=lambda x: (role_order.get(x[1]["role"], 9), x[0])
    )

    return render_template("users.html", users=sorted_users)


@app.route("/users/add", methods=["POST"])
@login_required
def users_add():
    uid = (request.form.get("user_id") or "").strip()
    role = (request.form.get("role") or "user").strip()

    if not uid.isdigit():
        flash("ID пользователя должен быть числом", "danger")
        return redirect(url_for("users_page"))

    if role == "owner":
        flash("❌ Нельзя назначить нового владельца!", "danger")
        role = "user"

    users = load_users()
    users[uid] = {"role": role, "username": ""}
    save_users(users)

    flash(f"Пользователь {uid} добавлен с ролью {role}", "success")
    return redirect(url_for("users_page"))



@app.route("/users/setrole", methods=["POST"])
@login_required
def users_setrole():
    uid = (request.form.get("user_id") or "").strip()
    role = (request.form.get("role") or "user").strip()

    if uid == str(OWNER_ID):
        flash("❌ Нельзя менять роль владельца!", "danger")
        return redirect(url_for("users_page"))

    users = load_users()
    if uid in users:
        users[uid]["role"] = role
        save_users(users)
        flash(f"Роль пользователя {uid} изменена на {role}", "info")
    else:
        flash("Пользователь не найден", "danger")

    return redirect(url_for("users_page"))

@app.route("/users/delete/<user_id>", methods=["POST"])
@login_required
def users_delete(user_id: str):
    if str(user_id) == str(OWNER_ID):
        flash("❌ Нельзя удалить владельца!", "danger")
        return redirect(url_for("users_page"))

    users = load_users()
    if user_id in users:
        del users[user_id]
        save_users(users)
        flash(f"Пользователь {user_id} удалён", "warning")
    else:
        flash("Пользователь не найден", "danger")
    return redirect(url_for("users_page"))


# ================== LOGS ==================
@app.route("/logs")
@login_required
def logs_page():
    data = tail_log(LOG_FILE, 80000)
    if request.args.get("ajax"):
        return data
    return render_template("logs.html", logs=data)

# ================== CONTROL ==================
@app.route("/control", methods=["GET"])
@login_required
def control_page():
    return render_template("control.html")

@app.route("/control/reset2fa", methods=["POST"])
@login_required
def action_reset2fa():
    try:
        write_json(TWOFA_FILE, {"enabled": False})
        flash("🔑 2FA сброшено. При следующем входе снова отобразится QR-код.", "warning")
    except Exception as e:
        flash(f"Не удалось сбросить 2FA: {e}", "danger")
    return redirect(url_for("control_page"))

# ====== ДЕЙСТВИЯ (BOT) ======
@app.route("/control/reload", methods=["POST"])
@login_required
def action_reload():
    """
    Обновляет кэш расписания через функции бота, если они есть.
    """
    try:
        from bot import fetch_schedule, schedule_cache  # type: ignore
        schedule_coro(_reload_coro(fetch_schedule, schedule_cache))
        flash("Запущен перезапуск кэша расписания", "success")
    except Exception as e:
        flash(f"Не удалось вызвать reload через бот: {e}", "danger")
    return redirect(url_for("control_page"))

async def _reload_coro(fetch_schedule_func, schedule_cache_obj):
    try:
        schedule_cache_obj.clear()
    except Exception:
        pass
    await fetch_schedule_func(application)

@app.route("/control/fullreload", methods=["POST"])
@login_required
def action_fullreload():
    """
    Полная перезагрузка (расписание + преподаватели), если функции есть.
    """
    try:
        from bot import fetch_schedule, schedule_cache, fetch_teachers, teachers_cache  # type: ignore
        schedule_coro(_fullreload_coro(fetch_schedule, schedule_cache, fetch_teachers, teachers_cache))
        flash("Запущена полная перезагрузка", "success")
    except Exception as e:
        flash(f"Не удалось вызвать fullreload через бот: {e}", "danger")
    return redirect(url_for("control_page"))

async def _fullreload_coro(fetch_schedule_func, schedule_cache_obj, fetch_teachers_func, teachers_cache_obj):
    try:
        schedule_cache_obj.clear()
    except Exception:
        pass
    await fetch_schedule_func(application)
    try:
        teachers_cache_obj.clear()
    except Exception:
        pass
    try:
        await fetch_teachers_func(application)
    except Exception:
        # если нет функции — тихо игнорируем
        pass

@app.route("/control/broadcast", methods=["POST"])
@login_required
def action_broadcast():
    """
    Рассылка всем пользователям из allowed_users.json.
    """
    text = (request.form.get("message") or "").strip()
    if not text:
        flash("Сообщение пустое", "danger")
        return redirect(url_for("control_page"))

    users = load_users()
    if not users:
        flash("Нет пользователей для рассылки", "warning")
        return redirect(url_for("control_page"))

    try:
        schedule_coro(_broadcast_coro(text, list(users.keys())))
        flash(f"Рассылка запущена ({len(users)} пользователей)", "success")
    except Exception as e:
        flash(f"Не получилось запустить рассылку: {e}", "danger")
    return redirect(url_for("control_page"))

async def _broadcast_coro(text: str, user_ids: list[str]):
    ok, fail = 0, 0
    for uid in user_ids:
        try:
            await application.bot.send_message(chat_id=int(uid), text=f"🔔 Объявление:\n{text}")
            ok += 1
        except Exception:
            fail += 1
    # Можно писать в лог
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now().isoformat(timespec='seconds')}] broadcast: ok={ok}, fail={fail}\n")
    except Exception:
        pass


# ======== 2FA (Google Authenticator) ========
TWOFA_FILE = os.path.join(PROJECT_ROOT, "2fa_status.json")
TOTP_SECRET = os.environ.get("TOTP_SECRET") or pyotp.random_base32()
totp = pyotp.TOTP(TOTP_SECRET)


def is_2fa_enabled() -> bool:
    data = read_json(TWOFA_FILE, {"enabled": False})
    return data.get("enabled", False)


def set_2fa_enabled():
    write_json(TWOFA_FILE, {"enabled": True})


@app.route("/qrcode")
def qrcode_route():
    # доступен только если пользователь прошёл login, но ещё не 2FA
    if not session.get("pre_2fa") and not session.get("logged_in"):
        return redirect(url_for("login"))

    # если уже активирован 2FA — не рисуем QR
    if is_2fa_enabled():
        flash("2FA уже активировано, используйте код из приложения.", "info")
        return redirect(url_for("twofa"))

    uri = totp.provisioning_uri(name="AdminPanel", issuer_name="SIBSAU_BOT")
    img = qrcode.make(uri)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return send_file(buf, mimetype="image/png")


@app.route("/2fa", methods=["GET", "POST"], endpoint="twofa")
def twofa():
    if not session.get("pre_2fa"):
        return redirect(url_for("login"))

    show_qr = not is_2fa_enabled()
    form = TwoFAForm()

    if form.validate_on_submit():
        code = form.code.data.strip()
        if totp.verify(code):
            session.pop("pre_2fa", None)
            session["logged_in"] = True
            set_2fa_enabled()   # записываем, что QR больше не нужен
            flash("✅ 2FA успешно подтверждено", "success")
            return redirect(url_for("index"))
        else:
            flash("Неверный код 2FA", "danger")

    return render_template("2fa.html", form=form, show_qr=show_qr)

# ================== ЗАПУСК ==================
def run_flask():
    if SSL_CERT and SSL_KEY and os.path.exists(SSL_CERT) and os.path.exists(SSL_KEY):
        app.run(
            host="0.0.0.0",
            port=19999,
            ssl_context=(SSL_CERT, SSL_KEY)
        )
    else:
        print("⚠️ SSL не настроен, панель будет работать по HTTP (небезопасно)")
        app.run(host="0.0.0.0", port=19999)
