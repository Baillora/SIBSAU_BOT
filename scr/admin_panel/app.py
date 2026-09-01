import os
import json
import asyncio
import hmac
import hashlib
import pyotp
import qrcode
import io
import socket
import urllib.parse
from pathlib import Path
from functools import wraps
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
from flask import Flask, render_template, redirect, url_for, request, flash, session, send_file, jsonify, abort
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_wtf import CSRFProtect
import httpx

import scr.core.settings as settings
from scr.core.logger import logger
from scr.core.users import user_manager
from scr.core.stats import stats_manager
from scr.core.notes import notes_manager
from scr.core.auth_tokens import auth_token_manager
from scr.parsers.schedule_parser import fetch_schedule, schedule_cache
from scr.parsers.teacher_parser import fetch_teachers, teachers_cache
from .forms import LoginForm, TwoFAForm

# Инициализация Flask
app = Flask(__name__, template_folder="templates", static_folder="static")
app.secret_key = settings.FLASK_SECRET or "default_secret_key_for_dev_mode"

SSL_CERT = settings.SSL_CERT
SSL_KEY = settings.SSL_KEY
use_ssl = bool(settings.SSL_CERT and settings.SSL_KEY and os.path.exists(settings.SSL_CERT) and os.path.exists(settings.SSL_KEY))

app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SECURE=use_ssl,
    SESSION_COOKIE_SAMESITE="Strict",
    PERMANENT_SESSION_LIFETIME=timedelta(days=30)
)

# CSRF защита
csrf = CSRFProtect(app)


def get_client_ip() -> str:
    """Безопасное определение реального IP клиента с поддержкой прокси"""
    if request.headers.get("CF-Connecting-IP"):
        return request.headers.get("CF-Connecting-IP").split(",")[0].strip()
    if request.headers.get("X-Forwarded-For"):
        return request.headers.get("X-Forwarded-For").split(",")[0].strip()
    if request.headers.get("X-Real-IP"):
        return request.headers.get("X-Real-IP").split(",")[0].strip()
    return request.remote_addr or "127.0.0.1"


def get_request_host() -> str:
    """Определение хоста сервера / домена панели"""
    host = request.host
    if host:
        return host.split(":")[0]
    return socket.gethostname() or "unknown_host"


# Ограничитель запросов (Brute-force protection)
limiter = Limiter(get_client_ip, app=app, default_limits=["120 per minute"])

# 2FA
_totp_key = settings.TOTP_SECRET or "JBSWY3DPEHPK3PXP"
totp = pyotp.TOTP(_totp_key)


def is_2fa_enabled() -> bool:
    """Проверяет статус активации 2FA"""
    twofa_path = Path(settings.TWOFA_FILE)
    if twofa_path.exists():
        try:
            with open(twofa_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return bool(data.get("enabled", False))
        except Exception:
            return False
    return False


def set_2fa_enabled(enabled: bool = True) -> None:
    """Устанавливает статус 2FA"""
    try:
        twofa_path = Path(settings.TWOFA_FILE)
        twofa_path.parent.mkdir(parents=True, exist_ok=True)
        with open(twofa_path, "w", encoding="utf-8") as f:
            json.dump({"enabled": enabled}, f, indent=2)
    except Exception as e:
        logger.error(f"Ошибка сохранения 2FA статуса: {e}")


def get_user_role() -> str:
    """Получить актуальную роль текущего авторизованного пользователя"""
    if session.get("is_master_admin"):
        return "owner"
    tg_id = session.get("telegram_id")
    if tg_id:
        try:
            return user_manager.get_role(int(tg_id))
        except Exception:
            return "user"
    # Для традиционного входа по логину/паролю администратора роль по умолчанию - owner
    return session.get("role", "owner")


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))

        # Проверка актуальности прав для вошедших через Telegram
        tg_id = session.get("telegram_id")
        if tg_id:
            try:
                uid = int(tg_id)
                if not user_manager.is_allowed(uid):
                    session.clear()
                    flash("⛔️ Доступ отозван. Ваш аккаунт больше не разрешен в системе.", "danger")
                    return redirect(url_for("login"))
                session["role"] = user_manager.get_role(uid)
            except Exception:
                session.clear()
                return redirect(url_for("login"))

        return f(*args, **kwargs)
    return decorated_function


def role_required(*allowed_roles: str):
    """Декоратор для строгой проверки роли пользователя в веб-панели (RBAC)"""
    def decorator(f):
        @wraps(f)
        @login_required
        def decorated_function(*args, **kwargs):
            current_role = get_user_role()
            if current_role not in allowed_roles:
                flash(f"⛔️ У вас нет прав для доступа к этому разделу (ваша роль: {current_role}).", "warning")
                if current_role == "user":
                    return redirect(url_for("schedule_view"))
                elif current_role == "mod":
                    return redirect(url_for("users_page"))
                return redirect(url_for("index"))
            return f(*args, **kwargs)
        return decorated_function
    return decorator


@app.context_processor
def inject_user_context():
    """Передача данных текущего пользователя во все шаблоны"""
    has_ssl = bool(settings.SSL_CERT and settings.SSL_KEY and os.path.exists(settings.SSL_CERT) and os.path.exists(settings.SSL_KEY))
    if session.get("logged_in"):
        role = get_user_role()
        role_labels = {
            "owner": "👑 Владелец",
            "admin": "🛡️ Администратор",
            "mod": "👮 Модератор",
            "user": "🎓 Студент"
        }
        return {
            "current_role": role,
            "current_role_label": role_labels.get(role, "Пользователь"),
            "current_username": session.get("username", "Пользователь"),
            "current_tg_id": session.get("telegram_id"),
            "is_master_admin": session.get("is_master_admin", False),
            "is_https": has_ssl,
        }
    return {
        "current_role": None,
        "current_role_label": None,
        "current_username": None,
        "current_tg_id": None,
        "is_master_admin": False,
        "is_https": has_ssl,
    }


def is_safe_url(url: str) -> bool:
    """Проверка безопасности URL против SSRF и XSS инъекций"""
    if not url:
        return True
    try:
        parsed = urllib.parse.urlparse(url.strip())
        return parsed.scheme in ("http", "https") and bool(parsed.netloc)
    except Exception:
        return False


def tail_log(path, max_lines: int = 500) -> str:
    """Возвращает последние строки лога"""
    p = Path(path)
    if not p.exists():
        return "Лог-файл пуст или отсутствует."
    try:
        with open(p, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        last_lines = lines[-max_lines:]
        return "".join(reversed(last_lines))
    except Exception as e:
        return f"Ошибка чтения лога: {e}"


def check_login(username: str, password: str) -> bool:
    """Безопасная проверка логина и пароля с защитой от timing attacks"""
    username_valid = hmac.compare_digest(username.strip(), (settings.PANEL_USER or "").strip())
    password_valid = hmac.compare_digest(password.strip(), (settings.PANEL_PASS or "").strip())
    return username_valid and password_valid


def get_httpx_client(timeout: float = 5.0) -> httpx.Client:
    """Создает клиент HTTPX с поддержкой PROXY_URL"""
    proxy = getattr(settings, "PROXY_URL", "")
    if proxy:
        return httpx.Client(proxy=proxy, timeout=timeout)
    return httpx.Client(timeout=timeout)


def send_owner_login_alert(
    is_success: bool,
    username: str,
    ip: str,
    host: str,
    reason: Optional[str] = None
) -> None:
    """Отправка уведомления о попытке входа исключительно владельцу бота"""
    if not settings.TOKEN or not settings.OWNER_ID:
        return

    now = datetime.now()
    header_time = now.strftime("%d.%m.%Y %H:%M")
    body_time = now.strftime("%Y-%m-%d %H:%M:%S")

    if is_success:
        text = (
            f"[{header_time}] Panel Info #2: ✅ Успешный вход в панель.\n"
            f"💻 Хост: {host}\n"
            f"👤 Имя пользователя: {username}\n"
            f"🌐 IP: {ip}\n"
            f"⏰ Время: {body_time}"
        )
    else:
        text = (
            f"[{header_time}] Panel Info #2: ❗️ Ошибка входа в панель.\n"
            f"💻 Хост: {host}\n"
            f"❗️ Причина: {reason or 'invalid credentials'}\n"
            f"👤 Имя пользователя: {username}\n"
            f"🌐 IP: {ip}\n"
            f"⏰ Время: {body_time}"
        )

    try:
        with get_httpx_client(timeout=5.0) as client:
            client.post(
                f"https://api.telegram.org/bot{settings.TOKEN}/sendMessage",
                json={"chat_id": settings.OWNER_ID, "text": text}
            )
    except Exception as e:
        logger.warning(f"Не удалось отправить уведомление о входе владельцу: {e}")


# ================== SECURITY HEADERS ==================

@app.after_request
def set_security_headers(response):
    """Установка защитных HTTP-заголовков (OWASP / InfoSec Standards)"""
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), camera=(), microphone=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self' https:; "
        "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com https://telegram.org; "
        "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com; "
        "font-src 'self' https://cdnjs.cloudflare.com data:; "
        "img-src 'self' data: https:; "
        "frame-src https://oauth.telegram.org; "
        "frame-ancestors 'none';"
    )
    if use_ssl:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


# ================== ОБРАБОТЧИКИ ОШИБОК ==================

@app.errorhandler(429)
def ratelimit_handler(e):
    ip = get_client_ip()
    host = get_request_host()
    send_owner_login_alert(
        is_success=False,
        username=session.get("username", "Unknown"),
        ip=ip,
        host=host,
        reason="rate limit exceeded (brute force protection)"
    )
    flash("⚠️ Слишком много запросов. Пожалуйста, подождите минуту перед следующей попыткой.", "danger")
    return render_template("login.html", form=LoginForm()), 429


@app.errorhandler(404)
def not_found_handler(e):
    return render_template("base.html"), 404


@app.errorhandler(500)
def internal_error_handler(e):
    logger.error(f"Internal server error: {e}")
    return render_template("base.html"), 500


# ================== МАРШРУТЫ АВТОРИЗАЦИИ ==================

@app.route("/login", methods=["GET", "POST"])
@limiter.limit("5 per minute")
def login():
    if session.get("logged_in"):
        role = get_user_role()
        if role == "user":
            return redirect(url_for("schedule_view"))
        return redirect(url_for("index"))

    form = LoginForm()
    if form.validate_on_submit():
        username = form.username.data.strip()
        password = form.password.data.strip()

        ip = get_client_ip()
        host = get_request_host()

        if check_login(username, password):
            session.clear()
            session["pre_2fa"] = True
            session["username"] = username
            session["remember_me"] = bool(form.remember_me.data)
            return redirect(url_for("twofa"))
        else:
            send_owner_login_alert(
                is_success=False,
                username=username,
                ip=ip,
                host=host,
                reason="invalid master credentials"
            )
            flash("Неверный логин или пароль", "danger")

    return render_template("login.html", form=form)


@app.route("/auth/telegram", methods=["GET"])
@limiter.limit("10 per minute")
def auth_telegram():
    """Вход по одноразовой ссылке (magic link) из Telegram бота"""
    token = request.args.get("token", "").strip()
    ip = get_client_ip()
    host = get_request_host()

    if not token:
        flash("Токен авторизации отсутствует.", "danger")
        return redirect(url_for("login"))

    data = auth_token_manager.verify_and_consume_token(token)
    if not data:
        send_owner_login_alert(
            is_success=False,
            username="Telegram-User",
            ip=ip,
            host=host,
            reason="invalid or expired telegram auth token"
        )
        flash("❌ Ссылка для входа недействительна или срок её действия истек. Запросите новую команду /web в боте.", "danger")
        return redirect(url_for("login"))

    uid = int(data["user_id"])
    if not user_manager.is_allowed(uid):
        send_owner_login_alert(
            is_success=False,
            username=f"ID:{uid}",
            ip=ip,
            host=host,
            reason="unauthorized telegram user"
        )
        flash("⛔️ Доступ запрещен. Ваш аккаунт не найден в списке разрешенных пользователей.", "danger")
        return redirect(url_for("login"))

    role = user_manager.get_role(uid)
    username = data.get("username") or str(uid)

    session.clear()
    session["logged_in"] = True
    session["telegram_id"] = uid
    session["username"] = username
    session["role"] = role
    session["is_master_admin"] = (role == "owner")
    session.permanent = True

    send_owner_login_alert(
        is_success=True,
        username=f"TG: {username} ({uid}) [{role}]",
        ip=ip,
        host=host
    )
    flash(f"✅ Вы успешно вошли через Telegram как {username} ({role})!", "success")

    if role == "user":
        return redirect(url_for("schedule_view"))
    elif role == "mod":
        return redirect(url_for("users_page"))
    return redirect(url_for("index"))


@app.route("/auth/telegram_code", methods=["POST"])
@limiter.limit("5 per minute")
def auth_telegram_code():
    """Вход по 6-значному коду и Telegram ID"""
    tg_id_str = (request.form.get("telegram_id") or "").strip()
    code = (request.form.get("code") or "").strip()
    ip = get_client_ip()
    host = get_request_host()

    if not tg_id_str.isdigit() or not code:
        flash("Пожалуйста, введите ваш Telegram ID и 6-значный код.", "danger")
        return redirect(url_for("login"))

    uid = int(tg_id_str)
    data = auth_token_manager.verify_and_consume_code(uid, code)
    if not data:
        send_owner_login_alert(
            is_success=False,
            username=f"ID:{uid}",
            ip=ip,
            host=host,
            reason="invalid telegram OTP code"
        )
        flash("❌ Неверный код подтверждения или Telegram ID. Отправьте /web боту для получения свежего кода.", "danger")
        return redirect(url_for("login"))

    if not user_manager.is_allowed(uid):
        send_owner_login_alert(
            is_success=False,
            username=f"ID:{uid}",
            ip=ip,
            host=host,
            reason="unauthorized telegram user"
        )
        flash("⛔️ Доступ запрещен. Ваш аккаунт не найден в списке разрешенных.", "danger")
        return redirect(url_for("login"))

    role = user_manager.get_role(uid)
    username = data.get("username") or str(uid)
    remember_me = request.form.get("remember_me") in ("1", "true", "on", "checked")

    session.clear()
    session["logged_in"] = True
    session["telegram_id"] = uid
    session["username"] = username
    session["role"] = role
    session["is_master_admin"] = (role == "owner")
    session.permanent = remember_me

    send_owner_login_alert(
        is_success=True,
        username=f"TG: {username} ({uid}) [{role}]",
        ip=ip,
        host=host
    )
    flash(f"✅ Добро пожаловать, {username}!", "success")

    if role == "user":
        return redirect(url_for("schedule_view"))
    elif role == "mod":
        return redirect(url_for("users_page"))
    return redirect(url_for("index"))


@app.route("/2fa", methods=["GET", "POST"], endpoint="twofa")
@limiter.limit("5 per minute")
def twofa():
    if not session.get("pre_2fa"):
        return redirect(url_for("login"))

    show_qr = not is_2fa_enabled()
    form = TwoFAForm()
    username = session.get("username", "Admin")
    ip = get_client_ip()
    host = get_request_host()

    if form.validate_on_submit():
        code = form.code.data.strip()
        if totp.verify(code):
            remember = session.pop("remember_me", True)
            session.pop("pre_2fa", None)
            session["logged_in"] = True
            session["is_master_admin"] = True
            session["role"] = "owner"
            session.permanent = bool(remember)
            set_2fa_enabled(True)

            send_owner_login_alert(
                is_success=True,
                username=username,
                ip=ip,
                host=host
            )
            flash("✅ 2FA успешно подтверждено", "success")
            return redirect(url_for("index"))
        else:
            send_owner_login_alert(
                is_success=False,
                username=username,
                ip=ip,
                host=host,
                reason="invalid 2FA code"
            )
            flash("Неверный код 2FA", "danger")

    return render_template("2fa.html", form=form, show_qr=show_qr)


@app.route("/qrcode")
def qrcode_route():
    if not session.get("pre_2fa") and not session.get("logged_in"):
        return redirect(url_for("login"))

    if is_2fa_enabled():
        flash("2FA уже активировано, используйте код из приложения.", "info")
        return redirect(url_for("twofa"))

    uri = totp.provisioning_uri(name="AdminPanel", issuer_name="SIBSAU_BOT")
    img = qrcode.make(uri)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return send_file(buf, mimetype="image/png")


@app.route("/logout")
def logout():
    session.clear()
    flash("Вы вышли из системы.", "info")
    return redirect(url_for("login"))


# ================== СТАТИСТИКА И ПАНЕЛЬ (ТОЛЬКО ADMIN И OWNER) ==================

@app.route("/")
@login_required
def index():
    role = get_user_role()
    if role == "user":
        return redirect(url_for("schedule_view"))
    elif role == "mod":
        return redirect(url_for("users_page"))

    stats_data = stats_manager.get_snapshot()
    totals = {
        "unique_users_count": stats_data["unique_users_count"],
        "total_messages": stats_data["total_messages"],
        "schedule_requests": stats_data["schedule_requests"],
        "commands_executed": stats_data["commands_executed"],
        "search_queries": stats_data["search_queries"],
        "errors": stats_data["errors"],
    }

    return render_template(
        "index.html",
        stats=stats_data,
        totals=totals,
        peak_usage=stats_data.get("peak_usage", {}),
        commands_per_user=stats_data.get("commands_per_user", {}),
        daily_active_users=stats_data.get("daily_active_users", {}),
    )


# ================== РАСПИСАНИЕ (ДОСТУПНО ВСЕМ РОЛЯМ) ==================

@app.route("/schedule", methods=["GET"])
@login_required
def schedule_view():
    """Просмотр актуального расписания в веб-панели (доступно всем: студент, модер, админ, владелец)"""
    schedule_data = dict(schedule_cache)
    if not schedule_data:
        try:
            schedule_data = asyncio.run(fetch_schedule(None))
        except Exception:
            schedule_data = {}

    return render_template(
        "schedule.html",
        schedule=schedule_data,
        weekdays=settings.RU_WEEKDAYS_ORDER
    )


# ================== ПОЛЬЗОВАТЕЛИ (MOD, ADMIN, OWNER) ==================

@app.route("/users", methods=["GET"])
@role_required("owner", "admin", "mod")
def users_page():
    users_dict = user_manager.get_all_users()

    role_order = {"owner": 0, "admin": 1, "mod": 2, "user": 3, "unknown": 9}
    sorted_users = sorted(
        users_dict.items(),
        key=lambda x: (role_order.get(x[1].get("role", "user"), 9), x[0])
    )

    return render_template("users.html", users=sorted_users)


@app.route("/users/add", methods=["POST"])
@role_required("owner", "admin", "mod")
def users_add():
    current_role = get_user_role()
    uid_str = (request.form.get("user_id") or "").strip()
    requested_role = (request.form.get("role") or "user").strip()

    if not uid_str.isdigit() or len(uid_str) > 16:
        flash("ID пользователя должен быть числом (до 16 цифр)", "danger")
        return redirect(url_for("users_page"))

    uid = int(uid_str)

    # Ограничения по ролям в зависимости от ранга создателя
    if current_role == "mod":
        # Модератор может добавлять только обычных пользователей (user)
        role_to_set = "user"
    elif current_role == "admin":
        # Администратор может создавать только user или mod
        if requested_role not in ("user", "mod"):
            flash("Администратор может добавлять пользователей только с ролями 'Студент' или 'Модератор'.", "warning")
            role_to_set = "user"
        else:
            role_to_set = requested_role
    else:
        # Владелец может назначать admin, mod, user
        if requested_role in ("user", "mod", "admin"):
            role_to_set = requested_role
        else:
            role_to_set = "user"

    if user_manager.add_user(uid, role=role_to_set, username="Веб-панель"):
        flash(f"✅ Пользователь {uid} успешно добавлен с ролью {role_to_set}", "success")
    else:
        flash("Пользователь уже существует или не может быть добавлен", "warning")

    return redirect(url_for("users_page"))


@app.route("/users/setrole", methods=["POST"])
@role_required("owner", "admin")
def users_setrole():
    """Смена роли пользователя (только Admin и Owner)"""
    current_role = get_user_role()
    uid_str = (request.form.get("user_id") or "").strip()
    new_role = (request.form.get("role") or "user").strip()

    if not uid_str.isdigit() or len(uid_str) > 16:
        flash("Некорректный ID пользователя", "danger")
        return redirect(url_for("users_page"))

    uid = int(uid_str)
    if uid == settings.OWNER_ID or new_role == "owner":
        flash("❌ Нельзя менять роль владельца!", "danger")
        return redirect(url_for("users_page"))

    target_current_role = user_manager.get_role(uid)

    # Администратор не может менять роли других администраторов или назначать новых администраторов
    if current_role == "admin":
        if target_current_role in ("admin", "owner"):
            flash("❌ У вас нет прав для изменения роли администратора.", "danger")
            return redirect(url_for("users_page"))
        if new_role not in ("user", "mod"):
            flash("❌ Администратор может назначать только роли 'Студент' и 'Модератор'.", "danger")
            return redirect(url_for("users_page"))

    if user_manager.set_role(uid, new_role):
        flash(f"✅ Роль пользователя {uid} изменена на {new_role}", "info")
    else:
        flash("Пользователь не найден", "danger")

    return redirect(url_for("users_page"))


@app.route("/users/delete/<user_id>", methods=["POST"])
@role_required("owner", "admin", "mod")
def users_delete(user_id: str):
    current_role = get_user_role()
    if not user_id.isdigit():
        flash("Некорректный ID", "danger")
        return redirect(url_for("users_page"))

    uid = int(user_id)
    if uid == settings.OWNER_ID:
        flash("❌ Нельзя удалить владельца!", "danger")
        return redirect(url_for("users_page"))

    target_role = user_manager.get_role(uid)

    # Проверка рангов при удалении:
    # Модератор может удалять только 'user'
    if current_role == "mod" and target_role != "user":
        flash("❌ Модератор может удалять только обычных пользователей (Студентов).", "danger")
        return redirect(url_for("users_page"))

    # Администратор может удалять 'user' и 'mod', но не 'admin'/'owner'
    if current_role == "admin" and target_role in ("admin", "owner"):
        flash("❌ Администратор не может удалять других администраторов.", "danger")
        return redirect(url_for("users_page"))

    if user_manager.remove_user(uid):
        flash(f"Пользователь {uid} удалён", "warning")
    else:
        flash("Пользователь не найден", "danger")

    return redirect(url_for("users_page"))


@app.route("/users/message/<user_id>", methods=["POST"])
@role_required("owner", "admin")
def send_user_message(user_id: str):
    """Отправка прямого сообщения пользователю в Telegram (только Admin и Owner)"""
    if not user_id.isdigit():
        flash("Некорректный ID", "danger")
        return redirect(url_for("users_page"))

    uid = int(user_id)
    text = (request.form.get("text") or "").strip()
    if not text or len(text) > 2000:
        flash("Сообщение не может быть пустым или превышать 2000 символов", "danger")
        return redirect(url_for("users_page"))

    token = settings.TOKEN
    if not token:
        flash("TOKEN не задан", "danger")
        return redirect(url_for("users_page"))

    try:
        with get_httpx_client(timeout=5.0) as client:
            resp = client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": uid, "text": f"📩 *Сообщение от администратора:*\n\n{text}", "parse_mode": "Markdown"}
            )
            if resp.is_success:
                flash(f"✅ Сообщение отправлено пользователю {uid}", "success")
            else:
                flash(f"❌ Ошибка отправки: {resp.text}", "danger")
    except Exception as e:
        flash(f"❌ Ошибка: {e}", "danger")

    return redirect(url_for("users_page"))


# ================== ЛОГИ (ADMIN И OWNER) ==================

@app.route("/logs")
@role_required("owner", "admin")
def logs_page():
    data = tail_log(settings.LOG_FILE, 1000)
    if request.args.get("ajax"):
        return data
    return render_template("logs.html", logs=data)


@app.route("/logs/download")
@role_required("owner", "admin")
def logs_download():
    """Скачивание файла логов"""
    p = Path(settings.LOG_FILE)
    if p.exists():
        return send_file(p, as_attachment=True, download_name="warning.log")
    flash("Файл логов отсутствует", "warning")
    return redirect(url_for("logs_page"))


@app.route("/logs/clear", methods=["POST"])
@role_required("owner")
def logs_clear():
    """Очистка файла логов (только Owner)"""
    try:
        p = Path(settings.LOG_FILE)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write("")
        flash("✅ Лог-файл успешно очищен", "success")
    except Exception as e:
        flash(f"❌ Ошибка очистки лога: {e}", "danger")
    return redirect(url_for("logs_page"))


# ================== НАСТРОЙКИ (ТОЛЬКО OWNER) ==================

@app.route("/settings_panel", methods=["GET", "POST"])
@role_required("owner")
def settings_panel():
    """Просмотр и безопасное редактирование всех параметров .env (только Owner)"""
    if request.method == "POST":
        new_token = (request.form.get("token") or "").strip()
        new_owner_id_str = (request.form.get("owner_id") or "").strip()
        new_timezone = (request.form.get("timezone") or "Asia/Krasnoyarsk").strip()

        new_sched = (request.form.get("schedule_url") or "").strip()
        new_plan = (request.form.get("plan_url") or "").strip()
        new_sem_start = (request.form.get("semester_start") or "").strip()

        new_panel_user = (request.form.get("panel_user") or "admin").strip()
        new_panel_pass = (request.form.get("panel_pass") or "").strip()
        new_flask_secret = (request.form.get("flask_secret") or "").strip()
        new_panel_port_str = (request.form.get("panel_port") or "19999").strip()
        new_panel_url = (request.form.get("panel_url") or "").strip()

        new_ssl_cert = (request.form.get("ssl_cert") or "").strip()
        new_ssl_key = (request.form.get("ssl_key") or "").strip()
        new_totp_secret = (request.form.get("totp_secret") or "").strip()

        new_proxy_url = (request.form.get("proxy_url") or "").strip()
        new_log_level = (request.form.get("log_level") or "INFO").strip().upper()

        if new_sched and not is_safe_url(new_sched):
            flash("❌ Недопустимый URL для расписания (разрешены только http/https)", "danger")
            return redirect(url_for("settings_panel"))

        if new_plan and not is_safe_url(new_plan):
            flash("❌ Недопустимый URL для учебного плана (разрешены только http/https)", "danger")
            return redirect(url_for("settings_panel"))

        if new_panel_url and not is_safe_url(new_panel_url):
            flash("❌ Недопустимый URL для веб-панели (разрешены только http/https)", "danger")
            return redirect(url_for("settings_panel"))

        if new_log_level not in ("DEBUG", "INFO", "WARNING", "ERROR"):
            new_log_level = "INFO"

        # 1. Telegram
        if new_token:
            settings.TOKEN = new_token
            settings.update_env_var("TOKEN", new_token)

        if new_owner_id_str.isdigit():
            settings.OWNER_ID = int(new_owner_id_str)
            settings.update_env_var("OWNER_ID", new_owner_id_str)

        settings.TIMEZONE_NAME = new_timezone
        settings.update_env_var("TIMEZONE", new_timezone)

        # 2. Расписание
        settings.SCHEDULE_URL = new_sched
        settings.update_env_var("SCHEDULE_URL", new_sched)

        settings.PLAN_URL = new_plan
        settings.update_env_var("PLAN_URL", new_plan)

        settings.SEMESTER_START = new_sem_start
        settings.update_env_var("SEMESTER_START", new_sem_start)

        # 3. Веб-панель
        settings.PANEL_USER = new_panel_user
        settings.update_env_var("PANEL_USER", new_panel_user)

        if new_panel_pass:
            settings.PANEL_PASS = new_panel_pass
            settings.update_env_var("PANEL_PASS", new_panel_pass)

        if new_flask_secret:
            settings.FLASK_SECRET = new_flask_secret
            app.secret_key = new_flask_secret
            settings.update_env_var("FLASK_SECRET", new_flask_secret)

        if new_panel_port_str.isdigit():
            port_val = int(new_panel_port_str)
            if 1 <= port_val <= 65535:
                settings.PANEL_PORT = port_val
                settings.update_env_var("PANEL_PORT", new_panel_port_str)

        settings.set_panel_url(new_panel_url)

        # 4. SSL & 2FA
        if new_ssl_cert:
            resolved_cert = settings._resolve_ssl_path(new_ssl_cert)
            settings.SSL_CERT = resolved_cert or new_ssl_cert
            settings.update_env_var("SSL_CERT", new_ssl_cert)

        if new_ssl_key:
            resolved_key = settings._resolve_ssl_path(new_ssl_key)
            settings.SSL_KEY = resolved_key or new_ssl_key
            settings.update_env_var("SSL_KEY", new_ssl_key)

        if new_totp_secret:
            settings.TOTP_SECRET = new_totp_secret
            settings.update_env_var("TOTP_SECRET", new_totp_secret)

        # 5. Сеть и логирование
        settings.PROXY_URL = new_proxy_url
        settings.update_env_var("PROXY_URL", new_proxy_url)

        settings.LOG_LEVEL = new_log_level
        settings.update_env_var("LOG_LEVEL", new_log_level)

        flash("✅ Настройки обновлены и успешно сохранены в .env!", "success")
        return redirect(url_for("settings_panel"))

    has_ssl = bool(settings.SSL_CERT and settings.SSL_KEY and os.path.exists(settings.SSL_CERT) and os.path.exists(settings.SSL_KEY))
    current_settings = {
        "token": settings.TOKEN or "",
        "owner_id": settings.OWNER_ID or "",
        "timezone": getattr(settings, "TIMEZONE_NAME", "Asia/Krasnoyarsk"),
        "schedule_url": settings.SCHEDULE_URL or "",
        "plan_url": settings.PLAN_URL or "",
        "semester_start": settings.SEMESTER_START or "",
        "panel_user": settings.PANEL_USER or "admin",
        "panel_pass": settings.PANEL_PASS or "",
        "flask_secret": settings.FLASK_SECRET or "",
        "panel_port": settings.PANEL_PORT or 19999,
        "panel_url": settings.PANEL_URL or "",
        "ssl_cert": settings.SSL_CERT or "",
        "ssl_key": settings.SSL_KEY or "",
        "totp_secret": getattr(settings, "TOTP_SECRET", "") or "",
        "proxy_url": getattr(settings, "PROXY_URL", "") or "",
        "log_level": settings.LOG_LEVEL or "INFO",
        "use_ssl": has_ssl,
    }

    return render_template("settings.html", settings=current_settings)


# ================== УПРАВЛЕНИЕ (ADMIN И OWNER) ==================

@app.route("/control", methods=["GET"])
@role_required("owner", "admin")
def control_page():
    return render_template("control.html")


@app.route("/control/reset2fa", methods=["POST"])
@role_required("owner")
def action_reset2fa():
    """Сброс 2FA (только Owner)"""
    set_2fa_enabled(False)
    flash("🔑 2FA сброшено. При следующем входе снова отобразится QR-код.", "warning")
    return redirect(url_for("control_page"))


@app.route("/control/reload", methods=["POST"])
@role_required("owner", "admin", "mod")
def action_reload():
    """Обновление кэша расписания (Mod, Admin, Owner)"""
    try:
        schedule_cache.clear()
        asyncio.run(fetch_schedule(None))
        logger.info("Перезагрузка расписания через панель выполнена")
        flash("✅ Кэш расписания успешно обновлен", "success")
    except Exception as e:
        logger.error(f"Не удалось обновить расписание: {e}")
        flash(f"❌ Ошибка обновления: {e}", "danger")
    return redirect(url_for("control_page" if get_user_role() in ("owner", "admin") else "users_page"))


@app.route("/control/fullreload", methods=["POST"])
@role_required("owner", "admin")
def action_fullreload():
    """Полная перезагрузка кэша расписания и преподавателей (Admin, Owner)"""
    try:
        schedule_cache.clear()
        teachers_cache.clear()
        asyncio.run(fetch_schedule(None))
        asyncio.run(fetch_teachers(None))
        logger.info("Полная перезагрузка через панель выполнена")
        flash("✅ Полная перезагрузка расписания и преподавателей завершена", "success")
    except Exception as e:
        logger.error(f"Не удалось выполнить полную перезагрузку: {e}")
        flash(f"❌ Ошибка перезагрузки: {e}", "danger")
    return redirect(url_for("control_page"))


@app.route("/control/broadcast", methods=["POST"])
@role_required("owner", "admin")
def action_broadcast():
    """Общая рассылка сообщений (Admin, Owner)"""
    text = (request.form.get("message") or "").strip()
    if not text or len(text) > 2000:
        flash("Введите корректный текст рассылки!", "danger")
        return redirect(url_for("control_page"))

    users_data = user_manager.get_all_users()
    if not users_data:
        flash("Нет пользователей для рассылки", "warning")
        return redirect(url_for("control_page"))

    if not settings.TOKEN:
        flash("TOKEN не задан в .env", "danger")
        return redirect(url_for("control_page"))

    ok, fail = 0, 0
    with get_httpx_client(timeout=10.0) as client:
        for uid in list(users_data.keys()):
            try:
                resp = client.post(
                    f"https://api.telegram.org/bot{settings.TOKEN}/sendMessage",
                    json={"chat_id": int(uid), "text": f"🔔 {text}"}
                )
                if resp.is_success:
                    ok += 1
                else:
                    fail += 1
            except Exception as e:
                logger.error(f"Ошибка при отправке broadcast {uid}: {e}")
                fail += 1

    logger.info(f"Рассылка через веб-панель завершена. Успех: {ok}, Ошибок: {fail}")
    flash(f"✅ Рассылка завершена. Успех: {ok}, Ошибок: {fail}", "success")
    return redirect(url_for("control_page"))


def run_flask():
    """Запуск Flask сервера"""
    if use_ssl:
        print("🔐 SSL включён. Панель доступна по HTTPS.")
        app.run(host="0.0.0.0", port=19999, ssl_context=(settings.SSL_CERT, settings.SSL_KEY), debug=False)
    else:
        print("⚠️ SSL не настроен, панель работает по HTTP.")
        app.run(host="0.0.0.0", port=19999, debug=False)
