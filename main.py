import os
import time
import threading
import logging
import cmd
import yaml
from typing import List, Dict

# Підключаємо модулі парсингу
from src.tracker.git_watcher import GitActivityTracker
from src.tracker.notes_watcher import NotesTracker

# Підключаємо базу даних
from src.core.database import init_db, get_connection

logging.basicConfig(level=logging.WARNING, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("PulseCore")

ROADMAP_PATH = "config/roadmap.yaml"
REPO_PATH = os.getenv("REPO_PATH", ".")


class StateEngine:
    @staticmethod
    def load_roadmap() -> dict:
        if not os.path.exists(ROADMAP_PATH):
            return {}
        with open(ROADMAP_PATH, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    @staticmethod
    def save_roadmap(data: dict):
        os.makedirs(os.path.dirname(ROADMAP_PATH), exist_ok=True)
        with open(ROADMAP_PATH, "w", encoding="utf-8") as f:
            yaml.dump(data, f, allow_unicode=True, sort_keys=False)


class ActivityTrackerDaemon(threading.Thread):
    """Фоновий демон, що використовує модулі парсингу та зберігає стан у БД."""
    def __init__(self, repo_path: str):
        super().__init__(daemon=True)
        self.repo_path = repo_path
        
        # Витягуємо профіль з БД, якщо він вже був заданий, інакше дефолт
        target_user = "manikse"
        try:
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM system_config WHERE key = 'target_github_user'")
            row = cursor.fetchone()
            if row:
                target_user = row[0]
            conn.close()
        except Exception:
            pass

        self.git_tracker = GitActivityTracker(target_user=target_user)
        self.notes_tracker = NotesTracker(repo_path)

    def run(self):
        while True:
            time.sleep(10) # Перевірка кожні 10 секунд
            
            new_commits = self.git_tracker.get_new_activity()
            new_notes = self.notes_tracker.get_new_activity()
            
            # Якщо є нові дані, відкриваємо з'єднання з БД
            if new_commits or new_notes:
                conn = get_connection()
                cursor = conn.cursor()
                
                # Парсимо та записуємо Git
                for commit in new_commits:
                    print(f"\n\n[DAEMON] 🔔 Git Code Update (Commit: {commit['hash']}): {commit['subject']}")
                    try:
                        # INSERT OR IGNORE захищає від дублікатів по commit_hash
                        cursor.execute('''
                            INSERT OR IGNORE INTO git_activity (commit_hash, author, date, message)
                            VALUES (?, ?, ?, ?)
                        ''', (commit['hash'], commit.get('author', 'System'), commit.get('date', ''), commit['subject']))
                    except Exception as e:
                        logger.error(f"Помилка запису Git у БД: {e}")
                    
                    print("Pulse> ", end="", flush=True)

                # Парсимо та записуємо Нотатки (Markdown)
                for note in new_notes:
                    print(f"\n\n[DAEMON] 📝 Note {note['action']}: {note['file']}")
                    try:
                        cursor.execute('''
                            INSERT INTO notes_updates (file_path, last_modified, status)
                            VALUES (?, ?, ?)
                        ''', (note['file'], time.time(), note.get('action', 'updated')))
                    except Exception as e:
                        logger.error(f"Помилка запису Notes у БД: {e}")
                        
                    print("Pulse> ", end="", flush=True)
                
                # Зберігаємо транзакцію і закриваємо з'єднання
                conn.commit()
                conn.close()


class PulseConsole(cmd.Cmd):
    intro = (
        "\n======================================================\n"
        " EXARCHON-PULSE ENGINE (Low-Level Control Interface)\n"
        "======================================================\n"
        " Daemon is monitoring Git & Local Files.\n"
        " Type 'help' or '?' to list commands.\n"
    )
    prompt = "Pulse> "

    def do_status(self, arg):
        """Показати поточний статус розробки з роадмапу."""
        data = StateEngine.load_roadmap()
        phase = data.get("current_phase", "Unknown")
        print(f"\n[STATUS] Поточний етап: {phase}")
        print("[STATUS] Activity Trackers (Git, FS, DB): ONLINE")

    def do_decisions(self, arg):
        """Показати чергу стратегічних рішень."""
        data = StateEngine.load_roadmap()
        decisions = [d for d in data.get("decision_queue", []) if d.get("status") == "pending"]
        
        if not decisions:
            print("\n[DECISIONS] Черга чиста.")
            return

        print("\n[DECISIONS] Очікують вашого вирішення:")
        for dec in decisions:
            print(f" ID: {dec['id']} | {dec['question']}")
            for key, val in dec['options'].items():
                print(f"   {key}: {val}")

    def do_diagnostics(self, arg):
        """Показати діагностику: ціль спостереження, записи в БД та статус."""
        try:
            conn = get_connection()
            cursor = conn.cursor()
            
            # Перевіряємо цільовий профіль
            cursor.execute("SELECT value FROM system_config WHERE key = 'target_github_user'")
            row = cursor.fetchone()
            target = row[0] if row else "manikse (default)"
            
            # Рахуємо записи в таблицях
            cursor.execute("SELECT COUNT(*) FROM git_activity")
            commits_count = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM notes_updates")
            notes_count = cursor.fetchone()[0]
            
            conn.close()
            
            print(f"\n[DIAGNOSTICS] -------------------")
            print(f" Цільовий GitHub профіль : {target}")
            print(f" Збережено комітів у БД   : {commits_count}")
            print(f" Збережено нотаток у БД  : {notes_count}")
            print(f" Статус потоку демона    : ACTIVE (робочий цикл: 10с)")
            print(f"-----------------------------------")
        except Exception as e:
            print(f"\n[ERROR] Помилка діагностики бази даних: {e}")


    def do_decide(self, arg):
        """Прийняти рішення: decide <ID> <A/B>"""
        args = arg.split()
        if len(args) != 2:
            print("[ERROR] Використовуйте: decide <ID> <Вибір>")
            return
        
        dec_id, choice = args[0], args[1].upper()
        data = StateEngine.load_roadmap()
        
        found = False
        for dec in data.get("decision_queue", []):
            if dec["id"] == dec_id and dec["status"] == "pending":
                dec["status"] = "resolved"
                dec["selected_option"] = choice
                found = True
                print(f"\n[ACTION] Рішення {dec_id} прийнято ({choice}). Стан зафіксовано.")
                break
        
        if found:
            StateEngine.save_roadmap(data)

    def do_idea(self, arg):
        """Записати нову ідею або план: idea <твій текст>"""
        if not arg:
            print("[ERROR] Ти нічого не написав. Приклад: idea додати інтеграцію з OpenAI")
            return
        
        print(f"\n[BRAIN] Ідею зафіксовано: {arg}")
        print("[BRAIN] Очікую на підключення інтелектуального модуля для аналізу.")

    def do_set_target(self, arg):
        """Встановити GitHub профіль для парсингу: set_target <username>"""
        if not arg:
            print("[ERROR] Вкажіть ім'я користувача. Приклад: set_target manikse")
            return
        
        try:
            conn = get_connection()
            cursor = conn.cursor()
            # Використовуємо REPLACE, якщо таблиця створена правильно (з UNIQUE key)
            cursor.execute("INSERT OR REPLACE INTO system_config (key, value) VALUES ('target_github_user', ?)", (arg,))
            conn.commit()
            conn.close()
            print(f"\n[CONFIG] Цільовий профіль змінено на: {arg}")
            print("[SYSTEM] Зміни набудуть чинності після перезапуску ядра.")
        except Exception as e:
            print(f"\n[ERROR] Не вдалося зберегти профіль: {e}")

    def do_exit(self, arg):
        """Вийти."""
        print("\n[SYSTEM] Завершення роботи...")
        return True


def main():
    # Ініціалізація бази даних перед стартом
    init_db()
    
    tracker = ActivityTrackerDaemon(REPO_PATH)
    tracker.start()
    
    try:
        PulseConsole().cmdloop()
    except KeyboardInterrupt:
        print("\n[SYSTEM] Зупинка.")

if __name__ == "__main__":
    main()