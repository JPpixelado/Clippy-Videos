# database_utils.py
import sqlite3
import os

# Configuração do caminho do banco
SQLITE_DB = r'D:\sqlite\app.db' if os.name == 'nt' else 'app.db'

def get_db():
    conn = sqlite3.connect(SQLITE_DB)
    conn.row_factory = sqlite3.Row
    return conn

def get_channel_info(username):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM channels WHERE username = ?", (username,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None

def load_videos():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM videos")
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_video(video_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM videos WHERE id = ?", (video_id,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None

def save_video_entry(v):
    conn = get_db()
    c = conn.cursor()
    c.execute("""INSERT INTO videos (id, filename, filename_144p, filename_480p, title, description, views, channel, thumb) 
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""", 
              (v['id'], v['filename'], v['filename_144p'], v['filename_480p'], v['title'], v['description'], v['views'], v['channel'], v['thumb']))
    conn.commit()
    conn.close()

def create_channel_record(username, display_name, bio, password, foto):
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO channels (username, display_name, bio, password, foto) VALUES (?, ?, ?, ?, ?)",
              (username, display_name, bio, password, foto))
    conn.commit()
    conn.close()

def verify_channel_password(entered, stored):
    return entered == stored