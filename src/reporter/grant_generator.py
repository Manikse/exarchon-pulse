import os
import re
import logging
from datetime import datetime
from src.core.database import get_connection

logger = logging.getLogger("PulseCore.Reporter")


class ReportGenerator:
    """Генератор Markdown-звітів на основі даних з локальної бази SQLite."""

    def __init__(self, output_dir="reports"):
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)

    def _calculate_effort_distribution(self, pushes: list) -> dict:
        """Вираховує відсоткове співвідношення типів робіт на основі Conventional Commits."""
        categories = {
            "feature": [r"feat", r"feature", r"add"],
            "bug": [r"fix", r"bug", r"patch"],
            "documentation": [r"docs", r"doc"],
            "refactor": [r"refactor", r"style", r"perf"],
            "maintenance": [r"chore", r"test", r"ci"],
        }

        tally = {cat: 0 for cat in categories}
        tally["other"] = 0
        total = 0

        for push in pushes:
            # Шукаємо ключові слова у summary (регістронезалежно)
            summary = push["summary"].lower()
            matched = False
            for cat, patterns in categories.items():
                # Шукаємо або слово як окреме, або у форматі feat(scope):
                if any(
                    re.search(rf"\b{pat}\b", summary) or re.search(rf"{pat}\(", summary)
                    for pat in patterns
                ):
                    tally[cat] += 1
                    matched = True
                    break

            if not matched:
                tally["other"] += 1
            total += 1

        percentages = {}
        if total > 0:
            # Сортуємо словник за кількістю (від найбільшого до найменшого)
            sorted_tally = sorted(tally.items(), key=lambda item: item[1], reverse=True)
            for cat, count in sorted_tally:
                if count > 0:
                    percentages[cat] = (count / total) * 100

        return percentages

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

            # 3. Останні ключові досягнення
            cursor.execute("""
                SELECT repo_name, summary, created_at 
                FROM github_events 
                WHERE event_type = 'PushEvent' 
                ORDER BY created_at DESC LIMIT 50
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

        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        date_str = datetime.now().strftime("%Y-%m-%d")

        md_lines = []
        md_lines.append("# EXARCHON-PULSE: Executive Summary")
        md_lines.append(f"**Date Generated:** {date_str}\n")

        md_lines.append("## 📊 High-Level Metrics")
        md_lines.append(f"- **Total GitHub Events Tracked:** {total_events}")
        md_lines.append(f"- **Total Commits Pushed:** {total_commits}")
        md_lines.append(f"- **Active Repositories:** {len(repos)}\n")

        if repos:
            md_lines.append("### 📁 Repositories Touched")
            for r in repos:
                md_lines.append(f"- `{r}`")
            md_lines.append("\n")

        effort_dist = self._calculate_effort_distribution(recent_pushes)
        md_lines.append("## 🏷 Effort Distribution (Labels)")
        if effort_dist:
            for cat, pct in effort_dist.items():
                md_lines.append(f"- **{cat.capitalize()}**: {pct:.1f}%")
        else:
            md_lines.append("- Not enough data for categorization.")
        md_lines.append("\n")

        md_lines.append("## 🛠 Code & Architecture Updates")
        if recent_pushes:
            # Обмежуємо вивід до 15 останніх для зручності читання
            for push in recent_pushes[:15]:
                # Перетворюємо "2026-07-31T10:24:11Z" на "2026-07-31 10:24"
                formatted_time = push["created_at"].replace("T", " ")[:16]
                md_lines.append(
                    f"- **[{formatted_time}] {push['repo_name']}**: {push['summary']}"
                )
        else:
            md_lines.append("- No code updates recorded in this period.")
        md_lines.append("\n")

        md_lines.append("## 📝 Local Knowledge Base (Notes)")
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
