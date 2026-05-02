import sqlite3
import secrets
import datetime
import bcrypt
import json
import os
from flask import Flask, request, redirect, jsonify, session, url_for, render_template_string
from flask_mail import Mail, Message
from urllib.parse import urlparse

# Para usar timezone-aware datetime
from datetime import UTC

app = Flask(__name__)
app.secret_key = secrets.token_hex(32)  # Chave secreta para sessões
DB = "auth.db"

# Modo teste (desabilitar envio real de emails)
TEST_MODE = True  # Mude para False quando configurar SMTP real

# Configurações de email
app.config['MAIL_SERVER'] = 'smtp.outlook.com'  # Exemplo, ajustar conforme necessário
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = 'clippyvideos@hotmail.com'  # Substituir
app.config['MAIL_PASSWORD'] = 'clippy(")'  # Substituir - usar app password do Outlook
app.config['MAIL_DEFAULT_SENDER'] = 'clippyvideos@hotmail.com'

mail = Mail(app)

# Lista de sites permitidos (adicionar dinamicamente ou configurar)
ALLOWED_SITES = ['localhost:7070', '192.168.0.150:7070', 'localhost:7075']  # Exemplo

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
        email TEXT UNIQUE,
        username TEXT UNIQUE,
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
        site TEXT,
        expires_at TEXT
    )
    """)

    conn.commit()
    conn.close()

init_db()

# ---------- UTILIDADES ----------

def hash_password(password):
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def check_password(password, hashed):
    return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))

def verify_referer():
    referer = request.headers.get('Referer')
    if not referer:
        return False
    parsed = urlparse(referer)
    site = f"{parsed.netloc}"
    return site in ALLOWED_SITES

def send_verification_email(email, username, code):
    html_template = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; background-color: #f4f4f4; padding: 20px; }}
            .container {{ max-width: 600px; margin: 0 auto; background-color: #ffffff; padding: 20px; border-radius: 8px; box-shadow: 0 0 10px rgba(0,0,0,0.1); }}
            h1 {{ color: #333; }}
            p {{ color: #666; }}
            .code {{ font-size: 24px; font-weight: bold; color: #007bff; background-color: #e9ecef; padding: 10px; border-radius: 4px; display: inline-block; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Verificação de Email</h1>
            <p>Olá {username},</p>
            <p>Obrigado por se registrar. Use o código abaixo para verificar seu email:</p>
            <div class="code">{code}</div>
            <p>Se você não solicitou isso, ignore este email.</p>
        </div>
    </body>
    </html>
    """

    if TEST_MODE:
        # Modo teste: apenas logar o código
        print(f"\n{'='*60}")
        print(f"📧 EMAIL DE VERIFICAÇÃO (MODO TESTE)")
        print(f"{'='*60}")
        print(f"Para: {email}")
        print(f"Assunto: Verificação de Email")
        print(f"Código de Verificação: {code}")
        print(f"{'='*60}\n")
        return
    
    # Modo produção: enviar email real
    msg = Message('Verificação de Email', recipients=[email])
    msg.html = html_template
    mail.send(msg)

def load_emails_from_json():
    try:
        with open('emails.json', 'r') as f:
            data = json.load(f)
            return [user['email'] for user in data if 'email' in user]
    except FileNotFoundError:
        return []

# ---------- ROTAS ----------

@app.before_request
def check_security():
    # Apenas verificar referer em POST/requests que modificam dados
    if request.method in ['POST', 'PUT', 'DELETE']:
        if request.endpoint in ['register', 'login', 'verify', 'bulk_email', 'validate_session']:
            if not verify_referer():
                return jsonify({'error': 'Acesso não autorizado'}), 403

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        email = request.form['email']
        username = request.form['username']
        password = hash_password(request.form['password'])

        conn = get_db()
        c = conn.cursor()

        try:
            c.execute(
                "INSERT INTO users (email, username, password) VALUES (?, ?, ?)",
                (email, username, password)
            )
            user_id = c.lastrowid

            code = secrets.token_hex(4).upper()  # Código de 8 caracteres
            expires = (datetime.datetime.now(UTC) + datetime.timedelta(minutes=10)).isoformat()

            c.execute(
                "INSERT INTO email_tokens VALUES (?, ?, ?)",
                (code, user_id, expires)
            )

            conn.commit()
            send_verification_email(email, username, code)

            return jsonify({'message': 'Registro realizado. Verifique seu email.'})
        except sqlite3.IntegrityError:
            return jsonify({'error': 'Email ou username já existe'}), 400
        finally:
            conn.close()

    return render_template_string("""
    <form method="POST">
        <input name="email" placeholder="Email" required><br>
        <input name="username" placeholder="Username" required><br>
        <input name="password" type="password" placeholder="Senha" required><br>
        <button>Cadastrar</button>
    </form>
    """)

@app.route('/verify', methods=['POST'])
def verify():
    code = request.form['code']
    email = request.form['email']

    conn = get_db()
    c = conn.cursor()

    c.execute("""
    SELECT u.id FROM users u
    JOIN email_tokens et ON u.id = et.user_id
    WHERE u.email = ? AND et.token = ? AND et.expires_at > ?
    """, (email, code, datetime.datetime.now(UTC).isoformat()))

    user = c.fetchone()
    if user:
        c.execute("UPDATE users SET verified = 1 WHERE id = ?", (user['id'],))
        c.execute("DELETE FROM email_tokens WHERE user_id = ?", (user['id'],))
        conn.commit()
        conn.close()
        return jsonify({'message': 'Email verificado com sucesso.'})
    else:
        conn.close()
        return jsonify({'error': 'Código inválido ou expirado'}), 400

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        redirect_url = request.args.get('redirect', '/')

        conn = get_db()
        c = conn.cursor()

        c.execute("SELECT * FROM users WHERE email = ? AND verified = 1", (email,))
        user = c.fetchone()

        if user and check_password(password, user['password']):
            session_token = secrets.token_urlsafe(32)
            expires = (datetime.datetime.now(UTC) + datetime.timedelta(hours=1)).isoformat()
            site = urlparse(request.headers.get('Referer', '')).netloc

            c.execute(
                "INSERT INTO sessions VALUES (?, ?, ?, ?)",
                (session_token, user['id'], site, expires)
            )
            conn.commit()
            conn.close()

            # Redirecionar de volta com token
            return redirect(f"{redirect_url}?token={session_token}")
        else:
            conn.close()
            return jsonify({'error': 'Credenciais inválidas'}), 401

    return render_template_string("""
    <form method="POST">
        <input name="email" placeholder="Email" required><br>
        <input name="password" type="password" placeholder="Senha" required><br>
        <button>Login</button>
    </form>
    """)

@app.route('/bulk_email', methods=['POST'])
def bulk_email():
    # Assumir que é chamado por admin
    emails = load_emails_from_json()
    subject = request.form['subject']
    body = request.form['body']

    for email in emails:
        msg = Message(subject, recipients=[email])
        msg.html = body
        mail.send(msg)

    return jsonify({'message': f'Emails enviados para {len(emails)} usuários.'})

@app.route('/validate_session', methods=['POST'])
def validate_session():
    token = request.form['token']
    site = urlparse(request.headers.get('Referer', '')).netloc

    conn = get_db()
    c = conn.cursor()

    c.execute("SELECT user_id FROM sessions WHERE token = ? AND site = ? AND expires_at > ?",
              (token, site, datetime.datetime.now(UTC).isoformat()))

    session_data = c.fetchone()
    conn.close()

    if session_data:
        return jsonify({'valid': True, 'user_id': session_data['user_id']})
    else:
        return jsonify({'valid': False}), 401

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
    expires = (datetime.datetime.now(UTC) + datetime.timedelta(days=1)).isoformat()
    site = urlparse(request.headers.get('Referer', '')).netloc or 'localhost:7070'

    c.execute(
        "INSERT INTO sessions VALUES (?, ?, ?, ?)",
        (session_token, row["user_id"], site, expires)
    )

    conn.commit()
    conn.close()

    return redirect(f"http://localhost:7070/auth/callback?token={session_token}")

# ---------- VALIDATE ----------

@app.route('/api/validate')
def validate():
    token = request.args.get("token")
    site = urlparse(request.headers.get('Referer', '')).netloc or 'localhost:7070'

    conn = get_db()
    c = conn.cursor()

    c.execute("""
    SELECT users.username, sessions.expires_at
    FROM sessions
    JOIN users ON users.id = sessions.user_id
    WHERE sessions.token = ? AND sessions.site = ? AND sessions.expires_at > ?
    """, (token, site, datetime.datetime.now(UTC).isoformat()))

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
    app.run(port=7075, debug=True)