import pytest
import threading
from pathlib import Path
from scr.core.users import UserManager
from scr.core.stats import StatsManager


def test_user_manager_crud(temp_dir):
    file_path = temp_dir / "test_users.json"
    manager = UserManager(owner_id=111, file_path=file_path)

    assert manager.is_allowed(111)
    assert manager.get_role(111) == "owner"

    assert not manager.is_allowed(222)
    assert manager.get_role(222) == "unknown"

    # Add user
    assert manager.add_user(222, role="user", username="john_doe")
    assert manager.is_allowed(222)
    assert manager.get_role(222) == "user"

    # Modify role
    assert manager.set_role(222, "admin")
    assert manager.get_role(222) == "admin"
    assert manager.is_mod_or_admin(222)

    # Persistence check
    manager2 = UserManager(owner_id=111, file_path=file_path)
    assert manager2.is_allowed(222)
    assert manager2.get_role(222) == "admin"

    # Remove user
    assert manager2.remove_user(222)
    assert not manager2.is_allowed(222)


def test_user_manager_thread_safety(temp_dir):
    file_path = temp_dir / "concurrent_users.json"
    manager = UserManager(owner_id=1, file_path=file_path)

    def worker(start_id, count):
        for i in range(start_id, start_id + count):
            manager.add_user(i, role="user", username=f"user_{i}")

    threads = []
    for t_idx in range(5):
        t = threading.Thread(target=worker, args=(t_idx * 100 + 10, 20))
        threads.append(t)
        t.start()

    for t in threads:
        t.join()

    all_users = manager.get_all_users()
    assert len(all_users) == 100


def test_stats_manager_operations(temp_dir):
    file_path = temp_dir / "test_stats.json"
    manager = StatsManager(file_path=file_path)

    manager.record_activity(12345, is_command=True)
    manager.add_search_query()
    manager.add_schedule_request()
    manager.add_error()
    manager.save()

    snap = manager.get_snapshot()
    assert snap["unique_users_count"] == 1
    assert snap["total_messages"] == 1
    assert snap["commands_executed"] == 1
    assert snap["search_queries"] == 1
    assert snap["schedule_requests"] == 1
    assert snap["errors"] == 1

    # Reload from disk
    manager2 = StatsManager(file_path=file_path)
    snap2 = manager2.get_snapshot()
    assert snap2["unique_users_count"] == 1
    assert snap2["commands_executed"] == 1
