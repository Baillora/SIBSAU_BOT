import json
import os
import tempfile
import threading
from datetime import datetime
from collections import defaultdict
from pathlib import Path
from typing import Dict, Any, Set
from scr.core.settings import STATS_FILE


class StatsManager:
    """
    Потокобезопасный менеджер статистики с атомарным сохранением.
    """

    def __init__(self, file_path: Path = STATS_FILE):
        self.file_path = Path(file_path)
        self._lock = threading.RLock()
        self.stats: Dict[str, Any] = self._create_empty_stats()
        self.load()

    def _create_empty_stats(self) -> Dict[str, Any]:
        return {
            "unique_users": set(),
            "total_messages": 0,
            "schedule_requests": 0,
            "search_queries": 0,
            "commands_executed": 0,
            "errors": 0,
            "commands_per_user": defaultdict(int),
            "peak_usage": defaultdict(int),
            "daily_active_users": defaultdict(set),
        }

    def save(self) -> None:
        """Атомарное сохранение статистики в JSON"""
        with self._lock:
            serializable = {
                "unique_users": list(self.stats["unique_users"]),
                "total_messages": self.stats["total_messages"],
                "schedule_requests": self.stats["schedule_requests"],
                "search_queries": self.stats["search_queries"],
                "commands_executed": self.stats["commands_executed"],
                "errors": self.stats["errors"],
                "commands_per_user": dict(self.stats["commands_per_user"]),
                "peak_usage": dict(self.stats["peak_usage"]),
                "daily_active_users": {
                    k: list(v) for k, v in self.stats["daily_active_users"].items()
                },
            }

            self.file_path.parent.mkdir(parents=True, exist_ok=True)
            dir_path = self.file_path.parent
            temp_fd, temp_path = tempfile.mkstemp(dir=dir_path, prefix="stats_", suffix=".tmp")
            try:
                with open(temp_fd, "w", encoding="utf-8") as f:
                    json.dump(serializable, f, indent=4, ensure_ascii=False)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(temp_path, self.file_path)
            except Exception:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
                raise

    def load(self) -> Dict[str, Any]:
        """Загрузка статистики из JSON"""
        with self._lock:
            if not self.file_path.exists():
                return self.stats

            try:
                with open(self.file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)

                if isinstance(data, dict):
                    self.stats["unique_users"] = set(data.get("unique_users", []))
                    self.stats["total_messages"] = data.get("total_messages", 0)
                    self.stats["schedule_requests"] = data.get("schedule_requests", 0)
                    self.stats["search_queries"] = data.get("search_queries", 0)
                    self.stats["commands_executed"] = data.get("commands_executed", 0)
                    self.stats["errors"] = data.get("errors", 0)

                    self.stats["commands_per_user"] = defaultdict(
                        int, {str(k): v for k, v in data.get("commands_per_user", {}).items()}
                    )
                    self.stats["peak_usage"] = defaultdict(
                        int, {str(k): v for k, v in data.get("peak_usage", {}).items()}
                    )
                    self.stats["daily_active_users"] = defaultdict(
                        set,
                        {k: set(v) for k, v in data.get("daily_active_users", {}).items()},
                    )
            except Exception:
                pass
            return self.stats

    def record_activity(self, user_id: int, is_command: bool = True) -> None:
        """Единый метод фиксации активности пользователя"""
        with self._lock:
            uid_str = str(user_id)
            self.stats["unique_users"].add(user_id)
            self.stats["total_messages"] += 1
            if is_command:
                self.stats["commands_executed"] += 1
                self.stats["commands_per_user"][uid_str] += 1

            hour_str = str(datetime.now().hour)
            self.stats["peak_usage"][hour_str] += 1

            day_str = datetime.now().strftime("%Y-%m-%d")
            self.stats["daily_active_users"][day_str].add(user_id)

    def increment_command(self, user_id: int) -> None:
        with self._lock:
            self.stats["commands_per_user"][str(user_id)] += 1

    def record_peak_usage(self) -> None:
        with self._lock:
            hour_str = str(datetime.now().hour)
            self.stats["peak_usage"][hour_str] += 1

    def record_daily_active(self, user_id: int) -> None:
        with self._lock:
            day_str = datetime.now().strftime("%Y-%m-%d")
            self.stats["daily_active_users"][day_str].add(user_id)

    def add_search_query(self) -> None:
        with self._lock:
            self.stats["search_queries"] += 1

    def add_schedule_request(self) -> None:
        with self._lock:
            self.stats["schedule_requests"] += 1

    def add_error(self) -> None:
        with self._lock:
            self.stats["errors"] += 1

    def get_snapshot(self) -> Dict[str, Any]:
        """Возвращает безопасную копию текущей статистики для отображения"""
        with self._lock:
            return {
                "unique_users_count": len(self.stats["unique_users"]),
                "unique_users": list(self.stats["unique_users"]),
                "total_messages": self.stats["total_messages"],
                "schedule_requests": self.stats["schedule_requests"],
                "search_queries": self.stats["search_queries"],
                "commands_executed": self.stats["commands_executed"],
                "errors": self.stats["errors"],
                "commands_per_user": dict(self.stats["commands_per_user"]),
                "peak_usage": dict(self.stats["peak_usage"]),
                "daily_active_users": {
                    k: list(v) for k, v in self.stats["daily_active_users"].items()
                },
            }


# Глобальный синглтон
stats_manager = StatsManager(STATS_FILE)
stats = stats_manager.stats


# Функции-обертки для обратной совместимости
def save_stats() -> None:
    stats_manager.save()


def increment_user_commands(user_id: int) -> None:
    stats_manager.increment_command(user_id)


def record_peak_usage() -> None:
    stats_manager.record_peak_usage()


def record_daily_active(user_id: int) -> None:
    stats_manager.record_daily_active(user_id)


def add_search_query() -> None:
    stats_manager.add_search_query()


def add_schedule_request() -> None:
    stats_manager.add_schedule_request()
