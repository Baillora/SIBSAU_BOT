import pytest
from scr.admin_panel.app import app, check_login, set_2fa_enabled


@pytest.fixture
def client():
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as client:
        yield client


def test_check_login():
    assert check_login("admin", "admin")
    assert not check_login("admin", "wrong_password")
    assert not check_login("wrong_user", "admin")


def test_login_page_get(client):
    response = client.get("/login")
    assert response.status_code == 200
    assert "Вход в панель" in response.get_data(as_text=True)


def test_login_post_invalid(client):
    response = client.post("/login", data={"username": "admin", "password": "wrong"})
    assert response.status_code == 200
    assert "Неверный логин или пароль" in response.get_data(as_text=True)


def test_login_post_valid(client):
    response = client.post("/login", data={"username": "admin", "password": "admin"}, follow_redirects=False)
    assert response.status_code == 302
    assert "/2fa" in response.headers["Location"]


def test_index_unauthorized(client):
    response = client.get("/")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_index_authorized(client, mock_settings):
    with client.session_transaction() as sess:
        sess["logged_in"] = True
        sess["username"] = "admin"

    response = client.get("/")
    assert response.status_code == 200
    assert "Статистика" in response.get_data(as_text=True)


def test_users_management_flow(client, mock_settings):
    with client.session_transaction() as sess:
        sess["logged_in"] = True
        sess["username"] = "admin"

    # Add user
    response = client.post("/users/add", data={"user_id": "555555", "role": "user"}, follow_redirects=True)
    assert response.status_code == 200
    assert "555555" in response.get_data(as_text=True)

    # Change role
    response = client.post("/users/setrole", data={"user_id": "555555", "role": "admin"}, follow_redirects=True)
    assert response.status_code == 200
    assert "изменена на admin" in response.get_data(as_text=True)

    # Delete user
    response = client.post("/users/delete/555555", follow_redirects=True)
    assert response.status_code == 200
    assert "удалён" in response.get_data(as_text=True)


def test_logs_page(client, mock_settings):
    with client.session_transaction() as sess:
        sess["logged_in"] = True
        sess["username"] = "admin"

    response = client.get("/logs")
    assert response.status_code == 200
    assert "Логи" in response.get_data(as_text=True)

    # Ajax
    ajax_resp = client.get("/logs?ajax=1")
    assert ajax_resp.status_code == 200
