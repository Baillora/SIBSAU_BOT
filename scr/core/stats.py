import json
import os
from datetime import datetime
from collections import defaultdict
from scr.core.settings import STATS_FILE


class StatsManager:
    def __init__(self, file_path: str = STATS_FILE):
        self.file_path = file_path
        self.stats = {
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
        self.load()

    # ---------------- Основное ----------------
    def save(self):
        serializable = self.stats.copy()
        serializable["unique_users"] = list(self.stats["unique_users"])
        serializable["commands_per_user"] = dict(self.stats["commands_per_user"])
        serializable["peak_usage"] = dict(self.stats["peak_usage"])
        serializable["daily_active_users"] = {
            k: list(v) for k, v in self.stats["daily_active_users"].items()
        }

        with open(self.file_path, "w", encoding="utf-8") as f:
            json.dump(serializable, f, indent=4, ensure_ascii=False)

    def load(self):
        if not os.path.exists(self.file_path):
            return
        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            self.stats["unique_users"] = set(data.get("unique_users", []))
            self.stats["total_messages"] = data.get("total_messages", 0)
            self.stats["schedule_requests"] = data.get("schedule_requests", 0)
            self.stats["search_queries"] = data.get("search_queries", 0)
            self.stats["commands_executed"] = data.get("commands_executed", 0)
            self.stats["errors"] = data.get("errors", 0)
            self.stats["commands_per_user"] = defaultdict(
                int, data.get("commands_per_user", {})
            )
            self.stats["peak_usage"] = defaultdict(
                int, data.get("peak_usage", {})
            )
            self.stats["daily_active_users"] = defaultdict(
                set,
                {k: set(v) for k, v in data.get("daily_active_users", {}).items()},
            )
        except Exception:
            pass

    # ---------------- Методы ----------------
    def increment_command(self, user_id: int):
        self.stats["commands_per_user"][user_id] += 1

    def record_peak_usage(self):
        hour = datetime.now().hour
        self.stats["peak_usage"][hour] += 1

    def record_daily_active(self, user_id: int):
        day = datetime.now().strftime("%Y-%m-%d")
        self.stats["daily_active_users"][day].add(user_id)

    def add_search_query(self):
        self.stats["search_queries"] += 1

    def add_schedule_request(self):
        self.stats["schedule_requests"] += 1


# ---------- Глобальный объект для совместимости ----------
stats_manager = StatsManager()
stats = stats_manager.stats

# Функции-обертки (чтобы старые импорты не ломались)
def save_stats():
    stats_manager.save()

def increment_user_commands(user_id: int):
    stats_manager.increment_command(user_id)

def record_peak_usage():
    stats_manager.record_peak_usage()

def record_daily_active(user_id: int):
    stats_manager.record_daily_active(user_id)

def add_search_query():
    stats_manager.add_search_query()
