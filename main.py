import os
import time
import threading
import logging
import cmd
import yaml
from datetime import datetime

from dotenv import load_dotenv

load_dotenv()

from src.reporter.grant_generator import ReportGenerator
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


from src.tracker.git_watcher import GitActivityTracker
from src.tracker.notes_watcher import NotesTracker
from src.core.database import init_db, get_connection

logging.basicConfig(
    level=logging.WARNING, format="%(asctime)s [%(levelname)s] %(message)s"
)
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
    def __init__(self, repo_path: str):
        super().__init__(daemon=True)
        self.repo_path = repo_path

        target_user = "manikse"
        conn = get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT value FROM system_config WHERE key = 'target_github_user'"
            )
            row = cursor.fetchone()
            if row:
                target_user = row["value"]
        except Exception:
            pass
        finally:
            conn.close()

        self.git_tracker = GitActivityTracker(target_user=target_user)
        self.notes_tracker = NotesTracker(repo_path)

    def run(self):
        time.sleep(1)
        start_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(
            f"\n{C.DIM}[{start_time}]{C.RESET} {C.GREEN}[DAEMON]{C.RESET} Пульс запущено. Очікування нових подій..."
        )
        print("Pulse> ", end="", flush=True)

        ticks = 0
        while True:
            time.sleep(10)
            ticks += 1

            new_events = self.git_tracker.get_new_activity()
            new_notes = self.notes_tracker.get_new_activity()

            if new_events or new_notes:
                conn = get_connection()
                try:
                    cursor = conn.cursor()

                    for event in new_events:
                        curr_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        print(
                            f"\n\n{C.DIM}[{curr_time}]{C.RESET} {C.CYAN}[GIT]{C.RESET} {event['event_type']} in {C.YELLOW}{event['repo_name']}{C.RESET}: {event['summary']}"
                        )

                        cursor.execute(
                            """
                            INSERT OR IGNORE INTO github_events 
                            (event_id, event_type, repo_name, commits_count, raw_payload, summary, created_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                            (
                                event["event_id"],
                                event["event_type"],
                                event["repo_name"],
                                event["commits_count"],
                                event["raw_payload"],
                                event["summary"],
                                event["date"],
                            ),
                        )
                        print("Pulse> ", end="", flush=True)

                    for note in new_notes:
                        curr_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        action = note.get("action", "updated")
                        print(
                            f"\n\n{C.DIM}[{curr_time}]{C.RESET} {C.MAGENTA}[NOTES]{C.RESET} {action}: {note['file']}"
                        )

                        cursor.execute(
                            """
                            INSERT INTO notes_updates (file_path, last_modified, status)
                            VALUES (?, ?, ?)
                        """,
                            (note["file"], time.time(), action),
                        )
                        print("Pulse> ", end="", flush=True)

                    conn.commit()
                except Exception as e:
                    logger.error(f"Помилка запису в БД: {e}")
                    conn.rollback()
                finally:
                    conn.close()
            else:
                if ticks % 6 == 0:
                    curr_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    print(
                        f"\n{C.DIM}[{curr_time}]{C.RESET} {C.GREEN}[DAEMON]{C.RESET} Пульс активний. Спостереження триває..."
                    )
                    print("Pulse> ", end="", flush=True)


class PulseConsole(cmd.Cmd):
    intro = (
        f"\n{C.CYAN}======================================================{C.RESET}\n"
        f" {C.GREEN}EXARCHON-PULSE ENGINE (Low-Level Control Interface){C.RESET}\n"
        f"{C.CYAN}======================================================{C.RESET}\n"
        f" Daemon is monitoring Git & Local Files.\n"
        f" Type 'help' or '?' to list commands.\n"
    )
    prompt = "Pulse> "

    def emptyline(self):
        """Перевизначає поведінку cmd, щоб порожній Enter не повторював команду."""
        pass

    def do_report(self, arg):
        """Згенерувати аналітичний звіт на базі збережених даних. Використання: report"""
        print(f"\n{C.YELLOW}[REPORT]{C.RESET} Обробка даних...")
        conn = get_connection()
        try:
            cursor = conn.cursor()

            cursor.execute(
                "SELECT COUNT(*) as events, SUM(commits_count) as total_commits FROM github_events"
            )
            stats = cursor.fetchone()

            events_count = stats["events"] or 0
            commits_sum = stats["total_commits"] or 0

            cursor.execute(
                "SELECT repo_name, summary, created_at FROM github_events ORDER BY created_at DESC LIMIT 5"
            )
            recent_events = cursor.fetchall()

            print(f"\n{C.CYAN}=== EXARCHON-PULSE EXECUTIVE SUMMARY ==={C.RESET}")
            print(f"Зафіксовано подій в БД: {C.GREEN}{events_count}{C.RESET}")
            print(f"Сумарна кількість комітів: {C.GREEN}{commits_sum}{C.RESET}")

            print(f"\n{C.CYAN}Останні активності:{C.RESET}")
            if recent_events:
                for ev in recent_events:
                    print(
                        f" {C.DIM}[{ev['created_at']}]{C.RESET} {C.YELLOW}{ev['repo_name']}{C.RESET}: {ev['summary']}"
                    )
            else:
                print(f" {C.DIM}- Немає даних для відображення.{C.RESET}")
            print(f"{C.CYAN}========================================{C.RESET}\n")
        except Exception as e:
            print(f"\n{C.RED}[ERROR] Помилка генерації звіту: {e}{C.RESET}")
        finally:
            conn.close()

    def do_export(self, arg):
        """Експортувати повний Markdown-звіт. Використання: export"""
        print(f"\n{C.YELLOW}[REPORT]{C.RESET} Генерація розширеного Markdown-звіту...")
        generator = ReportGenerator()
        filepath = generator.generate_markdown_report()

        if filepath:
            print(
                f"{C.GREEN}[SUCCESS]{C.RESET} Звіт успішно згенеровано та збережено: {C.CYAN}{filepath}{C.RESET}"
            )
        else:
            print(
                f"{C.RED}[ERROR] Не вдалося згенерувати звіт. Перевірте логи.{C.RESET}"
            )

    def do_status(self, arg):
        data = StateEngine.load_roadmap()
        phase = data.get("current_phase", "Unknown")
        print(f"\n{C.YELLOW}[STATUS]{C.RESET} Поточний етап: {phase}")
        print(
            f"{C.YELLOW}[STATUS]{C.RESET} Modules (Git, FS, DB): {C.GREEN}ONLINE{C.RESET}"
        )

    def do_decisions(self, arg):
        data = StateEngine.load_roadmap()
        decisions = [
            d for d in data.get("decision_queue", []) if d.get("status") == "pending"
        ]

        if not decisions:
            print(f"\n{C.GREEN}[DECISIONS] Черга чиста.{C.RESET}")
            return

        print(f"\n{C.MAGENTA}[DECISIONS] Очікують вашого вирішення:{C.RESET}")
        for dec in decisions:
            print(f" ID: {dec['id']} | {dec['question']}")
            for key, val in dec["options"].items():
                print(f"   {key}: {val}")

    def do_diagnostics(self, arg):
        try:
            conn = get_connection()
            cursor = conn.cursor()

            cursor.execute(
                "SELECT value FROM system_config WHERE key = 'target_github_user'"
            )
            row = cursor.fetchone()
            target = row["value"] if row else "manikse (default)"

            cursor.execute("SELECT COUNT(*) as cnt FROM github_events")
            events_count = cursor.fetchone()["cnt"]

            cursor.execute("SELECT SUM(commits_count) as sm FROM github_events")
            commits_sum = cursor.fetchone()["sm"] or 0

            cursor.execute("SELECT COUNT(*) as cnt FROM notes_updates")
            notes_count = cursor.fetchone()["cnt"]

            conn.close()

            token_status = (
                f"{C.GREEN}LOADED{C.RESET}"
                if os.getenv("GITHUB_TOKEN")
                else f"{C.RED}MISSING (Rate Limit Risk){C.RESET}"
            )

            print(f"\n{C.CYAN}[DIAGNOSTICS] ---------------------------------{C.RESET}")
            print(f" Target GitHub Profile   : {C.YELLOW}{target}{C.RESET}")
            print(f" GitHub Token Status     : {token_status}")
            print(
                f" Saved Events (DB)       : {C.GREEN}{events_count}{C.RESET} (Commits: {commits_sum})"
            )
            print(f" Saved Notes (DB)        : {C.GREEN}{notes_count}{C.RESET}")
            print(f" Daemon Cycle            : 10s (Heartbeat: 60s)")
            print(f"{C.CYAN}-----------------------------------------------{C.RESET}")
        except Exception as e:
            print(f"\n{C.RED}[ERROR] Diagnostics DB failure: {e}{C.RESET}")

    def do_decide(self, arg):
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
                print(
                    f"\n{C.GREEN}[ACTION] Рішення {dec_id} зафіксовано: {choice}.{C.RESET}"
                )
                break

        if found:
            StateEngine.save_roadmap(data)

    def do_idea(self, arg):
        if not arg:
            print(
                f"{C.RED}[ERROR] Порожній ввід. Приклад: idea додати парсинг гілок{C.RESET}"
            )
            return
        print(f"\n{C.GREEN}[IDEA] Зафіксовано:{C.RESET} {arg}")
        print(f"{C.DIM}[IDEA] Збережено в локальний кеш.{C.RESET}")

    def do_set_target(self, arg):
        if not arg:
            print(f"{C.RED}[ERROR] Вкажіть ім'я. Приклад: set_target manikse{C.RESET}")
            return

        try:
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "INSERT OR REPLACE INTO system_config (key, value) VALUES ('target_github_user', ?)",
                (arg,),
            )
            conn.commit()
            conn.close()
            print(f"\n{C.GREEN}[CONFIG] Цільовий профіль:{C.RESET} {arg}")
            print(f"{C.DIM}[SYSTEM] Зміни застосуються після перезапуску.{C.RESET}")
        except Exception as e:
            print(f"\n{C.RED}[ERROR] Помилка запису профілю: {e}{C.RESET}")

    def do_exit(self, arg):
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
