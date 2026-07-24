import os
import time
import logging
from typing import List, Dict

logger = logging.getLogger("PulseCore.NotesTracker")

class NotesTracker:
    """Простий парсер оновлень у локальних Markdown файлах."""
    
    def __init__(self, workspace_path: str):
        self.workspace_path = workspace_path
        self.file_states = self._scan_directory()

    def _scan_directory(self) -> Dict[str, float]:
        """Сканує всі .md файли та зберігає їх час модифікації."""
        states = {}
        if not os.path.exists(self.workspace_path):
            return states

        for root, _, files in os.walk(self.workspace_path):
            for file in files:
                if file.endswith(".md") and "venv" not in root and ".git" not in root:
                    filepath = os.path.join(root, file)
                    try:
                        mtime = os.path.getmtime(filepath)
                        states[filepath] = mtime
                    except OSError:
                        pass
        return states

    def get_new_activity(self) -> List[Dict[str, str]]:
        """Повертає список файлів, які були змінені."""
        current_states = self._scan_directory()
        activity = []

        for filepath, mtime in current_states.items():
            # Якщо файл новий або час його зміни більший за збережений
            if filepath not in self.file_states or mtime > self.file_states[filepath]:
                filename = os.path.basename(filepath)
                activity.append({
                    "type": "note_update",
                    "file": filename,
                    "path": filepath,
                    "action": "modified" if filepath in self.file_states else "created"
                })
        
        self.file_states = current_states
        return activity