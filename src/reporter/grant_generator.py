import os
import logging
from datetime import datetime
from src.core.database import get_connection

logger = logging.getLogger("PulseCore.Reporter")


class ReportGenerator:
    """Генератор Markdown-звітів на основі даних з локальної бази SQLite."""

    def __init__(self, output_dir="reports"):
        self.output_dir = output_dir
        # Гарантуємо наявність директорії для звітів
        os.makedirs(self.output_dir, exist_ok=True)

    def generate_markdown_report(self) -> str:
        """Формує звіт, звертаючись до БД, та зберігає його у файл. Повертає шлях до файлу."""
        conn = get_connection()
        try:
            cursor = conn.cursor()

            # 1. Агрегована статистика
            cursor.execute(
                "SELECT COUNT(*) as events, SUM(commits_count) as total_commits FROM github_events"
            )
            stats = cursor.fetchone()
            total_events = stats["events"] or 0
            total_commits = stats["total_commits"] or 0

            # 2. Унікальні репозиторії
            cursor.execute("SELECT DISTINCT repo_name FROM github_events")
            repos = [row["repo_name"] for row in cursor.fetchall()]

            # 3. Останні ключові досягнення (тільки Push події, бо це реальний код)
            cursor.execute("""
                SELECT repo_name, summary, created_at 
                FROM github_events 
                WHERE event_type = 'PushEvent' 
                ORDER BY created_at DESC LIMIT 15
            """)
            recent_pushes = cursor.fetchall()

            # 4. Активність у локальних нотатках
            cursor.execute(
                "SELECT file_path, status, last_modified FROM notes_updates ORDER BY last_modified DESC LIMIT 10"
            )
            recent_notes = cursor.fetchall()

        except Exception as e:
            logger.error(f"Помилка отримання даних для звіту: {e}")
            return ""
        finally:
            conn.close()

        # Формування Markdown-документа
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        date_str = datetime.now().strftime("%Y-%m-%d")

        md_lines = []
        md_lines.append("# EXARCHON-PULSE: Executive Summary")
        md_lines.append(f"**Date Generated:** {date_str}\n")

        md_lines.append("## High-Level Metrics")
        md_lines.append(f"- **Total GitHub Events Tracked:** {total_events}")
        md_lines.append(f"- **Total Commits Pushed:** {total_commits}")
        md_lines.append(f"- **Active Repositories:** {len(repos)}\n")

        if repos:
            md_lines.append("### Repositories Touched")
            for r in repos:
                md_lines.append(f"- `{r}`")
            md_lines.append("\n")

        md_lines.append("## Code & Architecture Updates")
        if recent_pushes:
            for push in recent_pushes:
                # Відрізаємо зайвий час, залишаємо лише дату для чистоти звіту
                date_only = push["created_at"].split("T")[0]
                md_lines.append(
                    f"- **[{date_only}] {push['repo_name']}**: {push['summary']}"
                )
        else:
            md_lines.append("- No code updates recorded in this period.")
        md_lines.append("\n")

        md_lines.append("## Local Knowledge Base (Notes)")
        if recent_notes:
            for note in recent_notes:
                md_lines.append(f"- `{note['file_path']}` (Status: {note['status']})")
        else:
            md_lines.append("- No local notes updated.")
        md_lines.append("\n")

        md_lines.append("---\n*Generated autonomously by Exarchon-Pulse Engine.*")

        report_content = "\n".join(md_lines)
        filepath = os.path.join(self.output_dir, f"exarchon_report_{timestamp}.md")

        try:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(report_content)
            return filepath
        except IOError as e:
            logger.error(f"Помилка запису файлу звіту: {e}")
            return ""
