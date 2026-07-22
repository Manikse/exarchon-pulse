import os
import time
import subprocess
import asyncio
import logging
from typing import List, Dict
import yaml

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# Налаштування логування
logging.basicConfig(level=logging.INFO, format="%(asctime)s - [%(levelname)s] - %(message)s")
logger = logging.getLogger("Exarchon-Pulse")

# Конфігурація (замініть на власні значення або .env)
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "YOUR_CHAT_ID_HERE")
REPO_PATH = os.getenv("REPO_PATH", ".")
ROADMAP_PATH = "config/roadmap.yaml"


class GitActivityTracker:
    """Моніторинг Git-комітів у робочій директорії."""
    def __init__(self, repo_path: str):
        self.repo_path = repo_path
        self.last_commit_hash = self.get_latest_commit_hash()

    def get_latest_commit_hash(self) -> str:
        try:
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                check=True
            )
            return result.stdout.strip()
        except Exception as e:
            logger.error(f"Помилка отримання Git hash: {e}")
            return ""

    def get_commit_details(self, commit_hash: str) -> Dict[str, str]:
        try:
            result = subprocess.run(
                ["git", "log", "-1", "--pretty=format:%s%n%b", commit_hash],
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                check=True
            )
            message = result.stdout.strip()
            return {"hash": commit_hash[:7], "message": message}
        except Exception as e:
            logger.error(f"Помилка читання деталізації коміту: {e}")
            return {"hash": commit_hash, "message": "Оновлення коду"}

    def check_new_commits(self) -> List[Dict[str, str]]:
        current_hash = self.get_latest_commit_hash()
        if current_hash and current_hash != self.last_commit_hash:
            self.last_commit_hash = current_hash
            return [self.get_commit_details(current_hash)]
        return []


class RoadmapEngine:
    """Управління та парсинг Динамічного Роадмапу."""
    def __init__(self, yaml_path: str):
        self.yaml_path = yaml_path

    def load_roadmap(self) -> dict:
        if not os.path.exists(self.yaml_path):
            return {}
        with open(self.yaml_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    def get_pending_decisions(self) -> List[dict]:
        data = self.load_roadmap()
        return [d for d in data.get("decision_queue", []) if d.get("status") == "pending"]


# --- Telegram Bot Handlers ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "⚡ Exarchon-Pulse Engine онлайн.\n"
        "Команди:\n"
        "/decisions — Стратегічна черга рішень (Decision Queue)\n"
        "/status — Поточний стан роадмапу"
    )

async def decisions_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    engine = RoadmapEngine(ROADMAP_PATH)
    decisions = engine.get_pending_decisions()

    if not decisions:
        await update.message.reply_text("✅ Активних заблокованих рішень немає. Система працює автономно.")
        return

    for dec in decisions:
        keyboard = [
            [
                InlineKeyboardButton(f"Варіант А", callback_data=f"dec_{dec['id']}_A"),
                InlineKeyboardButton(f"Варіант Б", callback_data=f"dec_{dec['id']}_B"),
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        msg_text = (
            f"🧠 **DECISION QUEUE [{dec['id']}]**\n\n"
            f"**Питання:** {dec['question']}\n\n"
            f"**Контекст:** {dec['context']}\n\n"
            f"**A:** {dec['options']['A']}\n"
            f"**B:** {dec['options']['B']}"
        )
        await update.message.reply_text(msg_text, parse_mode="Markdown", reply_markup=reply_markup)

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data
    if data.startswith("pub_approve"):
        await query.edit_message_text(text=f"{query.message.text}\n\n✅ **Опубліковано в публічні канали!**")
    elif data.startswith("pub_reject"):
        await query.edit_message_text(text=f"{query.message.text}\n\n❌ **Відхилено.**")
    elif data.startswith("dec_"):
        _, dec_id, choice = data.split("_")
        await query.edit_message_text(
            text=f"{query.message.text}\n\n🎯 **Прийнято рішення:** Варіант {choice}. Роадмап оновлено."
        )


# --- Background Daemon Worker ---

async def background_tracker(app: Application):
    """Фоновий процес, що моніторить коміти та формує чернетки постів."""
    tracker = GitActivityTracker(REPO_PATH)
    logger.info("Activity Tracker Daemon запущено...")

    while True:
        await asyncio.sleep(10)  # Інтервал перевірки (10 сек для тесту)
        commits = tracker.check_new_commits()

        for commit in commits:
            # Створення чернетки для Build-in-Public
            draft_text = (
                f"🚀 **Exarchon Progress Update**\n\n"
                f"Зафіксовано новий прогрес у ядрі:\n"
                f"• `{commit['hash']}`: {commit['message']}\n\n"
                f"_Опублікувати цей апдейт у соцмережах?_"
            )
            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("👍 Approve & Publish", callback_data=f"pub_approve_{commit['hash']}"),
                    InlineKeyboardButton("👎 Reject", callback_data=f"pub_reject_{commit['hash']}"),
                ]
            ])

            if TELEGRAM_CHAT_ID and TELEGRAM_CHAT_ID != "YOUR_CHAT_ID_HERE":
                await app.bot.send_message(
                    chat_id=TELEGRAM_CHAT_ID,
                    text=draft_text,
                    parse_mode="Markdown",
                    reply_markup=keyboard
                )


# --- Main Application Loop ---

def main():
    if TELEGRAM_BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        logger.error("Будь ласка, вкажіть ваш TELEGRAM_BOT_TOKEN у коді або середовищі!")
        return

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Реєстрація хендлерів
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("decisions", decisions_command))
    app.add_handler(CallbackQueryHandler(button_callback))

    # Запуск фонового демона разом із ботом
    loop = asyncio.get_event_loop()
    loop.create_task(background_tracker(app))

    logger.info("Exarchon-Pulse Engine повністю запущено.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()