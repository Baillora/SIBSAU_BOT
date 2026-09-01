import pytest
import time
from unittest.mock import AsyncMock, patch, MagicMock
from scr.core.auth_tokens import AuthTokenManager
from scr.core.users import UserManager
from scr.admin_panel.app import app
from tests.conftest import create_mock_update
from scr.bot.handlers.web_auth import web_auth_command


@pytest.fixture
def auth_mgr():
    return AuthTokenManager(token_ttl=2)  # 2 секунды для быстрых тестов


def test_auth_token_manager_lifecycle(auth_mgr):
    # 1. Создание токена
    token, code, err = auth_mgr.create_auth_token(12345, "testuser", "user")
    assert token is not None
    assert code is not None
    assert len(code) == 6
    assert err is None

    # 2. Ограничение частоты запросов
    t2, c2, err2 = auth_mgr.create_auth_token(12345, "testuser", "user")
    assert t2 is None
    assert "подождите" in err2

    # 3. Верификация по ссылке (magic link)
    data = auth_mgr.verify_and_consume_token(token)
    assert data is not None
    assert data["user_id"] == 12345
    assert data["role"] == "user"

    # 4. Повторное использование невозможно (одноразовый)
    assert auth_mgr.verify_and_consume_token(token) is None


def test_auth_token_manager_otp_code(auth_mgr):
    token, code, _ = auth_mgr.create_auth_token(67890, "student", "user")
    assert code is not None

    # Неверный код
    assert auth_mgr.verify_and_consume_code(67890, "000000") is None

    # Верный код
    data = auth_mgr.verify_and_consume_code(67890, code)
    assert data is not None
    assert data["user_id"] == 67890

    # Повторный ввод использованного кода
    assert auth_mgr.verify_and_consume_code(67890, code) is None


def test_auth_token_manager_expiration(auth_mgr):
    token, code, _ = auth_mgr.create_auth_token(11111, "user1", "user")
    time.sleep(2.1)
    assert auth_mgr.verify_and_consume_token(token) is None
    assert auth_mgr.verify_and_consume_code(11111, code) is None


# ================== ТЕСТЫ FLASK TELEGRAM АВТОРИЗАЦИИ ==================

@pytest.fixture
def client(tmp_path, monkeypatch):
    test_file = tmp_path / "allowed_users.json"
    mgr = UserManager(owner_id=999999, file_path=test_file)
    mgr.add_user(111, role="user", username="student1")
    mgr.add_user(222, role="mod", username="mod1")
    mgr.add_user(333, role="admin", username="admin1")

    monkeypatch.setattr("scr.admin_panel.app.user_manager", mgr)
    monkeypatch.setattr("scr.core.users.user_manager", mgr)
    monkeypatch.setattr("scr.core.settings.OWNER_ID", 999999)

    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    from scr.admin_panel.app import limiter
    limiter.enabled = False

    with app.test_client() as c:
        yield c, mgr

    limiter.enabled = True


def test_auth_telegram_magic_link_success(client):
    c, mgr = client
    from scr.admin_panel.app import auth_token_manager
    token, code, _ = auth_token_manager.create_auth_token(111, "student1", "user")

    resp = c.get(f"/auth/telegram?token={token}", follow_redirects=True)
    assert resp.status_code == 200
    # Студент перенаправляется на расписание
    assert "Расписание" in resp.get_data(as_text=True)


def test_auth_telegram_magic_link_invalid(client):
    c, mgr = client
    resp = c.get("/auth/telegram?token=invalid_token", follow_redirects=True)
    assert resp.status_code == 200
    assert "недействительна" in resp.get_data(as_text=True)


def test_auth_telegram_code_success(client):
    c, mgr = client
    from scr.admin_panel.app import auth_token_manager
    _, code, _ = auth_token_manager.create_auth_token(333, "admin1", "admin")

    resp = c.post("/auth/telegram_code", data={"telegram_id": "333", "code": code}, follow_redirects=True)
    assert resp.status_code == 200
    # Админ перенаправляется на главную статистику
    assert "Статистика" in resp.get_data(as_text=True)


def test_auth_telegram_code_unauthorized_user(client):
    c, mgr = client
    from scr.admin_panel.app import auth_token_manager
    _, code, _ = auth_token_manager.create_auth_token(888888, "stranger", "user")

    resp = c.post("/auth/telegram_code", data={"telegram_id": "888888", "code": code}, follow_redirects=True)
    assert resp.status_code == 200
    assert "Доступ запрещен" in resp.get_data(as_text=True)


def test_remember_me_checkbox(client):
    c, mgr = client
    from scr.admin_panel.app import auth_token_manager
    auth_token_manager._rate_limits.clear()

    # 1. Без галочки Запомнить меня -> session.permanent = False
    _, code1, _ = auth_token_manager.create_auth_token(111, "student1", "user")
    c.post("/auth/telegram_code", data={"telegram_id": "111", "code": code1}, follow_redirects=True)
    with c.session_transaction() as sess:
        assert sess.permanent is False

    # 2. С галочкой Запомнить меня -> session.permanent = True
    auth_token_manager._rate_limits.clear()
    _, code2, _ = auth_token_manager.create_auth_token(222, "mod1", "mod")
    c.post("/auth/telegram_code", data={"telegram_id": "222", "code": code2, "remember_me": "1"}, follow_redirects=True)
    with c.session_transaction() as sess:
        assert sess.permanent is True


# ================== ТЕСТЫ RBAC (МАТРИЦА ПРАВ) ==================

def test_rbac_student_restrictions(client):
    c, mgr = client
    with c.session_transaction() as sess:
        sess["logged_in"] = True
        sess["telegram_id"] = 111
        sess["username"] = "student1"
        sess["role"] = "user"

    # 1. Расписание доступно
    assert c.get("/schedule").status_code == 200

    # 2. Статистика перенаправляет на расписание
    resp = c.get("/", follow_redirects=True)
    assert resp.status_code == 200
    assert "Расписание" in resp.get_data(as_text=True)

    # 3. Пользователи недоступны
    resp = c.get("/users", follow_redirects=True)
    assert "нет прав" in resp.get_data(as_text=True)

    # 4. Логи недоступны
    resp = c.get("/logs", follow_redirects=True)
    assert "нет прав" in resp.get_data(as_text=True)

    # 5. Настройки недоступны
    resp = c.get("/settings_panel", follow_redirects=True)
    assert "нет прав" in resp.get_data(as_text=True)

    # 6. Управление недоступно
    resp = c.get("/control", follow_redirects=True)
    assert "нет прав" in resp.get_data(as_text=True)


def test_rbac_moderator_permissions(client):
    c, mgr = client
    with c.session_transaction() as sess:
        sess["logged_in"] = True
        sess["telegram_id"] = 222
        sess["username"] = "mod1"
        sess["role"] = "mod"

    # Расписание доступно
    assert c.get("/schedule").status_code == 200
    # Список пользователей доступен
    assert c.get("/users").status_code == 200

    # Модератор не может менять роли
    resp = c.post("/users/setrole", data={"user_id": "111", "role": "admin"}, follow_redirects=True)
    assert "нет прав" in resp.get_data(as_text=True)

    # Модератор не может очищать или смотреть логи
    assert c.get("/logs", follow_redirects=True).status_code == 200

    # Модератор может добавлять только user (попытка назначить admin сбрасывается в user)
    c.post("/users/add", data={"user_id": "555", "role": "admin"}, follow_redirects=True)
    assert mgr.get_role(555) == "user"


def test_rbac_admin_permissions(client):
    c, mgr = client
    with c.session_transaction() as sess:
        sess["logged_in"] = True
        sess["telegram_id"] = 333
        sess["username"] = "admin1"
        sess["role"] = "admin"

    # Статистика, расписание, пользователи, логи, управление доступны
    assert c.get("/").status_code == 200
    assert c.get("/schedule").status_code == 200
    assert c.get("/users").status_code == 200
    assert c.get("/logs").status_code == 200
    assert c.get("/control").status_code == 200

    # Админ НЕ может очищать логи (только Owner)
    resp = c.post("/logs/clear", follow_redirects=True)
    assert "нет прав" in resp.get_data(as_text=True)

    # Админ НЕ может менять системные настройки (только Owner)
    resp = c.get("/settings_panel", follow_redirects=True)
    assert "нет прав" in resp.get_data(as_text=True)


def test_rbac_owner_full_access(client):
    c, mgr = client
    with c.session_transaction() as sess:
        sess["logged_in"] = True
        sess["telegram_id"] = 999999
        sess["username"] = "owner"
        sess["role"] = "owner"
        sess["is_master_admin"] = True

    assert c.get("/").status_code == 200
    assert c.get("/schedule").status_code == 200
    assert c.get("/users").status_code == 200
    assert c.get("/logs").status_code == 200
    assert c.get("/settings_panel").status_code == 200
    assert c.get("/control").status_code == 200


# ================== ТЕСТЫ БОТ-КОМАНДЫ /web И /setpanel ==================

@pytest.mark.asyncio
async def test_bot_web_command_authorized(mock_settings):
    user_id = mock_settings["owner_id"]
    update, context, bot = create_mock_update(user_id, "/web")

    await web_auth_command(update, context)
    update.message.reply_text.assert_called()
    call_kwargs = update.message.reply_text.call_args[1]
    reply_text = update.message.reply_text.call_args[0][0]
    assert "Авторизация в Веб-панели" in reply_text
    assert "одноразовый код" in reply_text
    assert "/auth/telegram?token=" in reply_text
    # Проверка инлайн кнопки быстрого входа
    reply_markup = call_kwargs.get("reply_markup")
    assert reply_markup is not None
    assert "/auth/telegram?token=" in reply_markup.inline_keyboard[0][0].url


@pytest.mark.asyncio
async def test_bot_web_command_unauthorized(mock_settings):
    user_id = 999111222  # Неавторизованный
    update, context, bot = create_mock_update(user_id, "/web")

    await web_auth_command(update, context)
    update.message.reply_text.assert_called()
    reply_text = update.message.reply_text.call_args[0][0]
    assert "Ваш ID" in reply_text


@pytest.mark.asyncio
async def test_bot_setpanel_command(mock_settings):
    from scr.bot.handlers.admin import setpanel_command
    import scr.core.settings as settings

    user_id = mock_settings["owner_id"]
    update, context, bot = create_mock_update(user_id, "/setpanel")
    context.args = ["http://my-ddns.domain.ru:19999"]

    await setpanel_command(update, context)
    assert settings.PANEL_URL == "http://my-ddns.domain.ru:19999"
    assert "успешно обновлен" in update.message.reply_text.call_args[0][0]

    # Сброс на авто
    context.args = ["auto"]
    await setpanel_command(update, context)
    assert settings.PANEL_URL == ""
    assert "автоматическое определение" in update.message.reply_text.call_args[0][0]
