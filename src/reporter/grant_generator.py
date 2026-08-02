import os
import re
import json
import logging
from datetime import datetime
from src.core.database import get_connection, get_report_scope
from src.core.period import resolve_period

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

    def _parse_diff_stats(self, push) -> dict:
        """
        Дістає files_changed/additions/deletions з raw_payload одного пушу.
        Захищено від старих записів (ще з часів events-feed), де цих полів
        немає взагалі, або raw_payload порожній/битий — тоді просто 0.
        """
        try:
            payload = json.loads(push["raw_payload"]) if push["raw_payload"] else {}
        except (json.JSONDecodeError, TypeError):
            return {"files_changed": 0, "additions": 0, "deletions": 0}
        return {
            "files_changed": payload.get("files_changed", 0) or 0,
            "additions": payload.get("additions", 0) or 0,
            "deletions": payload.get("deletions", 0) or 0,
        }

    def generate_markdown_report(
        self, period_type: str = "all", date_arg: str = None
    ) -> str:
        """
        Формує звіт, звертаючись до БД, та зберігає його у файл. Повертає шлях до файлу.

        period_type: "day" | "week" | "month" | "all" (як у resolve_period)
        date_arg: конкретна дата/тиждень/місяць для періоду, або None для
                  рухомого періоду ("останні N") чи всього часу.
        """
        start, end, period_label = resolve_period(period_type, date_arg)

        conn = get_connection()
        try:
            cursor = conn.cursor()

            conditions = []
            params = []

            if start is not None:
                conditions.append("created_at >= ? AND created_at < ?")
                params.extend(
                    [
                        start.strftime("%Y-%m-%dT%H:%M:%SZ"),
                        end.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    ]
                )

            scope = get_report_scope()
            if scope:
                placeholders = ",".join("?" for _ in scope)
                conditions.append(f"repo_name IN ({placeholders})")
                params.extend(scope)

            where_clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""
            where_clause_and = ("AND " + " AND ".join(conditions)) if conditions else ""

            # 1. Агрегована статистика
            cursor.execute(
                f"SELECT COUNT(*) as events, SUM(commits_count) as total_commits FROM github_events {where_clause}",
                params,
            )
            stats = cursor.fetchone()
            total_events = stats["events"] or 0
            total_commits = stats["total_commits"] or 0

            # 2. Унікальні репозиторії
            cursor.execute(
                f"SELECT DISTINCT repo_name FROM github_events {where_clause}",
                params,
            )
            repos = [row["repo_name"] for row in cursor.fetchall()]

            # 3. Останні ключові досягнення
            cursor.execute(
                f"""
                SELECT repo_name, summary, created_at, raw_payload 
                FROM github_events 
                WHERE event_type = 'PushEvent' {where_clause_and}
                ORDER BY created_at DESC LIMIT 50
            """,
                params,
            )
            recent_pushes = cursor.fetchall()

            # 4. Активність у локальних нотатках. Своя часова шкала (unix timestamp,
            # не ISO-рядок як у github_events), тому період рахуємо окремо.
            # Фокус по репозиторіях НЕ застосовується — нотатки не прив'язані до repo_name.
            if start is not None:
                cursor.execute(
                    """
                    SELECT file_path, status, last_modified FROM notes_updates
                    WHERE last_modified >= ? AND last_modified < ?
                    ORDER BY last_modified DESC LIMIT 10
                    """,
                    [start.timestamp(), end.timestamp()],
                )
            else:
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
        md_lines.append(f"**Date Generated:** {date_str}")
        md_lines.append(f"**Period:** {period_label}")
        md_lines.append(
            f"**Report Scope:** {', '.join(scope) if scope else 'All tracked repositories'}\n"
        )

        md_lines.append("## 📊 High-Level Metrics")
        md_lines.append(f"- **Total GitHub Events Tracked:** {total_events}")
        md_lines.append(f"- **Total Commits Pushed:** {total_commits}")
        md_lines.append(f"- **Active Repositories:** {len(repos)}")

        agg_files = sum(
            self._parse_diff_stats(p)["files_changed"] for p in recent_pushes
        )
        agg_add = sum(self._parse_diff_stats(p)["additions"] for p in recent_pushes)
        agg_del = sum(self._parse_diff_stats(p)["deletions"] for p in recent_pushes)
        if agg_files or agg_add or agg_del:
            md_lines.append(
                f"- **Lines Changed (last {len(recent_pushes)} pushes shown below):** "
                f"{agg_files} files, +{agg_add}/-{agg_del}"
            )
        md_lines.append("\n")

        if repos:
            md_lines.append("### 📁 Repositories Touched")
            for r in repos:
                md_lines.append(f"- `{r}`")
            md_lines.append("\n")

        effort_dist = self._calculate_effort_distribution(recent_pushes)
        md_lines.append("## Effort Distribution (Labels)")
        if effort_dist:
            for cat, pct in effort_dist.items():
                md_lines.append(f"- **{cat.capitalize()}**: {pct:.1f}%")
        else:
            md_lines.append("- Not enough data for categorization.")
        md_lines.append("\n")

        md_lines.append("## Code & Architecture Updates")
        if recent_pushes:
            # Обмежуємо вивід до 15 останніх для зручності читання
            for push in recent_pushes[:15]:
                # Перетворюємо "2026-07-31T10:24:11Z" на "2026-07-31 10:24"
                formatted_time = push["created_at"].replace("T", " ")[:16]
                diff_stats = self._parse_diff_stats(push)
                stats_suffix = ""
                if (
                    diff_stats["files_changed"]
                    or diff_stats["additions"]
                    or diff_stats["deletions"]
                ):
                    stats_suffix = (
                        f" _(files: {diff_stats['files_changed']}, "
                        f"+{diff_stats['additions']}/-{diff_stats['deletions']})_"
                    )
                md_lines.append(
                    f"- **[{formatted_time}] {push['repo_name']}**: {push['summary']}{stats_suffix}"
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
