import os
import sqlite3

SQLITE_DB = r"D:\sqlite\app.db"
UPLOAD_FOLDER = "static/uploads"

def get_db():
    conn = sqlite3.connect(SQLITE_DB, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def migrar_resolucoes():
    conn = get_db()
    c = conn.cursor()

    # pega todos os vídeos
    c.execute("SELECT id, filename FROM videos")
    rows = c.fetchall()

    for row in rows:
        vid = row["id"]
        filename = row["filename"]

        if not filename:
            continue

        # nomes esperados
        filename_144p = f"144p_{filename}"
        filename_480p = f"480p_{filename}"

        # checa se os arquivos existem
        path_144p = os.path.join(UPLOAD_FOLDER, filename_144p)
        path_480p = os.path.join(UPLOAD_FOLDER, filename_480p)

        update_fields = {}
        if os.path.exists(path_144p):
            update_fields["filename_144p"] = filename_144p
        if os.path.exists(path_480p):
            update_fields["filename_480p"] = filename_480p

        if update_fields:
            set_clause = ", ".join([f"{k} = ?" for k in update_fields.keys()])
            values = list(update_fields.values()) + [vid]
            c.execute(f"UPDATE videos SET {set_clause} WHERE id = ?", values)
            print(f"Atualizado vídeo {vid}: {update_fields}")

    conn.commit()
    conn.close()

if __name__ == "__main__":
    migrar_resolucoes()
