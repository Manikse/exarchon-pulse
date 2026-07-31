import os
import requests
import json
import logging
import time

logger = logging.getLogger("PulseCore")

class GitActivityTracker:
    def __init__(self, target_user="manikse"):
        self.target_user = target_user
        self.api_url = f"https://api.github.com/users/{self.target_user}/events/public"
        self.token = os.getenv("GITHUB_TOKEN")
        
        self.seen_events = set()
        self.is_first_run = True
        
        self.headers = {
            "User-Agent": "Exarchon-Pulse-Engine",
            "Accept": "application/vnd.github.v3+json"
        }
        if self.token:
            self.headers["Authorization"] = f"token {self.token}"

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
                        status = f.get("status") # added, modified, removed
                        patch = f.get("patch", "No text diff available (binary or large file)")
                        changes.append(f"File: {filename} ({status})\nChanges:\n{patch}")
                    return "\n\n".join(changes)
            
            # Якщо посилання на коміт немає, беремо загальні останні події репо
            commits_api = f"https://api.github.com/repos/{repo_name}/commits"
            resp = requests.get(commits_api, headers=self.headers, timeout=5)
            if resp.status_code == 200:
                commits = resp.json()
                if commits:
                    latest_commit_url = commits[0].get("url")
                    return self._fetch_repo_diff(repo_name, latest_commit_url)
        except Exception as e:
            logger.error(f"Error fetching repo diff: {e}")
        
        return "No code diff could be retrieved."

    def _generate_smart_summary(self, repo_name: str, payload: dict) -> tuple:
        """Аналізує зміни і формує коротке осмислене резюме + повний payload з файлами."""
        commits = payload.get("commits", [])
        commits_count = len(commits)
        
        commit_msgs = [c.get("message", "").split('\n')[0] for c in commits]
        detailed_changes_text = ""

        if commits_count > 0:
            for commit in commits:
                commit_url = commit.get("url")
                if commit_url:
                    diff_data = self._fetch_repo_diff(repo_name, commit_url)
                    commit["detailed_diff"] = diff_data
                    detailed_changes_text += f"\n--- Commit: {commit.get('message', '').split('\n')[0]} ---\n{diff_data}"
                    time.sleep(0.3)
            summary = f"Updated {repo_name}: " + " | ".join(commit_msgs)
        else:
            # Якщо комітів у пейлоаді 0 (наприклад, веб-редагування або сабмодулі)
            diff_data = self._fetch_repo_diff(repo_name)
            payload["detailed_diff"] = diff_data
            summary = f"Direct update/push in {repo_name} (web edit or branch sync)"
            commits_count = 1 # Враховуємо як подію змін

        return summary, commits_count, json.dumps(payload)

    def get_new_activity(self):
        new_events = []
        try:
            response = requests.get(self.api_url, headers=self.headers, timeout=10)
            
            if response.status_code == 403:
                logger.error("[GIT] API Rate Limit Exceeded. Перевірте GITHUB_TOKEN.")
                return []
            elif response.status_code != 200:
                return []

            events = response.json()
            
            for event in reversed(events):
                event_id = event.get("id")
                
                if event_id in self.seen_events:
                    continue
                    
                self.seen_events.add(event_id)
                
                if self.is_first_run:
                    continue

                event_type = event.get("type")
                repo_name = event.get("repo", {}).get("name", "unknown")
                created_at = event.get("created_at")
                payload = event.get("payload", {})
                
                summary = ""
                commits_count = 0

                if event_type == "PushEvent":
                    summary, commits_count, raw_payload_str = self._generate_smart_summary(repo_name, payload)
                elif event_type == "CreateEvent":
                    ref_type = payload.get("ref_type", "repository")
                    summary = f"Created new {ref_type} in {repo_name}"
                    raw_payload_str = json.dumps(payload)
                elif event_type == "IssuesEvent":
                    summary = f"{payload.get('action').capitalize()} issue: {payload.get('issue', {}).get('title', '')}"
                    raw_payload_str = json.dumps(payload)
                elif event_type == "PullRequestEvent":
                    summary = f"{payload.get('action').capitalize()} PR: {payload.get('pull_request', {}).get('title', '')}"
                    raw_payload_str = json.dumps(payload)
                else:
                    continue

                new_events.append({
                    "event_id": event_id,
                    "event_type": event_type,
                    "repo_name": repo_name,
                    "commits_count": commits_count,
                    "summary": summary,
                    "raw_payload": raw_payload_str,
                    "date": created_at
                })
            
            self.is_first_run = False
            return new_events

        except Exception as e:
            logger.error(f"[GIT] Parser failure: {e}")
            return []