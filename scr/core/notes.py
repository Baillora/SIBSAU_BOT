import json
import os
import tempfile
import threading
import uuid
import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional
from scr.core.settings import DATA_DIR

NOTES_FILE = DATA_DIR / "notes.json"
MAX_NOTES_PER_USER = 50
MAX_SUBJECT_LEN = 100
MAX_TEXT_LEN = 1000


class NotesManager:
    """Потокобезопасный менеджер заметок и дедлайнов студентов с ограничениями по объему данных"""

    def __init__(self, file_path: Path = NOTES_FILE):
        self.file_path = Path(file_path)
        self._lock = threading.RLock()
        self.notes: Dict[str, List[Dict[str, Any]]] = {}
        self.load()

    def load(self) -> Dict[str, List[Dict[str, Any]]]:
        """Загрузка заметок из файла"""
        with self._lock:
            if not self.file_path.exists():
                self.notes = {}
                return self.notes

            try:
                with open(self.file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    self.notes = data
                else:
                    self.notes = {}
                return self.notes
            except Exception:
                self.notes = {}
                return self.notes

    def save(self) -> None:
        """Атомарное сохранение заметок"""
        with self._lock:
            self.file_path.parent.mkdir(parents=True, exist_ok=True)
            dir_path = self.file_path.parent
            temp_fd, temp_path = tempfile.mkstemp(dir=dir_path, prefix="notes_", suffix=".tmp")
            try:
                with open(temp_fd, "w", encoding="utf-8") as f:
                    json.dump(self.notes, f, indent=4, ensure_ascii=False)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(temp_path, self.file_path)
            except Exception:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
                raise

    def add_note(self, user_id: int, subject: str, text: str) -> Optional[str]:
        """Добавление новой заметки с санитизацией и лимитами"""
        with self._lock:
            uid_str = str(user_id)
            user_notes = self.notes.setdefault(uid_str, [])

            if len(user_notes) >= MAX_NOTES_PER_USER:
                return None

            note_id = str(uuid.uuid4())[:8]
            created_at = datetime.datetime.now().strftime("%d.%m.%Y %H:%M")

            clean_subject = subject.strip()[:MAX_SUBJECT_LEN]
            clean_text = text.strip()[:MAX_TEXT_LEN]

            note_entry = {
                "id": note_id,
                "subject": clean_subject,
                "text": clean_text,
                "created_at": created_at,
            }

            user_notes.append(note_entry)
            self.save()
            return note_id

    def get_user_notes(self, user_id: int) -> List[Dict[str, Any]]:
        """Получение всех заметок пользователя"""
        with self._lock:
            uid_str = str(user_id)
            return list(self.notes.get(uid_str, []))

    def delete_note(self, user_id: int, note_id: str) -> bool:
        """Удаление заметки по ID"""
        with self._lock:
            uid_str = str(user_id)
            user_notes = self.notes.get(uid_str, [])
            filtered = [n for n in user_notes if n.get("id") != note_id]
            if len(filtered) < len(user_notes):
                self.notes[uid_str] = filtered
                self.save()
                return True
            return False

    def get_notes_for_subject(self, user_id: int, subject: str) -> List[Dict[str, Any]]:
        """Получение заметок пользователя по конкретному предмету"""
        with self._lock:
            uid_str = str(user_id)
            user_notes = self.notes.get(uid_str, [])
            sub_lower = subject.lower().strip()
            return [n for n in user_notes if sub_lower in n.get("subject", "").lower()]


# Глобальный синглтон
notes_manager = NotesManager(file_path=NOTES_FILE)
