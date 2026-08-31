import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Dict, Any, Optional
from scr.core.settings import ALLOWED_USERS_FILE, OWNER_ID


class UserManager:
    """
    Потокобезопасный менеджер пользователей с атомарным сохранением в JSON.
    """

    def __init__(self, owner_id: int = OWNER_ID, file_path: Path = ALLOWED_USERS_FILE):
        self.owner_id = int(owner_id) if str(owner_id).isdigit() else 0
        self.file_path = Path(file_path)
        self._lock = threading.RLock()
        self.users: Dict[str, Any] = {"users": {}}
        self.load()

    def load(self) -> Dict[str, Any]:
        """Загрузка и нормализация пользователей из JSON"""
        with self._lock:
            if not self.file_path.exists():
                self.users = {"users": {}}
                return self.users

            try:
                with open(self.file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)

                normalized = {}
                if isinstance(data, dict):
                    raw_users = data.get("users", data)
                    if isinstance(raw_users, dict):
                        for uid, val in raw_users.items():
                            if str(uid) == "users":
                                continue
                            if isinstance(val, dict):
                                normalized[str(uid)] = {
                                    "role": str(val.get("role", "user")),
                                    "username": str(val.get("username", "Неизвестно")),
                                    "subgroup": str(val.get("subgroup", "all")),
                                    "notifications": bool(val.get("notifications", False)),
                                }
                            else:
                                normalized[str(uid)] = {
                                    "role": str(val),
                                    "username": "Неизвестно",
                                    "subgroup": "all",
                                    "notifications": False,
                                }

                self.users = {"users": normalized}
                return self.users
            except Exception:
                self.users = {"users": {}}
                return self.users

    def save(self) -> None:
        """Атомарное сохранение данных в JSON"""
        with self._lock:
            data = {"users": self.users.get("users", {})}
            self.file_path.parent.mkdir(parents=True, exist_ok=True)

            dir_path = self.file_path.parent
            temp_fd, temp_path = tempfile.mkstemp(dir=dir_path, prefix="users_", suffix=".tmp")
            try:
                with open(temp_fd, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=4, ensure_ascii=False)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(temp_path, self.file_path)
            except Exception:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
                raise

    def is_allowed(self, user_id: int) -> bool:
        """Проверка доступа пользователя к боту"""
        with self._lock:
            uid_str = str(user_id)
            if self.owner_id != 0 and user_id == self.owner_id:
                return True
            return uid_str in self.users.get("users", {})

    def get_role(self, user_id: int) -> str:
        """Получение роли пользователя"""
        with self._lock:
            if self.owner_id != 0 and user_id == self.owner_id:
                return "owner"
            uid_str = str(user_id)
            user_data = self.users.get("users", {}).get(uid_str)
            if user_data:
                return user_data.get("role", "user")
            return "unknown"

    def is_mod_or_admin(self, user_id: int) -> bool:
        """Проверка наличия прав модератора, администратора или владельца"""
        return self.get_role(user_id) in ["mod", "admin", "owner"]

    def add_user(self, user_id: int, role: str = "user", username: Optional[str] = None) -> bool:
        """Добавление пользователя в список разрешенных"""
        with self._lock:
            if self.owner_id != 0 and user_id == self.owner_id:
                return False
            uid_str = str(user_id)
            self.users.setdefault("users", {})[uid_str] = {
                "role": role,
                "username": username or "Неизвестно",
                "subgroup": "all",
                "notifications": False,
            }
            self.save()
            return True

    def remove_user(self, user_id: int) -> bool:
        """Удаление пользователя из списка разрешенных"""
        with self._lock:
            uid_str = str(user_id)
            if uid_str in self.users.get("users", {}):
                del self.users["users"][uid_str]
                self.save()
                return True
            return False

    def set_role(self, user_id: int, role: str) -> bool:
        """Изменение роли пользователя"""
        with self._lock:
            if self.owner_id != 0 and user_id == self.owner_id:
                return False
            uid_str = str(user_id)
            if uid_str in self.users.get("users", {}):
                self.users["users"][uid_str]["role"] = role
                self.save()
                return True
            return False

    def update_username(self, user_id: int, username: str) -> None:
        """Обновление username пользователя"""
        with self._lock:
            uid_str = str(user_id)
            if uid_str in self.users.get("users", {}):
                self.users["users"][uid_str]["username"] = username
                self.save()

    def get_subgroup(self, user_id: int) -> str:
        """Получение выбранной подгруппы ('1', '2' или 'all')"""
        with self._lock:
            uid_str = str(user_id)
            user_data = self.users.get("users", {}).get(uid_str, {})
            return str(user_data.get("subgroup", "all"))

    def set_subgroup(self, user_id: int, subgroup: str) -> bool:
        """Установка подгруппы ('1', '2' или 'all')"""
        with self._lock:
            if subgroup not in ("1", "2", "all"):
                subgroup = "all"
            uid_str = str(user_id)
            self.users.setdefault("users", {}).setdefault(uid_str, {
                "role": "owner" if (self.owner_id != 0 and user_id == self.owner_id) else "user",
                "username": "Owner" if (self.owner_id != 0 and user_id == self.owner_id) else "Пользователь",
            })
            self.users["users"][uid_str]["subgroup"] = subgroup
            self.save()
            return True

    def get_notifications(self, user_id: int) -> bool:
        """Получение статуса уведомлений"""
        with self._lock:
            uid_str = str(user_id)
            user_data = self.users.get("users", {}).get(uid_str, {})
            return bool(user_data.get("notifications", False))

    def set_notifications(self, user_id: int, enabled: bool) -> bool:
        """Включение/выключение уведомлений"""
        with self._lock:
            uid_str = str(user_id)
            self.users.setdefault("users", {}).setdefault(uid_str, {
                "role": "owner" if (self.owner_id != 0 and user_id == self.owner_id) else "user",
                "username": "Owner" if (self.owner_id != 0 and user_id == self.owner_id) else "Пользователь",
            })
            self.users["users"][uid_str]["notifications"] = bool(enabled)
            self.save()
            return True

    def get_all_users(self) -> Dict[str, Dict[str, Any]]:
        """Получение всех пользователей"""
        with self._lock:
            return dict(self.users.get("users", {}))


# Глобальный синглтон
user_manager = UserManager(owner_id=OWNER_ID, file_path=ALLOWED_USERS_FILE)


# Функции обратной совместимости
def load_allowed_users() -> Dict[str, Any]:
    return user_manager.load()


def save_allowed_users(data: Dict[str, Any]) -> None:
    with user_manager._lock:
        if "users" in data:
            user_manager.users = data
        else:
            user_manager.users = {"users": data}
        user_manager.save()


def is_user_allowed(user_id: int) -> bool:
    return user_manager.is_allowed(user_id)


def get_user_role(user_id: int) -> str:
    return user_manager.get_role(user_id)


def is_mod_or_admin(user_id: int) -> bool:
    return user_manager.is_mod_or_admin(user_id)
