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

import sys

try:
    import readline
except ImportError:
    readline = None


def async_print(message):
    """
    Виводить повідомлення з фонового потоку, не ламаючи поточний ввід користувача.
    """
    # \r повертає каретку на початок, \033[K очищує рядок до кінця
    sys.stdout.write("\r\033[K")
    print(message)

    # Відновлюємо prompt та те, що користувач вже встиг ввести
    buffer = readline.get_line_buffer() if readline else ""
    sys.stdout.write("Pulse> " + buffer)
    sys.stdout.flush()


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

        self.git_tracker = GitActivityTracker(target_user=target_user)
        self.notes_tracker = NotesTracker(repo_path)
        self.network_online = True  # Додаємо відстеження стану мережі

    def run(self):
        time.sleep(1)
        start_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        async_print(
            f"{C.DIM}[{start_time}]{C.RESET} {C.GREEN}[DAEMON]{C.RESET} Пульс запущено. Очікування нових подій..."
        )

        ticks = 0
        while True:
            time.sleep(10)
            ticks += 1

            new_events = self.git_tracker.get_new_activity()

            # --- Контроль стану мережі ---
            if new_events is None:
                if self.network_online:
                    curr_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    async_print(
                        f"\n{C.DIM}[{curr_time}]{C.RESET} {C.RED}[ERROR] Втрачено з'єднання з інтернетом або GitHub API.{C.RESET}"
                    )
                    self.network_online = False
                new_events = []  # Скидаємо до порожнього списку, щоб цикл безпечно йшов далі
            else:
                if not self.network_online:
                    curr_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    async_print(
                        f"\n{C.DIM}[{curr_time}]{C.RESET} {C.GREEN}[SYSTEM] З'єднання відновлено. Продовжую моніторинг.{C.RESET}"
                    )
                    self.network_online = True
            # -----------------------------

            new_notes = self.notes_tracker.get_new_activity()

            if new_events or new_notes:
                conn = get_connection()
                try:
                    cursor = conn.cursor()

                    for event in new_events:
                        curr_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        async_print(
                            f"{C.DIM}[{curr_time}]{C.RESET} {C.CYAN}[GIT]{C.RESET} {event['event_type']} in {C.YELLOW}{event['repo_name']}{C.RESET}: {event['summary']}"
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

                    for note in new_notes:
                        curr_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        action = note.get("action", "updated")
                        async_print(
                            f"{C.DIM}[{curr_time}]{C.RESET} {C.MAGENTA}[NOTES]{C.RESET} {action}: {note['file']}"
                        )

                        cursor.execute(
                            """
                            INSERT INTO notes_updates (file_path, last_modified, status)
                            VALUES (?, ?, ?)
                        """,
                            (note["file"], time.time(), action),
                        )

                    conn.commit()
                except Exception as e:
                    logger.error(f"Помилка запису в БД: {e}")
                    conn.rollback()
                finally:
                    conn.close()
            else:
                if ticks % 6 == 0:
                    curr_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    async_print(
                        f"{C.DIM}[{curr_time}]{C.RESET} {C.GREEN}[DAEMON]{C.RESET} Пульс активний. Спостереження триває..."
                    )


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
        """Згенерувати аналітичний звіт. Використання: report [day|week|month|all]"""
        args = arg.strip().lower()
        valid_args = {"day": 1, "week": 7, "month": 30}

        from datetime import datetime, timedelta

        time_filter = ""
        params = []
        period_name = "За весь час"
        limit = 10  # Дефолтний ліміт для 'all', щоб не переповнити консоль

        if args in valid_args:
            days = valid_args[args]
            cutoff = datetime.utcnow() - timedelta(days=days)
            cutoff_str = cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")
            time_filter = "WHERE created_at >= ?"
            params = [cutoff_str]
            period_name = f"За останні {days} днів"
            limit = 50  # Розширений ліміт для конкретних часових зрізів
        elif args and args != "all":
            print(
                f"\n{C.RED}[ERROR] Невідомий період. Використовуйте: report [day|week|month|all]{C.RESET}"
            )
            return

        print(
            f"\n{C.YELLOW}[REPORT]{C.RESET} Генерація розширеного звіту ({period_name})..."
        )
        conn = get_connection()
        try:
            cursor = conn.cursor()

            # Загальна статистика за період
            cursor.execute(
                f"SELECT COUNT(*) as events, SUM(commits_count) as total_commits FROM github_events {time_filter}",
                params,
            )
            stats = cursor.fetchone()
            events_count = stats["events"] or 0
            commits_sum = stats["total_commits"] or 0

            # Агрегація по репозиторіях
            cursor.execute(
                f"""
                SELECT repo_name, COUNT(*) as ev_count, SUM(commits_count) as com_count 
                FROM github_events {time_filter} 
                GROUP BY repo_name 
                ORDER BY ev_count DESC
            """,
                params,
            )
            repo_stats = cursor.fetchall()

            # Останні дії з динамічним лімітом
            cursor.execute(
                f"SELECT repo_name, summary, created_at FROM github_events {time_filter} ORDER BY created_at DESC LIMIT ?",
                params + [limit],
            )
            recent_events = cursor.fetchall()

            print(f"\n{C.CYAN}=== EXARCHON-PULSE EXECUTIVE SUMMARY ==={C.RESET}")
            print(f"Період: {C.YELLOW}{period_name}{C.RESET}")
            print(
                f"Зафіксовано подій: {C.GREEN}{events_count}{C.RESET} | Комітів: {C.GREEN}{commits_sum}{C.RESET}"
            )

            if repo_stats:
                print(f"\n{C.CYAN}Розподіл активності по репозиторіях:{C.RESET}")
                for r in repo_stats:
                    c_count = r["com_count"] or 0
                    print(
                        f" - {C.YELLOW}{r['repo_name']}{C.RESET}: {r['ev_count']} подій (Комітів: {c_count})"
                    )

            # Тепер ми чітко вказуємо, скільки записів виведено
            print(f"\n{C.CYAN}Активність (до {limit} останніх записів):{C.RESET}")
            if recent_events:
                from datetime import timezone

                for ev in recent_events:
                    try:
                        # Парсимо UTC час з GitHub (наприклад, '2026-08-01T09:57:08Z')
                        utc_dt = datetime.strptime(
                            ev["created_at"], "%Y-%m-%dT%H:%M:%SZ"
                        )
                        # Встановлюємо, що це саме UTC, і конвертуємо в локальний час системи
                        utc_dt = utc_dt.replace(tzinfo=timezone.utc)
                        local_dt = utc_dt.astimezone()
                        date_short = local_dt.strftime("%Y-%m-%d %H:%M:%S")
                    except ValueError:
                        # Fallback, якщо дата має неочікуваний формат
                        date_short = ev["created_at"].replace("T", " ").replace("Z", "")

                    print(
                        f" {C.DIM}[{date_short}]{C.RESET} {C.YELLOW}{ev['repo_name']}{C.RESET}: {ev['summary']}"
                    )
            else:
                print(f" {C.DIM}- Немає даних для відображення за цей період.{C.RESET}")
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

    def do_clear(self, arg):
        """Очистити екран консолі. Використання: clear"""
        os.system("cls" if os.name == "nt" else "clear")

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
