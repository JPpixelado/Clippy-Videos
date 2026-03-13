import os
import sqlite3
import json
import uuid

SQLITE_DB = r"D:\sqlite\app.db"

os.makedirs(os.path.dirname(SQLITE_DB), exist_ok=True)

def get_db():
    conn = sqlite3.connect(SQLITE_DB)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()

    c.execute("""
    CREATE TABLE IF NOT EXISTS users (
        username TEXT PRIMARY KEY,
        nome TEXT,
        email TEXT,
        password TEXT
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS channels (
        username TEXT PRIMARY KEY,
        display_name TEXT,
        bio TEXT,
        password TEXT,
        foto_path TEXT
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS videos (
        id TEXT PRIMARY KEY,
        filename TEXT,
        filename_144p TEXT,
        filename_480p TEXT,
        title TEXT,
        description TEXT,
        views INTEGER DEFAULT 0,
        channel TEXT,
        thumb TEXT,
        subtitles TEXT,
        status TEXT DEFAULT 'pendente'
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS lives (
        id TEXT PRIMARY KEY,
        channel TEXT,
        title TEXT,
        status TEXT,
        started_at TEXT
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS collabs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        video_id TEXT,
        video_title TEXT,
        channel TEXT,
        name TEXT,
        role TEXT,
        status TEXT
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS shorts (
        id INTEGER PRIMARY KEY,
        filename TEXT,
        title TEXT,
        description TEXT,
        timestamp TEXT
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS likes (
        video_id TEXT PRIMARY KEY,
        count INTEGER DEFAULT 0
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS subscribers (
        channel TEXT,
        username TEXT,
        PRIMARY KEY (channel, username)
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS posts (
        id TEXT PRIMARY KEY,
        channel TEXT,
        title TEXT,
        content TEXT,
        date TEXT
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT,
        video_id TEXT,
        watched_at TEXT
    )
    """)

    conn.commit()
    conn.close()

def migrate_json_to_db():
    conn = get_db()
    c = conn.cursor()

    def table_empty(table):
        c.execute(f"SELECT COUNT(*) FROM {table}")
        return c.fetchone()[0] == 0

    # MIGRATE videos.json
    if table_empty("videos") and os.path.exists("videos.json"):
        with open("videos.json", "r", encoding="utf-8") as f:
            data = json.load(f)

        for v in data:
            subtitles = json.dumps(v.get("subtitles", []), ensure_ascii=False)
            c.execute("""
                INSERT INTO videos (id, filename, title, description, views, channel, thumb, subtitles, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                v.get("id", uuid.uuid4().hex[:10]),
                v.get("filename"),
                v.get("title"),
                v.get("description"),
                v.get("views", 0),
                v.get("channel"),
                v.get("thumb"),
                subtitles,
                v.get("status", "pendente"),
            ))

        print("Migrado videos.json → videos")

    conn.commit()
    conn.close()


if __name__ == "__main__":
    print("Criando banco de dados SQLite...")
    init_db()
    migrate_json_to_db()
    print("Banco criado com sucesso em:", SQLITE_DB)
