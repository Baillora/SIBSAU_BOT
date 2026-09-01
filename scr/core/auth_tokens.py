import time
import secrets
import threading
from typing import Dict, Any, Optional, Tuple


class AuthTokenManager:
    """
    Потокобезопасный менеджер одноразовых токенов и OTP-кодов для авторизации в веб-панели через Telegram.
    """

    def __init__(self, token_ttl: int = 300):
        self.token_ttl = token_ttl  # Время жизни токена в секундах (5 минут)
        self._lock = threading.RLock()
        # token -> {"user_id": int, "username": str, "role": str, "code": str, "expires_at": float}
        self._tokens: Dict[str, Dict[str, Any]] = {}
        # user_id -> last_generation_timestamp
        self._rate_limits: Dict[int, float] = {}

    def _cleanup_expired(self) -> None:
        """Очистка просроченных токенов"""
        now = time.time()
        expired_keys = [k for k, v in self._tokens.items() if v.get("expires_at", 0) < now]
        for k in expired_keys:
            self._tokens.pop(k, None)

    def create_auth_token(self, user_id: int, username: str, role: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """
        Создание одноразового токена и 6-значного цифрового кода.
        Возвращает (token, otp_code, error_message).
        """
        with self._lock:
            self._cleanup_expired()
            now = time.time()

            # Ограничение частоты генерации: не чаще 1 раза в 5 секунд на одного пользователя
            last_gen = self._rate_limits.get(user_id, 0)
            if now - last_gen < 5:
                wait_sec = int(5 - (now - last_gen)) + 1
                return None, None, f"Пожалуйста, подождите {wait_sec} сек. перед запросом нового кода."

            # Удаляем старые токены этого же пользователя
            to_remove = [k for k, v in self._tokens.items() if v.get("user_id") == user_id]
            for k in to_remove:
                self._tokens.pop(k, None)

            token = secrets.token_urlsafe(32)
            # Генерация 6-значного криптографически безопасного кода
            otp_code = f"{secrets.randbelow(900000) + 100000}"

            self._tokens[token] = {
                "user_id": user_id,
                "username": username,
                "role": role,
                "code": otp_code,
                "expires_at": now + self.token_ttl
            }
            self._rate_limits[user_id] = now
            return token, otp_code, None

    def verify_and_consume_token(self, token: str) -> Optional[Dict[str, Any]]:
        """
        Проверка и однократное использование токена по ссылке (magic link).
        Возвращает словарь данных пользователя или None.
        """
        if not token:
            return None

        with self._lock:
            self._cleanup_expired()
            data = self._tokens.pop(token, None)
            if data and data.get("expires_at", 0) >= time.time():
                return data
            return None

    def verify_and_consume_code(self, user_id: int, code: str) -> Optional[Dict[str, Any]]:
        """
        Проверка и однократное использование 6-значного кода по ID пользователя.
        Возвращает словарь данных пользователя или None.
        """
        if not user_id or not code:
            return None

        clean_code = str(code).replace(" ", "").strip()

        with self._lock:
            self._cleanup_expired()
            found_token = None
            found_data = None

            for tok, data in self._tokens.items():
                if data.get("user_id") == user_id and data.get("code") == clean_code:
                    if data.get("expires_at", 0) >= time.time():
                        found_token = tok
                        found_data = data
                        break

            if found_token:
                self._tokens.pop(found_token, None)
                return found_data
            return None


# Глобальный экземпляр менеджера токенов авторизации
auth_token_manager = AuthTokenManager()
