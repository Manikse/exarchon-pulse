import os
import requests
import json
import logging
import sqlite3
import time
from datetime import datetime, timezone
from src.core.database import get_connection

logger = logging.getLogger("PulseCore.GitWatcher")

# Як часто оновлюємо список репозиторіїв користувача (автовиявлення).
REPO_DISCOVERY_INTERVAL = 300  # 5 хв
# Як часто перевіряємо коміти (SHA) по кожному вже відомому репозиторію.
COMMIT_CHECK_INTERVAL = 30  # 30 сек
# Скільки останніх комітів запитувати на репозиторій за раз.
COMMITS_PER_CHECK = 20


class GitActivityTracker:
    """
    Відстежує активність користувача на GitHub.

    PushEvent НЕ береться з /events/public — цей feed підтверджено (перевірено
    через github.com/{user}.atom, 2026-08-01) втрачає окремі пуші при швидких
    послідовних комітах в один репозиторій. Замість цього коміти відстежуються
    напряму по SHA через /repos/{repo}/commits для кожного репозиторію,
    автовиявленого через /users/{user}/repos.

    events/public лишається єдиним джерелом для CreateEvent/IssuesEvent/
    PullRequestEvent — там втрат не зафіксовано.
    """

    def __init__(self, target_user="manikse"):
        self.target_user = target_user
        self.token = os.getenv("GITHUB_TOKEN")

        self.headers = {
            "User-Agent": "Exarchon-Pulse-Engine",
            "Accept": "application/vnd.github.v3+json",
        }
        if self.token:
            self.headers["Authorization"] = f"Bearer {self.token}"

        self.events_api_url = f"https://api.github.com/users/{self.target_user}/events/public?per_page=100"
        self.repos_api_url = (
            f"https://api.github.com/users/{self.target_user}/repos"
            f"?per_page=100&sort=pushed&direction=desc"
        )

        # {repo_full_name: last_known_sha or None}
        self.tracked_repos = self._load_tracked_repos()

        # Таймери навмисно в минулому, щоб перша перевірка відбулась одразу
        # на першому тіку демона, а не через повний інтервал очікування.
        self._last_repo_discovery = 0.0
        self._last_commit_check = 0.0

    # ------------------------------------------------------------------
    # Персистентний стан tracked_repos (SQLite, атомарне відкриття/закриття)
    # ------------------------------------------------------------------

    def _load_tracked_repos(self) -> dict:
        """Завантажує з БД раніше відомі репозиторії та їх останній оброблений SHA."""
        tracked = {}
        try:
            conn = get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT repo_name, last_sha FROM tracked_repos")
                for row in cursor.fetchall():
                    tracked[row["repo_name"]] = row["last_sha"]
            finally:
                conn.close()
        except sqlite3.Error as e:
            logger.error(f"[GIT] Не вдалося завантажити tracked_repos з БД: {e}")
        return tracked

    def _save_tracked_repo(self, repo_name: str, sha: str):
        """Атомарно зберігає останній оброблений SHA для репозиторію."""
        try:
            conn = get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO tracked_repos (repo_name, last_sha, last_checked_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(repo_name) DO UPDATE SET
                        last_sha = excluded.last_sha,
                        last_checked_at = excluded.last_checked_at
                    """,
                    (repo_name, sha, datetime.now(timezone.utc).isoformat()),
                )
                conn.commit()
            finally:
                conn.close()
        except sqlite3.Error as e:
            logger.error(f"[GIT] Не вдалося зберегти стан репо {repo_name}: {e}")

    def _get_last_known_event_date(self, repo_name: str):
        """Дата останньої вже залогованої події по цьому репо (зі старих даних events feed)."""
        try:
            conn = get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT MAX(created_at) as latest FROM github_events WHERE repo_name = ?",
                    (repo_name,),
                )
                row = cursor.fetchone()
                return row["latest"] if row and row["latest"] else None
            finally:
                conn.close()
        except sqlite3.Error as e:
            logger.error(
                f"[GIT] Не вдалося прочитати останню подію для {repo_name}: {e}"
            )
            return None

    # ------------------------------------------------------------------
    # Автовиявлення репозиторіїв
    # ------------------------------------------------------------------

    def _discover_repos(self):
        """Оновлює список репозиторіїв користувача через /users/{user}/repos."""
        try:
            resp = requests.get(self.repos_api_url, headers=self.headers, timeout=10)

            if resp.status_code in (403, 429):
                logger.error("[GIT] Rate Limit під час автовиявлення репозиторіїв.")
                return
            if resp.status_code != 200:
                logger.error(
                    f"[GIT] Помилка автовиявлення репозиторіїв: HTTP {resp.status_code}"
                )
                return

            repos = resp.json()
            if not isinstance(repos, list):
                logger.error(f"[GIT] Неочікуваний формат відповіді /repos: {repos}")
                return

            discovered = 0
            for repo in repos:
                if repo.get("fork"):
                    continue  # форки свідомо не відстежуємо
                full_name = repo.get("full_name")
                if full_name and full_name not in self.tracked_repos:
                    self.tracked_repos[full_name] = None  # SHA ще невідомий
                    self._save_tracked_repo(full_name, None)
                    discovered += 1

            if discovered:
                logger.info(
                    f"[GIT] Автовиявлення: додано {discovered} новий(х) репозиторій(їв)."
                )

        except requests.RequestException as e:
            logger.error(f"[GIT] Мережева помилка автовиявлення репозиторіїв: {e}")

    # ------------------------------------------------------------------
    # Перевірка комітів по конкретному репозиторію (SHA-based, надійно)
    # ------------------------------------------------------------------

    def _fetch_repo_diff(self, repo_name: str, commit_url: str = None) -> str:
        """Витягує змінені файли та їхній вміст (diff) для аналізу."""
        try:
            if commit_url:
                resp = requests.get(commit_url, headers=self.headers, timeout=5)
                if resp.status_code == 200:
                    data = resp.json()
                    changes = []
                    for f in data.get("files", []):
                        filename = f.get("filename")
                        status = f.get("status")
                        patch = f.get(
                            "patch", "No text diff available (binary or large file)"
                        )
                        changes.append(
                            f"File: {filename} ({status})\nChanges:\n{patch}"
                        )
                    return "\n\n".join(changes)
        except Exception as e:
            logger.debug(f"Помилка завантаження diff: {e}")

        return "No code diff could be retrieved."

    def _check_repo_commits(self, repo_name: str) -> list:
        """
        Перевіряє новий стан HEAD репозиторію проти останнього відомого SHA.
        Ніколи не кидає виключення й не просуває SHA, якщо перевірка не вдалась
        (щоб репозиторій автоматично повторно перевірився наступного циклу).
        """
        try:
            commits_api = (
                f"https://api.github.com/repos/{repo_name}/commits"
                f"?per_page={COMMITS_PER_CHECK}"
            )
            resp = requests.get(commits_api, headers=self.headers, timeout=10)

            if resp.status_code in (403, 429):
                logger.error(f"[GIT] Rate Limit під час перевірки {repo_name}.")
                return []
            if resp.status_code == 404:
                logger.debug(
                    f"[GIT] {repo_name} недоступний (видалений/приватний/перейменований)."
                )
                return []
            if resp.status_code != 200:
                logger.debug(
                    f"[GIT] {repo_name}: HTTP {resp.status_code}, пропускаю цикл."
                )
                return []

            commits = resp.json()
            if not isinstance(commits, list) or not commits:
                return []
        except requests.RequestException as e:
            logger.debug(f"[GIT] Мережева помилка при перевірці {repo_name}: {e}")
            return []

        last_known_sha = self.tracked_repos.get(repo_name)

        if last_known_sha is None:
            # Перше опрацювання цього репо новим механізмом.
            # Якщо по ньому вже є історія в github_events (зі старого events feed) —
            # добираємо все, що сталось ПІСЛЯ останньої відомої там події.
            # Якщо історії немає (справді новий репо) — стартуємо з HEAD без
            # ретроактивного заповнення (щоб не заспамити старою історією).
            baseline_date = self._get_last_known_event_date(repo_name)
            if baseline_date:
                new_commits = [
                    c
                    for c in commits
                    if c.get("commit", {}).get("author", {}).get("date", "")
                    > baseline_date
                ]
            else:
                new_commits = []
        else:
            new_commits = []
            for c in commits:
                if c["sha"] == last_known_sha:
                    break
                new_commits.append(c)
            else:
                # last_known_sha не знайдено серед останніх COMMITS_PER_CHECK
                # (форс-пуш, сквош або довга перерва) — не вгадуємо пропущену
                # історію, трактуємо як один "sync" по поточному HEAD.
                new_commits = commits[:1]

        # HEAD оновлюємо в будь-якому разі — навіть якщо new_commits порожній,
        # це означає "я вже бачив цей стан репо".
        self.tracked_repos[repo_name] = commits[0]["sha"]
        self._save_tracked_repo(repo_name, commits[0]["sha"])

        if not new_commits:
            return []

        new_events = []
        for c in reversed(new_commits):  # від старого до нового
            sha = c.get("sha", "")
            msg = c.get("commit", {}).get("message", "").split("\n")[0]
            author_date = c.get("commit", {}).get("author", {}).get("date")
            commit_url = c.get("url")

            diff_data = (
                self._fetch_repo_diff(repo_name, commit_url) if commit_url else ""
            )
            payload = {"sha": sha, "detailed_diff": diff_data}

            new_events.append(
                {
                    "event_id": f"commit_{sha}",
                    "event_type": "PushEvent",
                    "repo_name": repo_name,
                    "commits_count": 1,
                    "summary": msg if msg else f"Direct update in {repo_name}",
                    "raw_payload": json.dumps(payload),
                    "date": author_date,
                }
            )

        return new_events

    # ------------------------------------------------------------------
    # Events feed — лише для Issues/PR/Create (PushEvent тут свідомо ігнорується)
    # ------------------------------------------------------------------

    def _check_other_events(self):
        """Повертає None лише на справжню мережеву відмову (сигнал для UI-банера)."""
        new_events = []
        try:
            response = requests.get(
                self.events_api_url, headers=self.headers, timeout=10
            )

            if response.status_code in (403, 429):
                logger.error(
                    "[GIT] API Rate Limit Exceeded (events feed). Перевірте GITHUB_TOKEN."
                )
                return []
            elif response.status_code != 200:
                return []

            events = response.json()
            if not isinstance(events, list):
                logger.error(
                    f"[GIT] Неочікуваний формат відповіді events feed: {events}"
                )
                return []

            try:
                conn = get_connection()
                try:
                    cursor = conn.cursor()
                    cursor.execute(
                        "SELECT event_id FROM github_events ORDER BY id DESC LIMIT 200"
                    )
                    saved_events = {row["event_id"] for row in cursor.fetchall()}
                finally:
                    conn.close()
            except sqlite3.Error as e:
                logger.error(f"[GIT] Помилка читання БД (event_id cache): {e}")
                return []

            for event in reversed(events):
                event_id = event.get("id")
                if event_id in saved_events:
                    continue

                event_type = event.get("type")
                if event_type not in ("CreateEvent", "IssuesEvent", "PullRequestEvent"):
                    continue  # PushEvent і решта — зона commit-поллера

                repo_name = event.get("repo", {}).get("name", "unknown")
                created_at = event.get("created_at")
                payload = event.get("payload", {})

                action = payload.get("action", "Created")
                title = payload.get("issue", {}).get(
                    "title", payload.get("pull_request", {}).get("title", "")
                )
                summary = f"{action} in {repo_name}: {title}".strip(": ")

                new_events.append(
                    {
                        "event_id": event_id,
                        "event_type": event_type,
                        "repo_name": repo_name,
                        "commits_count": 0,
                        "summary": summary,
                        "raw_payload": json.dumps(payload),
                        "date": created_at,
                    }
                )

            return new_events

        except requests.exceptions.ConnectionError:
            return None
        except requests.RequestException as e:
            logger.debug(f"[GIT] API failure (events feed): {e}")
            return None

    # ------------------------------------------------------------------
    # Публічний вхід, викликається демоном раз на тік (10с)
    # ------------------------------------------------------------------

    def get_new_activity(self):
        all_new_events = []
        network_error = False
        now = time.time()

        if now - self._last_repo_discovery >= REPO_DISCOVERY_INTERVAL:
            self._discover_repos()
            self._last_repo_discovery = now

        if now - self._last_commit_check >= COMMIT_CHECK_INTERVAL:
            self._last_commit_check = now
            for repo_name in list(self.tracked_repos.keys()):
                all_new_events.extend(self._check_repo_commits(repo_name))

        other_events = self._check_other_events()
        if other_events is None:
            network_error = True
        else:
            all_new_events.extend(other_events)

        if network_error and not all_new_events:
            return None

        return all_new_events
