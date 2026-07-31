import os
import time
import threading
import logging
import cmd
import yaml
from datetime import datetime
from typing import List, Dict

from dotenv import load_dotenv
load_dotenv()

from colorama import init, Fore, Style
init(autoreset=True)

class C:
    CYAN = Fore.CYAN
    GREEN = Fore.GREEN
    YELLOW = Fore.YELLOW
    RED = Fore.RED
    MAGENTA = Fore.MAGENTA
    DIM = Style.DIM
    RESET = Style.RESET_ALL

# Підключаємо модулі парсингу
from src.tracker.git_watcher import GitActivityTracker
from src.tracker.notes_watcher import NotesTracker

# Підключаємо базу даних
from src.core.database import init_db, get_connection

logging.basicConfig(level=logging.WARNING, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("Pulse")

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
    """Фоновий демон Пульсу, що збирає дані безпосередньо з Github та файлової системи."""
    def __init__(self, repo_path: str):
        super().__init__(daemon=True)
        self.repo_path = repo_path
        
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
        time.sleep(1)
        start_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"\n{C.DIM}[{start_time}]{C.RESET} {C.GREEN}[DAEMON]{C.RESET} Пульс запущено. Очікування нових подій...")
        print("Pulse> ", end="", flush=True)

        ticks = 0
        while True:
            time.sleep(10)
            ticks += 1
            
            new_events = self.git_tracker.get_new_activity()
            new_notes = self.notes_tracker.get_new_activity()
            
            if new_events or new_notes:
                conn = get_connection()
                cursor = conn.cursor()
                
                for event in new_events:
                    curr_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    print(f"\n\n{C.DIM}[{curr_time}]{C.RESET} {C.CYAN}[GIT]{C.RESET} {event['event_type']} in {C.YELLOW}{event['repo_name']}{C.RESET}: {event['summary']}")
                    try:
                        cursor.execute('''
                            INSERT OR IGNORE INTO github_events 
                            (event_id, event_type, repo_name, commits_count, raw_payload, summary, created_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?)
                        ''', (
                            event['event_id'], event['event_type'], event['repo_name'], 
                            event['commits_count'], event['raw_payload'], event['summary'], event['date']
                        ))
                    except Exception as e:
                        logger.error(f"DB Insert Error (Git): {e}")
                    
                    print("Pulse> ", end="", flush=True)

                for note in new_notes:
                    curr_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    action = note.get('action', 'updated')
                    print(f"\n\n{C.DIM}[{curr_time}]{C.RESET} {C.MAGENTA}[NOTES]{C.RESET} {action}: {note['file']}")
                    try:
                        cursor.execute('''
                            INSERT INTO notes_updates (file_path, last_modified, status)
                            VALUES (?, ?, ?)
                        ''', (note['file'], time.time(), action))
                    except Exception as e:
                        logger.error(f"DB Insert Error (Notes): {e}")
                        
                    print("Pulse> ", end="", flush=True)
                
                conn.commit()
                conn.close()
            else:
                if ticks % 6 == 0:
                    curr_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    print(f"\n{C.DIM}[{curr_time}]{C.RESET} {C.GREEN}[DAEMON]{C.RESET} Пульс активний. Спостереження триває...")
                    print("Pulse> ", end="", flush=True)


class PulseConsole(cmd.Cmd):
    intro = (
        f"\n{C.CYAN}======================================================{C.RESET}\n"
        f" {C.GREEN}PULSE (Data Tracking Sub-system){C.RESET}\n"
        f"{C.CYAN}======================================================{C.RESET}\n"
        f" Daemon is running in the background.\n"
        f" Type 'help' or '?' to list commands.\n"
    )
    prompt = "Pulse> "

    def do_status(self, arg):
        """Показати поточний статус розробки з роадмапу."""
        data = StateEngine.load_roadmap()
        phase = data.get("current_phase", "Unknown")
        print(f"\n{C.YELLOW}[STATUS]{C.RESET} Поточний етап: {phase}")
        print(f"{C.YELLOW}[STATUS]{C.RESET} Modules (Git, FS, DB): {C.GREEN}ONLINE{C.RESET}")

    def do_decisions(self, arg):
        """Показати чергу стратегічних рішень."""
        data = StateEngine.load_roadmap()
        decisions = [d for d in data.get("decision_queue", []) if d.get("status") == "pending"]
        
        if not decisions:
            print(f"\n{C.GREEN}[DECISIONS] Черга чиста.{C.RESET}")
            return

        print(f"\n{C.MAGENTA}[DECISIONS] Очікують вашого вирішення:{C.RESET}")
        for dec in decisions:
            print(f" ID: {dec['id']} | {dec['question']}")
            for key, val in dec['options'].items():
                print(f"   {key}: {val}")

    def do_diagnostics(self, arg):
        """Показати діагностику: ціль спостереження, записи в БД та статус."""
        try:
            conn = get_connection()
            cursor = conn.cursor()
            
            cursor.execute("SELECT value FROM system_config WHERE key = 'target_github_user'")
            row = cursor.fetchone()
            target = row[0] if row else "manikse (default)"
            
            cursor.execute("SELECT COUNT(*) FROM github_events")
            events_count = cursor.fetchone()[0]
            
            cursor.execute("SELECT SUM(commits_count) FROM github_events")
            commits_sum = cursor.fetchone()[0] or 0
            
            cursor.execute("SELECT COUNT(*) FROM notes_updates")
            notes_count = cursor.fetchone()[0]
            
            conn.close()
            
            # Перевіряємо наявність токена в середовищі
            token_status = f"{C.GREEN}LOADED{C.RESET}" if os.getenv("GITHUB_TOKEN") else f"{C.RED}MISSING (Rate Limit Risk){C.RESET}"
            
            print(f"\n{C.CYAN}[DIAGNOSTICS] ---------------------------------{C.RESET}")
            print(f" Target GitHub Profile   : {C.YELLOW}{target}{C.RESET}")
            print(f" GitHub Token Status     : {token_status}")
            print(f" Saved Events (DB)       : {C.GREEN}{events_count}{C.RESET} (Commits: {commits_sum})")
            print(f" Saved Notes (DB)        : {C.GREEN}{notes_count}{C.RESET}")
            print(f" Daemon Cycle            : 10s (Heartbeat: 60s)")
            print(f"{C.CYAN}-----------------------------------------------{C.RESET}")
        except Exception as e:
            print(f"\n{C.RED}[ERROR] Diagnostics DB failure: {e}{C.RESET}")

    def do_decide(self, arg):
        """Прийняти рішення: decide <ID> <A/B>"""
        args = arg.split()
        if len(args) != 2:
            print(f"{C.RED}[ERROR] Формат: decide <ID> <Вибір>{C.RESET}")
            return
        
        dec_id, choice = args[0], args[1].upper()
        data = StateEngine.load_roadmap()
        
        found = False
        for dec in data.get("decision_queue", []):
            if dec["id"] == dec_id and dec["status"] == "pending":
                dec["status"] = "resolved"
                dec["selected_option"] = choice
                found = True
                print(f"\n{C.GREEN}[ACTION] Рішення {dec_id} зафіксовано: {choice}.{C.RESET}")
                break
        
        if found:
            StateEngine.save_roadmap(data)

    def do_idea(self, arg):
        """Записати нову ідею або план: idea <твій текст>"""
        if not arg:
            print(f"{C.RED}[ERROR] Порожній ввід. Приклад: idea додати парсинг гілок{C.RESET}")
            return
        
        print(f"\n{C.GREEN}[IDEA] Зафіксовано:{C.RESET} {arg}")
        print(f"{C.DIM}[IDEA] Збережено в локальний кеш.{C.RESET}")

    def do_set_target(self, arg):
        """Встановити GitHub профіль для парсингу: set_target <username>"""
        if not arg:
            print(f"{C.RED}[ERROR] Вкажіть ім'я. Приклад: set_target manikse{C.RESET}")
            return
        
        try:
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("INSERT OR REPLACE INTO system_config (key, value) VALUES ('target_github_user', ?)", (arg,))
            conn.commit()
            conn.close()
            print(f"\n{C.GREEN}[CONFIG] Цільовий профіль:{C.RESET} {arg}")
            print(f"{C.DIM}[SYSTEM] Зміни застосуються після перезапуску.{C.RESET}")
        except Exception as e:
            print(f"\n{C.RED}[ERROR] Помилка запису профілю: {e}{C.RESET}")

    def do_exit(self, arg):
        """Вийти."""
        print(f"\n{C.YELLOW}[SYSTEM] Завершення роботи...{C.RESET}")
        return True


def main():
    init_db()
    tracker = ActivityTrackerDaemon(REPO_PATH)
    tracker.start()
    
    try:
        PulseConsole().cmdloop()
    except KeyboardInterrupt:
        print(f"\n{C.YELLOW}[SYSTEM] Зупинка.{C.RESET}")

if __name__ == "__main__":
    main()