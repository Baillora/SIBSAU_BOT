import json
import os
from scr.core.settings import ALLOWED_USERS_FILE, OWNER_ID


def load_allowed_users():
    """Загрузка пользователей из allowed_users.json"""
    if not os.path.exists(ALLOWED_USERS_FILE):
        return {"users": {}}
    try:
        with open(ALLOWED_USERS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        # гарантируем правильную структуру
        if "users" not in data:
            data = {"users": data}
        return data
    except Exception:
        return {"users": {}}


def save_allowed_users(users):
    """Сохраняем пользователей в JSON (всегда {"users": {}})"""
    if "users" not in users:
        users = {"users": users}
    with open(ALLOWED_USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(users, f, indent=4, ensure_ascii=False)


def is_user_allowed(user_id: int) -> bool:
    users = load_allowed_users()
    return str(user_id) in users["users"] or user_id == OWNER_ID


def get_user_role(user_id: int) -> str:
    if user_id == OWNER_ID:
        return "owner"
    users = load_allowed_users()
    return users["users"].get(str(user_id), {}).get("role", "user")


def is_mod_or_admin(user_id: int) -> bool:
    role = get_user_role(user_id)
    return role in ["mod", "admin", "owner"]


class UserManager:
    def __init__(self, owner_id: int):
        self.owner_id = owner_id
        self.users = load_allowed_users()

    def save(self):
        save_allowed_users(self.users)

    def add_user(self, user_id: int, role: str = "user", username: str = None):
        if str(user_id) == str(self.owner_id):
            return  # OWNER не пишем в JSON
        self.users["users"][str(user_id)] = {
            "role": role,
            "username": username or "Неизвестно"
        }
        self.save()

    def remove_user(self, user_id: int):
        if str(user_id) in self.users["users"]:
            del self.users["users"][str(user_id)]
            self.save()

    def get_role(self, user_id: int) -> str:
        if user_id == self.owner_id:
            return "owner"
        return self.users["users"].get(str(user_id), {}).get("role", "user")

    def is_allowed(self, user_id: int) -> bool:
        return user_id == self.owner_id or str(user_id) in self.users["users"]
