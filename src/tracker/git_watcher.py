import os
import requests
import json
import logging
import time
from src.core.database import get_connection

logger = logging.getLogger("PulseCore.GitWatcher")


class GitActivityTracker:
    def __init__(self, target_user="manikse"):
        self.target_user = target_user
        self.api_url = f"https://api.github.com/users/{self.target_user}/events/public"
        self.token = os.getenv("GITHUB_TOKEN")

        self.headers = {
            "User-Agent": "Exarchon-Pulse-Engine",
            "Accept": "application/vnd.github.v3+json",
        }
        if self.token:
            self.headers["Authorization"] = f"Bearer {self.token}"

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

            commits_api = f"https://api.github.com/repos/{repo_name}/commits"
            resp = requests.get(commits_api, headers=self.headers, timeout=5)
            if resp.status_code == 200 and resp.json():
                latest_commit_url = resp.json()[0].get("url")
                return self._fetch_repo_diff(repo_name, latest_commit_url)
        except Exception as e:
            logger.debug(f"Помилка завантаження diff: {e}")

        return "No code diff could be retrieved."

    def _generate_smart_summary(self, repo_name: str, payload: dict) -> tuple:
        """Аналізує зміни і формує коротке осмислене резюме + повний payload з файлами."""
        commits = payload.get("commits", [])
        commits_count = len(commits)

        if commits_count > 0:
            # Нормальний сценарій: коміти є в payload
            commit_msgs = [c.get("message", "").split("\n")[0] for c in commits]
            summary = " | ".join(commit_msgs)

            first_commit_url = commits[0].get("url")
            diff_data = (
                self._fetch_repo_diff(repo_name, first_commit_url)
                if first_commit_url
                else ""
            )
            payload["detailed_diff"] = diff_data

            return summary, commits_count, json.dumps(payload)
        else:
            # Сценарій Web Edit / Sync: комітів немає в payload.
            # Робимо активний запит за останнім фактичним комітом репозиторію.
            try:
                commits_api = f"https://api.github.com/repos/{repo_name}/commits"
                resp = requests.get(commits_api, headers=self.headers, timeout=5)

                if resp.status_code == 200 and resp.json():
                    latest_commit_data = resp.json()[0]
                    # Витягуємо повідомлення з об'єкта commit
                    msg = (
                        latest_commit_data.get("commit", {})
                        .get("message", "")
                        .split("\n")[0]
                    )
                    commit_url = latest_commit_data.get("url")

                    diff_data = (
                        self._fetch_repo_diff(repo_name, commit_url)
                        if commit_url
                        else ""
                    )
                    payload["detailed_diff"] = diff_data

                    summary = (
                        msg
                        if msg
                        else f"Direct update in {repo_name} (branch sync/web edit)"
                    )
                    return summary, 1, json.dumps(payload)
            except Exception as e:
                logger.debug(f"Failed to fetch fallback commit for {repo_name}: {e}")

            # Якщо навіть резервний запит впав
            diff_data = self._fetch_repo_diff(repo_name)
            payload["detailed_diff"] = diff_data
            summary = f"Direct update in {repo_name} (branch sync/web edit)"
            return summary, 1, json.dumps(payload)

    def get_new_activity(self):
        new_events = []
        try:
            response = requests.get(self.api_url, headers=self.headers, timeout=10)

            if response.status_code in (403, 429):
                logger.error("[GIT] API Rate Limit Exceeded. Перевірте GITHUB_TOKEN.")
                return []
            elif response.status_code != 200:
                return []

            events = response.json()

            # Витягуємо останні event_id з БД, щоб перевіряти дублікати
            conn = get_connection()
            try:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT event_id FROM github_events ORDER BY id DESC LIMIT 50"
                )
                saved_events = {row["event_id"] for row in cursor.fetchall()}
            finally:
                conn.close()

            for event in reversed(events):
                event_id = event.get("id")

                # Відсікаємо те, що вже є в базі
                if event_id in saved_events:
                    continue

                event_type = event.get("type")
                repo_name = event.get("repo", {}).get("name", "unknown")
                created_at = event.get("created_at")
                payload = event.get("payload", {})

                summary = ""
                commits_count = 0

                if event_type == "PushEvent":
                    summary, commits_count, raw_payload_str = (
                        self._generate_smart_summary(repo_name, payload)
                    )
                elif event_type in ("CreateEvent", "IssuesEvent", "PullRequestEvent"):
                    action = payload.get("action", "Created")
                    title = payload.get("issue", {}).get(
                        "title", payload.get("pull_request", {}).get("title", "")
                    )
                    summary = f"{action} in {repo_name}: {title}".strip(": ")
                    raw_payload_str = json.dumps(payload)
                else:
                    continue

                new_events.append(
                    {
                        "event_id": event_id,
                        "event_type": event_type,
                        "repo_name": repo_name,
                        "commits_count": commits_count,
                        "summary": summary,
                        "raw_payload": raw_payload_str,
                        "date": created_at,
                    }
                )

            return new_events

        except requests.RequestException as e:
            logger.error(f"[GIT] Network failure: {e}")
            return []
