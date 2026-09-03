import json
import os
import secrets
import tempfile
import threading
import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple

from scr.core.settings import DATA_DIR, BOT_TIMEZONE, get_invite_link_url
from scr.core import users
from scr.core.logger import logger

INVITE_LINKS_FILE = DATA_DIR / "invite_links.json"


class InviteManager:
    """
    Потокобезопасный менеджер ссылок-приглашений с лимитами использования и сроком действия.
    """

    def __init__(self, file_path: Path = INVITE_LINKS_FILE):
        self.file_path = Path(file_path)
        self._lock = threading.RLock()
        self.invites: Dict[str, Dict[str, Any]] = {}
        self.load()

    def load(self) -> Dict[str, Dict[str, Any]]:
        """Загрузка инвайт-ссылок из JSON"""
        with self._lock:
            if not self.file_path.exists():
                self.invites = {}
                return self.invites

            try:
                with open(self.file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    self.invites = data.get("invites", data)
                else:
                    self.invites = {}
                return self.invites
            except Exception as e:
                logger.error(f"Ошибка при чтении {self.file_path}: {e}")
                self.invites = {}
                return self.invites

    def save(self) -> None:
        """Атомарное сохранение инвайт-ссылок в JSON"""
        with self._lock:
            data = {"invites": self.invites}
            self.file_path.parent.mkdir(parents=True, exist_ok=True)

            temp_fd, temp_path = tempfile.mkstemp(
                dir=self.file_path.parent, prefix="invites_", suffix=".tmp"
            )
            try:
                with open(temp_fd, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=4, ensure_ascii=False)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(temp_path, self.file_path)
            except Exception as e:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
                logger.error(f"Ошибка при сохранении {self.file_path}: {e}")
                raise

    def create_invite(
        self,
        title: str,
        role: str = "user",
        max_uses: int = 0,
        expires_at: Optional[str] = None,
        created_by: str = "admin"
    ) -> Dict[str, Any]:
        """
        Создает новую ссылку-приглашение.
        max_uses: 0 = бесконечно, >0 = лимит переходов.
        expires_at: строка ISO даты (YYYY-MM-DD или YYYY-MM-DDTHH:MM) или None.
        """
        with self._lock:
            token = secrets.token_urlsafe(6).replace("-", "").replace("_", "")
            while token in self.invites:
                token = secrets.token_urlsafe(6).replace("-", "").replace("_", "")

            now = datetime.datetime.now(BOT_TIMEZONE)
            created_at_iso = now.isoformat()
            created_at_formatted = now.strftime("%d.%m.%Y %H:%M")

            # Нормализация даты истечения
            exp_iso = None
            exp_formatted = "Бессрочно"
            if expires_at and str(expires_at).strip():
                try:
                    exp_clean = str(expires_at).strip()
                    if "T" in exp_clean:
                        exp_dt = datetime.datetime.fromisoformat(exp_clean)
                    else:
                        exp_dt = datetime.datetime.strptime(exp_clean, "%Y-%m-%d")
                    # Привязываем таймзону если не задана
                    if exp_dt.tzinfo is None:
                        exp_dt = exp_dt.replace(tzinfo=BOT_TIMEZONE)
                    exp_iso = exp_dt.isoformat()
                    exp_formatted = exp_dt.strftime("%d.%m.%Y %H:%M")
                except Exception as e:
                    logger.warning(f"Не удалось распарсить дату истечения инвайта '{expires_at}': {e}")
                    exp_iso = None

            invite_obj = {
                "token": token,
                "title": title.strip() or f"Приглашение #{token}",
                "role": role if role in ("user", "mod", "admin") else "user",
                "max_uses": max(0, int(max_uses)),
                "used_count": 0,
                "expires_at": exp_iso,
                "expires_at_formatted": exp_formatted,
                "created_at": created_at_iso,
                "created_at_formatted": created_at_formatted,
                "created_by": str(created_by),
                "is_active": True,
                "used_by": []
            }

            self.invites[token] = invite_obj
            self.save()
            logger.info(f"Создана инвайт-ссылка [{token}] '{invite_obj['title']}' (роль: {role}, лимит: {max_uses})")
            return invite_obj

    def get_invite(self, token: str) -> Optional[Dict[str, Any]]:
        """Получить информацию по токену инвайта"""
        with self._lock:
            return self.invites.get(token)

    def get_all_invites(self) -> List[Dict[str, Any]]:
        """Получить все инвайты в виде списка (отсортированы по новизне)"""
        with self._lock:
            items = list(self.invites.values())
            items.sort(key=lambda x: x.get("created_at", ""), reverse=True)
            for it in items:
                it["url"] = get_invite_link_url(it["token"])
                # Проверяем не истек ли срок
                if it.get("is_active") and it.get("expires_at"):
                    try:
                        exp_dt = datetime.datetime.fromisoformat(it["expires_at"])
                        if exp_dt.tzinfo is None:
                            exp_dt = exp_dt.replace(tzinfo=BOT_TIMEZONE)
                        if datetime.datetime.now(BOT_TIMEZONE) > exp_dt:
                            it["is_expired"] = True
                    except Exception:
                        pass
                if it.get("max_uses", 0) > 0 and it.get("used_count", 0) >= it.get("max_uses", 0):
                    it["is_exhausted"] = True
            return items

    def delete_invite(self, token: str) -> bool:
        """Удалить инвайт-ссылку"""
        with self._lock:
            if token in self.invites:
                del self.invites[token]
                self.save()
                logger.info(f"Инвайт-ссылка [{token}] удалена")
                return True
            return False

    def toggle_active(self, token: str) -> bool:
        """Включить/выключить действие инвайт-ссылки"""
        with self._lock:
            if token in self.invites:
                cur = self.invites[token].get("is_active", True)
                self.invites[token]["is_active"] = not cur
                self.save()
                logger.info(f"Инвайт-ссылка [{token}] переключена: active={not cur}")
                return True
            return False

    def use_invite(self, token: str, user_id: int, username: str) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """
        Попытка использовать ссылку-приглашение.
        Возвращает: (успех: bool, сообщение: str, данные_инвайта: dict|None)
        """
        with self._lock:
            invite = self.invites.get(token)
            if not invite:
                return False, "Ссылка-приглашение не найдена.", None

            if not invite.get("is_active", True):
                return False, "Эта ссылка-приглашение была деактивирована администратором.", None

            # Проверка срока действия
            exp_iso = invite.get("expires_at")
            if exp_iso:
                try:
                    exp_dt = datetime.datetime.fromisoformat(exp_iso)
                    if exp_dt.tzinfo is None:
                        exp_dt = exp_dt.replace(tzinfo=BOT_TIMEZONE)
                    if datetime.datetime.now(BOT_TIMEZONE) > exp_dt:
                        invite["is_active"] = False
                        self.save()
                        return False, "Срок действия этой ссылки-приглашения истёк.", None
                except Exception as e:
                    logger.error(f"Ошибка проверки даты инвайта: {e}")

            # Проверка лимита использований
            max_uses = invite.get("max_uses", 0)
            used_count = invite.get("used_count", 0)
            if max_uses > 0 and used_count >= max_uses:
                invite["is_active"] = False
                self.save()
                return False, "Лимит использований для этой ссылки исчерпан.", None

            # Авторизуем пользователя в боте
            target_role = invite.get("role", "user")
            users.user_manager.add_user(user_id=user_id, role=target_role, username=username)

            # Обновляем статистику инвайта
            invite["used_count"] = used_count + 1
            now_str = datetime.datetime.now(BOT_TIMEZONE).strftime("%d.%m.%Y %H:%M")
            invite.setdefault("used_by", []).append({
                "user_id": user_id,
                "username": username or "Неизвестно",
                "used_at": now_str
            })

            # Если достигнут лимит после этого перехода — деактивируем
            if max_uses > 0 and invite["used_count"] >= max_uses:
                invite["is_active"] = False

            self.save()
            logger.info(f"✅ Пользователь {username} ({user_id}) успешно активировал инвайт [{token}] (роль: {target_role})")
            return True, "Успешная активация", invite


# Глобальный экземпляр
invite_manager = InviteManager()
