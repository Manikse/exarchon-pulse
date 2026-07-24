import sqlite3
import os

# Визначаємо шлях до бази даних (папка data у корені проєкту)
DB_PATH = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'pulse_state.db')

def init_db():
    """Ініціалізує таблиці бази даних, якщо вони не існують."""
    # Переконуємося, що папка data існує
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Таблиця для відстеження Git-комітів
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS git_activity (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            commit_hash TEXT UNIQUE NOT NULL,
            author TEXT,
            date TEXT,
            message TEXT,
            processed BOOLEAN DEFAULT 0
        )
    ''')

    # Таблиця для відстеження змін у Markdown-нотатках
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS notes_updates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_path TEXT NOT NULL,
            last_modified REAL NOT NULL,
            status TEXT DEFAULT 'updated',
            processed BOOLEAN DEFAULT 0
        )
    ''')

    # Таблиця для черги рішень (Decision Queue)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS decision_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_type TEXT NOT NULL, -- 'git' або 'note'
            source_id INTEGER NOT NULL,
            action_required TEXT,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    conn.commit()
    conn.close()
    print(f"[SYSTEM] База даних перевірена/ініціалізована: {os.path.abspath(DB_PATH)}")

def get_connection():
    """Повертає об'єкт з'єднання з БД для інших модулів."""
    return sqlite3.connect(DB_PATH)