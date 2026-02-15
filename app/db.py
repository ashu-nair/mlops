import sqlite3
from pathlib import Path

DB_PATH = Path("mlops.db")


def get_conn():
    return sqlite3.connect(DB_PATH)


def init_db():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS models (
        model_id TEXT PRIMARY KEY,
        created_at TEXT,
        active_version INTEGER DEFAULT 1
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS versions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        model_id TEXT,
        version INTEGER,
        status TEXT,
        folder_path TEXT,
        image_tag TEXT,
        container_id TEXT,
        internal_port INTEGER,
        created_at TEXT,
        error_log TEXT,
        FOREIGN KEY(model_id) REFERENCES models(model_id)
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS metrics (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        model_id TEXT,
        version INTEGER,
        request_time TEXT,
        latency_ms REAL
    )
    """)


    conn.commit()
    conn.close()
