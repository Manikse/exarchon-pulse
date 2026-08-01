import sqlite3
import os
import logging

logger = logging.getLogger("PulseCore.Database")

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "data", "pulse_state.db")


def get_connection():
    """Повертає об'єкт з'єднання з БД з підтримкою доступу за іменами колонок."""
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Ініціалізує таблиці бази даних."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

    conn = get_connection()
    try:
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS github_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT UNIQUE NOT NULL,       
                event_type TEXT NOT NULL,            
                repo_name TEXT NOT NULL,             
                commits_count INTEGER DEFAULT 0,     
                raw_payload TEXT,                    
                summary TEXT,                        
                created_at TEXT NOT NULL,
                analyzed_by_ai BOOLEAN DEFAULT 0     
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS notes_updates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_path TEXT NOT NULL,
                last_modified REAL NOT NULL,
                status TEXT DEFAULT 'updated',
                processed BOOLEAN DEFAULT 0
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS decision_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_type TEXT NOT NULL, 
                source_id INTEGER NOT NULL,
                action_required TEXT,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS system_config (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tracked_repos (
                repo_name TEXT PRIMARY KEY,
                last_sha TEXT,
                last_checked_at TEXT
            )
        """)

        cursor.execute(
            "INSERT OR IGNORE INTO system_config (key, value) VALUES ('target_github_user', 'manikse')"
        )

        conn.commit()
        print(f"[SYSTEM] База даних готова: {os.path.abspath(DB_PATH)}")
    except Exception as e:
        logger.error(f"Помилка ініціалізації БД: {e}")
        conn.rollback()
    finally:
        conn.close()
