import requests
import time
import logging

logger = logging.getLogger("PulseCore")

class GitActivityTracker:
    def __init__(self, target_user: str = "Manikse"):
        self.target_user = target_user
        self.api_url = f"https://api.github.com/users/{self.target_user}/events/public"
        self.seen_events = set()
        
        # Щоб не парсити стару історію при кожному запуску,
        # спочатку робимо "холостий" запит і запам'ятовуємо поточні події.
        self._init_seen_events()

    def _init_seen_events(self):
        try:
            response = requests.get(self.api_url)
            if response.status_code == 200:
                events = response.json()
                for event in events:
                    self.seen_events.add(event['id'])
        except Exception as e:
            logger.error(f"Помилка ініціалізації GitHub API: {e}")

    def get_new_activity(self):
        """Збирає нові події PushEvent (коміти) з профілю."""
        new_commits = []
        try:
            # Використовуємо таймаут, щоб не блокувати потік
            response = requests.get(self.api_url, timeout=5)
            
            if response.status_code == 200:
                events = response.json()
                
                for event in events:
                    event_id = event['id']
                    
                    # Пропускаємо те, що вже бачили
                    if event_id in self.seen_events:
                        continue
                    
                    self.seen_events.add(event_id)
                    
                    # Нас цікавлять тільки пуші коду (PushEvent)
                    if event['type'] == 'PushEvent':
                        repo_name = event['repo']['name']
                        commits = event['payload'].get('commits', [])
                        
                        for commit in commits:
                            new_commits.append({
                                "hash": commit['sha'][:7],
                                "author": commit['author']['name'],
                                "subject": f"[{repo_name}] {commit['message']}",
                                "date": event['created_at']
                            })
            else:
                logger.warning(f"GitHub API повернув статус {response.status_code}")
                
        except Exception as e:
            logger.error(f"Помилка з'єднання з GitHub: {e}")

        return new_commits