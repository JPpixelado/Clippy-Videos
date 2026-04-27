import sqlite3
import secrets
import datetime
from flask import Flask, request, redirect, jsonify

app = Flask(__name__)
DB = "auth.db"

# ---------- DB ----------

def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()

    c.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT,
        username TEXT,
        password TEXT,
        verified INTEGER DEFAULT 0
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS email_tokens (
        token TEXT PRIMARY KEY,
        user_id INTEGER,
        expires_at TEXT
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS sessions (
        token TEXT PRIMARY KEY,
        user_id INTEGER,
        expires_at TEXT
    )
    """)

    conn.commit()
    conn.close()

init_db()

# ---------- REGISTER ----------

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        email = request.form['email']
        username = request.form['username']
        password = request.form['password']

        conn = get_db()
        c = conn.cursor()

        c.execute(
            "INSERT INTO users (email, username, password) VALUES (?, ?, ?)",
            (email, username, password)
        )
        user_id = c.lastrowid

        token = secrets.token_urlsafe(20)
        expires = (datetime.datetime.utcnow() + datetime.timedelta(minutes=10)).isoformat()

        c.execute(
            "INSERT INTO email_tokens VALUES (?, ?, ?)",
            (token, user_id, expires)
        )

        conn.commit()
        conn.close()

        link = f"http://localhost:7075/auth/{token}"

        return f"""
        <h2>Conta criada!</h2>
        <p>Simulação de email:</p>
        <a href="{link}">{link}</a>
        """

    return """
    <form method="POST">
        <input name="email" placeholder="Email"><br>
        <input name="username" placeholder="Username"><br>
        <input name="password" placeholder="Senha"><br>
        <button>Cadastrar</button>
    </form>
    """

# ---------- AUTH PAGE ----------

@app.route('/auth/<token>')
def auth_page(token):
    return f"""
    <h2>Confirmar email</h2>
    <a href="/auth/{token}/confirm-email">Confirmar</a>
    """

# ---------- CONFIRM EMAIL ----------

@app.route('/auth/<token>/confirm-email')
def confirm_email(token):
    conn = get_db()
    c = conn.cursor()

    c.execute("SELECT * FROM email_tokens WHERE token = ?", (token,))
    row = c.fetchone()

    if not row:
        conn.close()
        return "Token inválido", 404

    # verificar email
    c.execute("UPDATE users SET verified = 1 WHERE id = ?", (row["user_id"],))

    # criar sessão
    session_token = secrets.token_urlsafe(32)
    expires = (datetime.datetime.utcnow() + datetime.timedelta(days=1)).isoformat()

    c.execute(
        "INSERT INTO sessions VALUES (?, ?, ?)",
        (session_token, row["user_id"], expires)
    )

    conn.commit()
    conn.close()

    return redirect(f"https://localhost:7070/auth/callback?token={session_token}")

# ---------- VALIDATE ----------

@app.route('/api/validate')
def validate():
    token = request.args.get("token")

    conn = get_db()
    c = conn.cursor()

    c.execute("""
    SELECT users.username
    FROM sessions
    JOIN users ON users.id = sessions.user_id
    WHERE sessions.token = ?
    """, (token,))

    row = c.fetchone()
    conn.close()

    if not row:
        return jsonify({"valid": False})

    return jsonify({
        "valid": True,
        "username": row["username"]
    })

# ---------- RUN ----------

if __name__ == '__main__':
    print("🔥 Auth server rodando em http://localhost:7075")
    app.run(port=7075, debug=False)
