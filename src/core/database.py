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
    # Таблиця для глибокого аналізу GitHub-активності (Ready for LLM)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS github_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id TEXT UNIQUE NOT NULL,       -- Унікальний ID події з GitHub
            event_type TEXT NOT NULL,            -- PushEvent, IssuesEvent, PullRequestEvent
            repo_name TEXT NOT NULL,             -- Де саме відбулася дія
            commits_count INTEGER DEFAULT 0,     -- Кількість комітів (якщо це Push)
            raw_payload TEXT,                    -- Зберігаємо ВЕСЬ JSON для майбутнього ШІ
            summary TEXT,                        -- Згенероване базове резюме для поточного CLI
            created_at TEXT NOT NULL,
            analyzed_by_ai BOOLEAN DEFAULT 0     -- Флаг для майбутнього ядра Exarchon
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

    # Таблиця для системних налаштувань (цільовий профіль GitHub, тощо)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS system_config (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    ''')

    # Встановлюємо дефолтне значення, щоб система знала за ким стежити
    cursor.execute("INSERT OR IGNORE INTO system_config (key, value) VALUES ('target_github_user', 'manikse')")

    conn.commit()
    conn.close()
    print(f"[SYSTEM] База даних перевірена/ініціалізована: {os.path.abspath(DB_PATH)}")

def get_connection():
    """Повертає об'єкт з'єднання з БД для інших модулів."""
    return sqlite3.connect(DB_PATH)