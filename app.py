# app.py
STATIC_SERVER_URL = "httpS://192.168.0.150:7071/"
STUDIO_BASE_URL = "httpS://192.168.0.150:7072/"  # URL do servidor independente
import os
import json
import uuid
import random
import subprocess
import sqlite3
from flask_socketio import SocketIO
from flask import Flask, render_template, request, redirect, url_for, session, send_from_directory, send_file, jsonify, abort, flash
from werkzeug.utils import secure_filename
from datetime import datetime
from admin import admin_bp
from flask import request

# ---------- CONFIG ----------

# Path to SQLite DB (you requested D:\sqlite)
# Se estiver no Windows, usa o caminho da D:, se não, usa o caminho do servidor
if os.name == 'nt':
    SQLITE_DB = r'D:\sqlite\app.db'
else:
    # No PythonAnywhere, ele vai criar o banco na mesma pasta do projeto
    SQLITE_DB = os.path.join(os.path.dirname(__file__), 'app.db')

# No app.py principal, mude para o caminho absoluto da nova pasta
if os.name == 'nt':
    BASE_STATIC = r'D:\cstatic\static'
    UPLOAD_FOLDER = os.path.join(BASE_STATIC, 'uploads')
    CHAT_FILES_FOLDER = os.path.join(BASE_STATIC, 'chat_uploads')
    COMMENTS_FOLDER = 'coments'
else:
    # No PythonAnywhere (mantém o padrão se não for mudar lá também)
    UPLOAD_FOLDER = 'static/uploads'
    CHAT_FILES_FOLDER = 'static/chat_uploads'

# App
app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = int(5 * 1024 * 1024 * 1024)
app.config['UPLOAD_FOLDER_CHAT'] = os.path.join('static', 'chat_uploads')
app.secret_key = 'chave-secreta-do-jp'

FFMPEG_PATH = r'D:\ffmpeg\bin\ffmpeg.exe'

app.register_blueprint(admin_bp)

@app.context_processor
def inject_static_url():
    # Isso permite usar {{ static_url }} em qualquer HTML
    return dict(static_url=STATIC_SERVER_URL)

# Ensure folders
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(COMMENTS_FOLDER, exist_ok=True)
os.makedirs(os.path.dirname(SQLITE_DB), exist_ok=True)
os.makedirs(CHAT_FILES_FOLDER, exist_ok=True)

# ---------- DB helpers ----------

def get_db():
    conn = sqlite3.connect(SQLITE_DB, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    
    # users
    c.execute("""
    CREATE TABLE IF NOT EXISTS users (
        username TEXT PRIMARY KEY,
        nome TEXT,
        email TEXT,
        password TEXT,
        is_pro INTEGER DEFAULT 0  -- adicionado aqui para suportar o PRO
    )
    """)
    
    # channels
    c.execute("""
    CREATE TABLE IF NOT EXISTS channels (
        username TEXT PRIMARY KEY,
        display_name TEXT,
        bio TEXT,
        password TEXT,
        foto_path TEXT
    )
    """)
    
    # videos
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
        status TEXT DEFAULT 'pendente',
        classificacao TEXT DEFAULT 'L'  -- Novo campo: 'L', '10', 'A10', '12', 'A12', '14', 'A14', '16', 'A16', '18', 'A18'.
    )
    """)
    
    # lives
    c.execute("""
    CREATE TABLE IF NOT EXISTS lives (
        id TEXT PRIMARY KEY,
        channel TEXT,
        title TEXT,
        status TEXT,
        started_at TEXT
    )
    """)
    
    # collabs
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
    
    # shorts
    c.execute("""
    CREATE TABLE IF NOT EXISTS shorts (
        id INTEGER PRIMARY KEY,
        filename TEXT,
        title TEXT,
        description TEXT,
        timestamp TEXT
    )
    """)
    
    # likes
    c.execute("""
    CREATE TABLE IF NOT EXISTS likes (
        video_id TEXT PRIMARY KEY,
        count INTEGER DEFAULT 0
    )
    """)
    
    # subscribers
    c.execute("""
    CREATE TABLE IF NOT EXISTS subscribers (
        channel TEXT,
        username TEXT,
        PRIMARY KEY (channel, username)
    )
    """)
    
    # posts
    c.execute("""
    CREATE TABLE IF NOT EXISTS posts (
        id TEXT PRIMARY KEY,
        channel TEXT,
        title TEXT,
        content TEXT,
        date TEXT
    )
    """)
    
    # history
    c.execute("""
    CREATE TABLE IF NOT EXISTS history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT,
        video_id TEXT,
        watched_at TEXT
    )
    """)
    
    # playlists (agora dentro da mesma conexão)
    c.execute("""
    CREATE TABLE IF NOT EXISTS playlists (
        id TEXT PRIMARY KEY,
        user_username TEXT NOT NULL,
        title TEXT NOT NULL,
        description TEXT,
        is_public INTEGER DEFAULT 0,
        created_at TEXT,
        updated_at TEXT
    )
    """)
    
    # playlist_items
    c.execute("""
    CREATE TABLE IF NOT EXISTS playlist_items (
        playlist_id TEXT,
        video_id TEXT,
        position INTEGER DEFAULT 0,
        added_at TEXT,
        PRIMARY KEY (playlist_id, video_id),
        FOREIGN KEY (playlist_id) REFERENCES playlists(id) ON DELETE CASCADE
    )
    """)
    
    # Commit uma única vez no final
    conn.commit()
    conn.close()

def migrate_json_to_db():
    """
    If there are existing JSON files (videos.json, lives.json, shorts.json, users.json, collabs.json),
    try to import them into the SQLite DB. This runs only if the tables are empty.
    """
    conn = get_db()
    c = conn.cursor()

    # check videos table empty
    c.execute("SELECT COUNT(*) FROM videos")
    if c.fetchone()[0] == 0 and os.path.exists("videos.json"):
        try:
            with open("videos.json", "r", encoding="utf-8") as f:
                videos = json.load(f)
            for v in videos:
                vid = str(v.get("id") or uuid.uuid4().hex[:10])
                subtitles = json.dumps(v.get("subtitles", []), ensure_ascii=False)
                c.execute("""
                    INSERT OR IGNORE INTO videos (id, filename, title, description, views, channel, thumb, subtitles, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    vid,
                    v.get("filename"),
                    v.get("title"),
                    v.get("description"),
                    int(v.get("views", 0)),
                    v.get("channel"),
                    v.get("thumb"),
                    subtitles,
                    v.get("status", "pendente")
                ))
            conn.commit()
            print("Migrated videos.json -> videos table")
        except Exception as e:
            print("Migration videos.json failed:", e)

    # lives
    c.execute("SELECT COUNT(*) FROM lives")
    if c.fetchone()[0] == 0 and os.path.exists("lives.json"):
        try:
            with open("lives.json", "r", encoding="utf-8") as f:
                lives = json.load(f)
            for l in lives:
                c.execute("""
                    INSERT OR IGNORE INTO lives (id, channel, title, status, started_at) VALUES (?, ?, ?, ?, ?)
                """, (l.get("id"), l.get("channel"), l.get("title"), l.get("status"), l.get("started_at")))
            conn.commit()
            print("Migrated lives.json -> lives table")
        except Exception as e:
            print("Migration lives.json failed:", e)

    # shorts
    c.execute("SELECT COUNT(*) FROM shorts")
    if c.fetchone()[0] == 0 and os.path.exists("shorts.json"):
        try:
            with open("shorts.json", "r", encoding="utf-8") as f:
                shorts = json.load(f)
            for s in shorts:
                c.execute("""
                    INSERT OR IGNORE INTO shorts (id, filename, title, description, timestamp) VALUES (?, ?, ?, ?, ?)
                """, (s.get("id"), s.get("filename"), s.get("title"), s.get("description"), s.get("timestamp")))
            conn.commit()
            print("Migrated shorts.json -> shorts table")
        except Exception as e:
            print("Migration shorts.json failed:", e)

    # users
    c.execute("SELECT COUNT(*) FROM users")
    if c.fetchone()[0] == 0 and os.path.exists("users.json"):
        try:
            with open("users.json", "r", encoding="utf-8") as f:
                users = json.load(f)
            for u in users:
                c.execute("INSERT OR IGNORE INTO users (username, nome, email, password) VALUES (?, ?, ?, ?)",
                          (u.get("username"), u.get("nome"), u.get("email"), u.get("password")))
            conn.commit()
            print("Migrated users.json -> users table")
        except Exception as e:
            print("Migration users.json failed:", e)

    # collabs.json
    c.execute("SELECT COUNT(*) FROM collabs")
    if c.fetchone()[0] == 0 and os.path.exists("collabs.json"):
        try:
            with open("collabs.json", "r", encoding="utf-8") as f:
                collabs = json.load(f)
            # collabs.json structure: list of {video_id, title, channel, collaborators:[{name,role,status}]}
            for entry in collabs:
                vid = entry.get("video_id")
                title = entry.get("title", "Título desconhecido")
                channel = entry.get("channel")
                for cdata in entry.get("collaborators", []):
                    c.execute("""
                        INSERT INTO collabs (video_id, video_title, channel, name, role, status)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (vid, title, channel, cdata.get("name"), cdata.get("role"), cdata.get("status")))
            conn.commit()
            print("Migrated collabs.json -> collabs table")
        except Exception as e:
            print("Migration collabs.json failed:", e)

    conn.close()

# Initialize DB and maybe migrate
init_db()
migrate_json_to_db()

# ---------- Utility functions (DB-backed) ----------

def load_videos():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM videos")
    rows = c.fetchall()
    videos = []
    for r in rows:
        v = dict(r)
        v['subtitles'] = json.loads(v['subtitles']) if v['subtitles'] else []
        videos.append(v)
    conn.close()
    return videos

def save_video_entry(video_entry):
    conn = get_db()
    c = conn.cursor()
    
    # Resolve o erro de "subtitles_json is not defined"
    subtitles_json = "" 

    c.execute("""
        INSERT OR REPLACE INTO videos (
            id, filename, filename_144p, filename_480p, 
            title, description, views, channel, thumb, 
            subtitles, status
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        video_entry['id'],
        video_entry.get('filename'),
        video_entry.get('filename_144p', ''),
        video_entry.get('filename_480p', ''),
        video_entry.get('title'),
        video_entry.get('description', ''),
        int(video_entry.get('views', 0)),
        video_entry.get('channel'),
        video_entry.get('thumb'),
        subtitles_json, # Agora a variável existe acima
        video_entry.get('status', 'pendente')
    ))
    conn.commit()
    conn.close()

def get_video(video_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM videos WHERE id = ?", (str(video_id),))
    row = c.fetchone()
    conn.close()
    if not row:
        return None
    v = dict(row)
    v['subtitles'] = json.loads(v['subtitles']) if v['subtitles'] else []
    return v

def increment_video_views(video_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE videos SET views = views + 1 WHERE id = ?", (str(video_id),))
    conn.commit()
    conn.close()

def load_lives():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM lives")
    rows = c.fetchall()
    lives = [dict(r) for r in rows]
    conn.close()
    return lives

def save_live(l):
    conn = get_db()
    c = conn.cursor()
    c.execute("""
        INSERT OR REPLACE INTO lives (id, channel, title, status, started_at) VALUES (?, ?, ?, ?, ?)
    """, (l['id'], l['channel'], l['title'], l['status'], l['started_at']))
    conn.commit()
    conn.close()

def save_shorts_entry(s):
    conn = get_db()
    c = conn.cursor()
    c.execute("""
        INSERT OR REPLACE INTO shorts (id, filename, title, description, timestamp) VALUES (?, ?, ?, ?, ?)
    """, (s['id'], s['filename'], s['title'], s['description'], s['timestamp']))
    conn.commit()
    conn.close()

def get_channel_info(username):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM channels WHERE username = ?", (username,))
    r = c.fetchone()
    conn.close()
    return dict(r) if r else None

def create_channel_record(username, display_name, bio, password, foto_path=None):
    conn = get_db()
    c = conn.cursor()
    c.execute("""
        INSERT OR REPLACE INTO channels (username, display_name, bio, password, foto_path) VALUES (?, ?, ?, ?, ?)
    """, (username, display_name, bio, password, foto_path))
    conn.commit()
    conn.close()

def load_users():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT username, nome, email, password FROM users")
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def save_user(u):
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO users (username, nome, email, password) VALUES (?, ?, ?, ?)",
              (u['username'], u['nome'], u['email'], u['password']))
    conn.commit()
    conn.close()

def verify_channel_password(senha_digitada, senha_salva):
    # Model 1: simple comparison
    return senha_digitada == senha_salva

# ---------- Helper: format_time & subtitle generation ----------

def format_time(t):
    millis = int((t - int(t)) * 1000)
    sec = int(t) % 60
    mins = (int(t) // 60) % 60
    hrs = int(t) // 3600
    return f"{hrs:02}:{mins:02}:{sec:02}.{millis:03}"

# ----> json <----

# Função auxiliar para pegar o caminho do config.json
def get_user_config_path(username):
    # Caminho base: users/usuario
    user_folder = os.path.join('users', username)
    
    # 1. Cria a pasta do utilizador se não existir
    if not os.path.exists(user_folder):
        os.makedirs(user_folder)
        print(f"Pasta criada para: {username}")

    config_path = os.path.join(user_folder, 'configs.json')

    # 2. Cria o ficheiro JSON com valores padrão se não existir
    if not os.path.exists(config_path):
        default_configs = {
            'cor_fundo': '#f0f2f5',
            'idade': '18',
            'tema': 'claro'
        }
        with open(config_path, 'w') as f:
            json.dump(default_configs, f)
        print(f"Configurações padrão criadas para: {username}")

    return config_path
    
def precisa_supervisao(username):
    path = get_user_config_path(username)
    if not os.path.exists(path):
        return False
    with open(path, 'r') as f:
        configs = json.load(f)
    try:
        idade = int(configs.get('idade', 18))
        return 2 <= idade <= 11  # Agora de 2 a 11 anos
    except:
        return False

def pode_assistir_video(classificacao_video, max_permitido):
    """
    Retorna True se o vídeo pode ser assistido com base na classificação máxima permitida.
    Ex: max_permitido='A12' → permite L, 10, A10, 12, A12
    """
    ordem = {
        'L': 0,
        '10': 10, 'A10': 10,
        '12': 12, 'A12': 12,
        '14': 14, 'A14': 14,
        '16': 16, 'A16': 16,
        '18': 18, 'A18': 18
    }
    
    # Se não tiver classificação, assume Livre
    video_num = ordem.get(classificacao_video or 'L', 0)
    max_num = ordem.get(max_permitido or '18', 18)
    
    return video_num <= max_num
# ---------- Routes (kept structure from your original app) ----------

@app.route('/', methods=['GET', 'POST'])
def index():
    ua = request.user_agent.string.lower()
    if 'mobile' in ua or 'android' in ua or 'iphone' in ua:
        return redirect('/lang=mobile')

    if request.method == 'POST':
        video = request.files.get('video')
        thumb = request.files.get('thumb')
        title = request.form.get('title')
        description = request.form.get('description')

        if video:
            filename = secure_filename(video.filename)
            video.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))

            thumb_filename = ''
            if thumb and thumb.filename != '':
                thumb_filename = 'thumb_' + secure_filename(thumb.filename)
                thumb.save(os.path.join(app.config['UPLOAD_FOLDER'], thumb_filename))

            vid = uuid.uuid4().hex[:10]
            video_entry = {
                'id': vid,
                'filename': filename,
                'filename_144p': f'144p_{filename}',
                'filename_480p': f'480p_{filename}',
                'title': title,
                'description': description,
                'views': 0,
                'channel': None,
                'thumb': thumb_filename,
                'subtitles': [],
                'status': 'pendente'
            }
            save_video_entry(video_entry)

    # Carrega todos os vídeos do banco
    all_videos = load_videos()

    # Define classificação máxima padrão (para não logados ou adultos)
    max_class = '18'

    username = session.get("username")
    studio_link = None
    
    if username:
        # Carrega configs do usuário logado
        path = get_user_config_path(username)
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                configs = json.load(f)
            max_class = configs.get('classificacao_maxima', '18')

        # Carrega link do studio (só para logados)
        studio_path = os.path.join("users", username, "studio.txt")
        if os.path.exists(studio_path):
            with open(studio_path, "r", encoding="utf-8") as f:
                relative_path = f.read().strip()
            studio_link = STUDIO_BASE_URL + relative_path.lstrip('/')
    else:
        studio_link = None

    # Filtra vídeos permitidos
    videos_permitidos = [
        v for v in all_videos
        if pode_assistir_video(v.get('classificacao', 'L'), max_class)
    ]

    # Embaralha os permitidos
    videos_embaralhados = random.sample(videos_permitidos, len(videos_permitidos)) if len(videos_permitidos) > 1 else videos_permitidos

    return render_template("index.html",
                           videos=videos_embaralhados,
                           studio_link=studio_link,
                           max_class=max_class)  # opcional

@app.before_request
def check_menor_idade():
    if 'username' not in session:
        return
    
    username = session['username']
    
    # Se não precisa de supervisão, libera tudo
    if not precisa_supervisao(username):
        return
    
    path = get_user_config_path(username)
    if not os.path.exists(path):
        print(f"[DEBUG BLOQUEIO] Arquivo configs não existe: {path}")
        return redirect(url_for('configs'))
    
    # Lê sempre fresco (sem cache)
    with open(path, 'r', encoding='utf-8') as f:
        configs = json.load(f)
    
    supervisao_ativa = configs.get('supervisao_ativa', False)
    print(f"[DEBUG BLOQUEIO] Usuário {username} - supervisao_ativa: {supervisao_ativa}")
    
    if not supervisao_ativa:
        # Permite apenas as rotas de configuração
        if not (request.path.startswith('/configs') or request.path.startswith('/supervisao-confirmar')):
            flash("Sua conta está em modo infantil. Configure a supervisão para continuar.")
            return redirect(url_for('configs'))

# ---- Live endpoints ----

@app.route('/live')
def live():
    username = session.get('username')
    if not username:
        return redirect('/login')
    return render_template('live.html', username=username)

@app.route('/lives/<live_id>')
def lives(live_id):
    lives_data = load_lives()
    live = next((l for l in lives_data if l['id'] == live_id), None)
    if not live:
        return "Live não encontrada", 404
    return render_template('lives.html', live=live)

@app.route('/api/live/create', methods=['POST'])
def api_live_create():
    username = session.get('username')
    if not username:
        return jsonify({"error": "não logado"}), 403

    data = request.get_json()
    title = data.get('title', 'Live sem título')
    password = data.get('password', '').strip()

    channel = get_channel_info(username)
    if not channel:
        return jsonify({"error": "canal não encontrado"}), 404

    stored_password = channel.get('password', '')
    if password != stored_password:
        return jsonify({"error": "senha incorreta"}), 403

    live_id = "live_" + uuid.uuid4().hex[:8]
    live = {
        "id": live_id,
        "channel": username,
        "title": title,
        "status": "online",
        "started_at": datetime.utcnow().isoformat()
    }
    save_live(live)
    return jsonify({"id": live_id, "title": title, "channel": username})

@app.route('/api/live/stop', methods=['POST'])
def api_live_stop():
    data = request.get_json()
    live_id = data.get('id')
    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE lives SET status = 'offline' WHERE id = ?", (live_id,))
    conn.commit()
    conn.close()
    return jsonify({"status": "encerrada"})

# ----- Player -----

@app.route('/player/<item_id>')
def player(item_id):
    likes = {}

    video = get_video(item_id)
    if video:
        if video.get('status') == 'bloqueado':
            return "🚫 Este vídeo foi bloqueado por direitos autorais ou violação de regras.", 403

        increment_video_views(item_id)

        # comments: read from folder as before
        caminho_comentarios = os.path.join(COMMENTS_FOLDER, f'{item_id}.txt')
        comentarios = []
        if os.path.exists(caminho_comentarios):
            with open(caminho_comentarios, 'r', encoding='utf-8') as f:
                comentarios = f.readlines()

        videos_data = load_videos()
        relacionados = [v for v in videos_data if str(v['id']) != str(item_id)]

        username = session.get('username')
        playlists = []
        if username:
            conn = get_db()
            c = conn.cursor()
            c.execute("SELECT id, title FROM playlists WHERE user_username = ? ORDER BY updated_at DESC", (username,))
            playlists = [dict(row) for row in c.fetchall()]
            conn.close()

        # likes
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT count FROM likes WHERE video_id = ?", (str(item_id),))
        r = c.fetchone()
        likes = {str(item_id): r['count']} if r else {}

        # channel info
        canal_username = video.get('channel')
        canal_display_name = canal_username or ''
        canal_bio = ''
        canal_foto = '/static/user.png'
        if canal_username:
            ch = get_channel_info(canal_username)
            if ch:
                canal_display_name = ch.get('display_name', canal_username)
                canal_bio = ch.get('bio', '')
                foto_path = ch.get('foto_path')
                if foto_path and os.path.exists(foto_path):
                    canal_foto = f'/channels/@{canal_username}/foto.jpg'
                else:
                    canal_foto = '/static/user.png'

        # collabs
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT name, role, status FROM collabs WHERE video_id = ?", (str(item_id),))
        collabs_rows = c.fetchall()
        collabs = [dict(r) for r in collabs_rows]
        conn.close()

        # history
        if username:
            conn = get_db()
            c = conn.cursor()
            c.execute("INSERT INTO history (username, video_id, watched_at) VALUES (?, ?, ?)",
                      (username, item_id, datetime.utcnow().isoformat()))
            conn.commit()
            conn.close()

        return render_template(
            'player.html',
            tipo="video",
            video=video,
            comentarios=comentarios,
            relacionados=relacionados,
            playlists=playlists,
            likes=likes,
            canal_username=canal_username,
            canal_display_name=canal_display_name,
            canal_bio=canal_bio,
            canal_foto=canal_foto,
            collabs=collabs
        )

    # Try live
    lives_data = load_lives()
    live = next((l for l in lives_data if str(l['id']) == str(item_id)), None)
    if live and live.get('status') == "online":
        return render_template('player.html', tipo="live", live=live, likes={})

    return "Conteúdo não encontrado", 500

# comments
@app.route('/comentar/<video_id>', methods=['POST'])
def comentar(video_id):
    # SEGURANÇA: Só permite comentar se houver usuário na sessão
    username = session.get('username')
    if not username:
        flash("Você precisa estar logado para comentar.")
        return redirect(url_for('login'))

    texto = request.form.get('comentario', '').strip()
    
    if texto:
        caminho = os.path.join(COMMENTS_FOLDER, f'{video_id}.txt')
        # Salvamos no formato "username|texto" para facilitar a separação depois
        with open(caminho, 'a', encoding='utf-8') as f:
            f.write(f'{username}|{texto}\n')
        return redirect(url_for('player', item_id=video_id))
        
    return 'Comentário vazio', 400

# search
@app.route('/buscar')
def buscar():
    query = request.args.get('q', '').lower()
    videos = load_videos()
    if query:
        videos = [v for v in videos if (v.get('title') or '').lower().find(query) != -1 or (v.get('description') or '').lower().find(query) != -1]

    canais_list = []
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT username, display_name, bio FROM channels")
    for row in c.fetchall():
        display_name = row['display_name'] or ''
        bio = row['bio'] or ''
        if not query or query in display_name.lower() or query in bio.lower():
            canais_list.append({
                'username': row['username'],
                'display_name': display_name,
                'bio': bio
            })
    conn.close()
    return render_template('buscar.html', videos=videos, canais=canais_list, query=query)

# ---- Users: login/cadastro ----

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        conn = get_db()
        c = conn.cursor()
        
        # 1. Buscamos a senha E o status PRO ao mesmo tempo
        c.execute("SELECT password, is_pro FROM users WHERE username = ?", (username,))
        user_data = c.fetchone()
        conn.close()
        
        if user_data and user_data['password'] == password:
            # 2. Salvamos tudo na sessão
            session['username'] = username
            session['is_pro'] = user_data['is_pro'] # Agora sim, pegando do banco!
            
            return redirect(url_for('index'))
            
        return 'Login inválido', 401
        
    return render_template('login.html')

@app.route('/cadastro', methods=['POST'])
def cadastro():
    nome = request.form.get('nome')
    email = request.form.get('email')
    username = request.form.get('username')
    password = request.form.get('password')
    if not all([nome, email, username, password]):
        return 'Dados incompletos', 400
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT 1 FROM users WHERE username = ?", (username,))
    if c.fetchone():
        conn.close()
        return 'Usuário já existe', 409
    c.execute("INSERT INTO users (username, nome, email, password) VALUES (?, ?, ?, ?)",
              (username, nome, email, password))
    conn.commit()
    conn.close()
    # also create users folder for studio link usage
    user_dir = os.path.join("users", username)
    os.makedirs(user_dir, exist_ok=True)
    with open(os.path.join(user_dir, "profile.txt"), "w", encoding="utf-8") as f:
        f.write(nome)
    return redirect(url_for('login'))

# ---- Create channel (studio) ----
# ---- Channel page ----

@app.route('/@<username>')
def canal(username):
    channel_path = os.path.join('channels', f'@{username}')
    info_path = os.path.join(channel_path, 'info.txt')

    display_name = username
    bio = ''
    if os.path.exists(info_path):
        with open(info_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            display_name = lines[0].strip()
            bio = lines[1].strip() if len(lines) > 1 else ''

    videos = [v for v in load_videos() if v.get('channel') == username]

    # subscribers
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT username FROM subscribers WHERE channel = ?", (username,))
    inscritos = [r['username'] for r in c.fetchall()]
    conn.close()
    subscribers = len(inscritos)
    ja_inscrito = False
    if 'username' in session:
        ja_inscrito = session['username'] in inscritos

    return render_template('canal.html',
                           username=username,
                           display_name=display_name,
                           bio=bio,
                           channel_videos=videos,
                           subscribers=subscribers,
                           ja_inscrito=ja_inscrito)

@app.route('/inscrever/<username>', methods=['POST'])
def inscrever(username):
    if 'username' not in session:
        flash("Você precisa estar logado para se inscrever em um canal.")
        return redirect(url_for('login'))
    inscrito = session['username']
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT 1 FROM subscribers WHERE channel = ? AND username = ?", (username, inscrito))
    if c.fetchone():
        conn.close()
        return 'Você já está inscrito neste canal.', 403
    c.execute("INSERT INTO subscribers (channel, username) VALUES (?, ?)", (username, inscrito))
    conn.commit()
    conn.close()
    flash(f"Inscrição no canal @{username} feita com sucesso!")
    return redirect(url_for('canal', username=username))

# route to serve channel photo
@app.route('/channels/@<username>/<filename>')
def canal_foto(username, filename):
    return send_from_directory(os.path.join('channels', f'@{username}'), filename)

# request_collab
# playlists & mobile routes kept similar, omitted here for brevity but can be ported to DB if needed
# I'll keep the rest of your endpoints (mobile, shorts, likes, posts, history) implemented using DB where applicable.

@app.route('/lang=mobile')
def mobile_view():
    username = session.get('username')
    videos = load_videos()
    return render_template('mobile.html', username=username, videos=videos)

@app.route('/lang=mobile/buscar')
def mobile_buscar():
    query = request.args.get('q', '').lower()
    videos = load_videos()
    if query:
        videos = [v for v in videos if query in (v.get('title') or '').lower()]
    return render_template('mobile-buscar.html', videos=videos, query=query)

@app.route('/lang=mobile/video/<video_id>')
def mobile_player(video_id):
    video = get_video(video_id)
    if video:
        video['views'] = int(video.get('views', 0)) + 1
        save_video_entry(video)
        caminho = os.path.join(COMMENTS_FOLDER, f'{video_id}.txt')
        comentarios = []
        if os.path.exists(caminho):
            with open(caminho, 'r', encoding='utf-8') as f:
                comentarios = f.readlines()
        relacionados = [v for v in load_videos() if v['id'] != video_id]
        username = session.get('username')
        playlists = []
        if username:
            playlists_path = os.path.join('users', f'@{username}', 'playlists.json')
            if os.path.exists(playlists_path):
                with open(playlists_path, 'r', encoding='utf-8') as f:
                    playlists = json.load(f)
        return render_template('mobile_video.html', video=video, comentarios=comentarios, relacionados=relacionados, playlists=playlists)
    return "Vídeo não encontrado", 404

@app.route('/watch/<video_id>', endpoint="watch")
def watch(video_id):
    video = get_video(video_id)
    if not video:
        abort(404)
    
    # BUSCAR VÍDEOS RELACIONADOS (isso resolve o erro 'relacionados' is undefined)
    videos_data = load_videos()
    # Pega todos os vídeos, exceto o que está sendo assistido agora
    relacionados = [v for v in videos_data if str(v['id']) != str(video_id)]
    
    # Passamos o 'relacionados' para o template
    return render_template("watch.html", video=video, relacionados=relacionados)

@app.route('/like_video', methods=['POST'])
def like_video():
    data = request.get_json()
    video_id = str(data.get('id'))
    if not video_id:
        return 'ID inválido', 400
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT count FROM likes WHERE video_id = ?", (video_id,))
    r = c.fetchone()
    if r:
        c.execute("UPDATE likes SET count = count + 1 WHERE video_id = ?", (video_id,))
    else:
        c.execute("INSERT INTO likes (video_id, count) VALUES (?, ?)", (video_id, 1))
    conn.commit()
    conn.close()
    return 'Like registrado', 200

@app.route("/shorts")
def shorts():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM shorts")
    shorts_data = [dict(r) for r in c.fetchall()]
    conn.close()
    return render_template("shorts.html", shorts=shorts_data)

@app.route('/upload_short', methods=['POST'])
def upload_short():
    file = request.files.get('video')
    if not file:
        return jsonify({'error': 'Nenhum vídeo enviado'}), 400
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT MAX(id) as mx FROM shorts")
    r = c.fetchone()
    next_id = (r['mx'] + 1) if r and r['mx'] is not None else 0
    shorts_folder = os.path.join('static', 'uploads')
    os.makedirs(shorts_folder, exist_ok=True)
    filename = secure_filename(file.filename)
    filepath = os.path.join(shorts_folder, filename)
    file.save(filepath)
    data = {
        "id": next_id,
        "filename": filename,
        "title": request.form.get('title', 'Short sem título'),
        "description": request.form.get('description', ''),
        "timestamp": datetime.now().isoformat()
    }
    save_shorts_entry(data)
    return jsonify({'success': True, 'id': next_id, 'filename': filename}), 200

@app.route('/@<username>/posts')
def user_posts(username):
    channel_path = os.path.join('channels', f'@{username}')
    info_path = os.path.join(channel_path, 'info.txt')
    subs_path = os.path.join(channel_path, 'subscribers.txt')
    posts_path = os.path.join(channel_path, 'posts.json')
    if not os.path.exists(info_path):
        return 'Canal não encontrado', 404
    with open(info_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
        display_name = lines[0].strip()
        bio = lines[1].strip() if len(lines) > 1 else ''
    # subscribers
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT username FROM subscribers WHERE channel = ?", (username,))
    inscritos = [r['username'] for r in c.fetchall()]
    conn.close()
    subscribers = len(inscritos)
    ja_inscrito = False
    if 'username' in session:
        ja_inscrito = session['username'] in inscritos
    # posts from DB
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id, title, content, date FROM posts WHERE channel = ?", (username,))
    posts = [dict(r) for r in c.fetchall()]
    conn.close()
    return render_template('posts.html',
                           username=username,
                           display_name=display_name,
                           bio=bio,
                           subscribers=subscribers,
                           ja_inscrito=ja_inscrito,
                           posts=posts)

@app.route('/aovivo')
def aovivo():
    lives = [l for l in load_lives() if l.get('status') == 'online']
    return render_template('aovivo.html', lives=lives)

@app.route('/historico')
def historico():
    username = session.get('username')
    if not username:
        return redirect('/login')
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT video_id FROM history WHERE username = ? ORDER BY id DESC", (username,))
    rows = c.fetchall()
    video_ids = [r['video_id'] for r in rows]
    all_videos = load_videos()
    videos = []
    for vid in video_ids:
        v = next((x for x in all_videos if str(x['id']) == str(vid)), None)
        if v:
            videos.append(v)
    conn.close()
    return render_template("historico.html", videos=videos)

@app.route('/foto_canal/<username>')
def foto_canal(username):
    channel_path = os.path.join("channels", f"@{username}")
    foto_path = os.path.join(channel_path, "foto.jpg")
    if not os.path.exists(foto_path):
        return send_file("static/user.png", mimetype='image/png')
    referer = request.headers.get("Referer", "")
    # optional: same-host check
    # if not referer.startswith(request.host_url):
    #     return "Acesso negado", 403
    return send_file(foto_path, mimetype='image/jpeg')

@app.errorhandler(500)
def internal_error(e):
    return render_template("erro.html", error_message="Erro interno no servidor"), 500

@app.route('/ia')
def ia():
    return render_template("ia.html")

# --- NOVAS ROTAS PARA SISTEMA DE COLLABS ---
# ===========================================
@app.route('/download/<video_id>')
def download_video(video_id):
    username = session.get('username')
    if not username:
        flash("Você precisa estar logado para baixar vídeos.")
        return redirect(url_for('login'))

    conn = get_db()
    c = conn.cursor()

    # 1. Verificar se o usuário é PRO
    c.execute("SELECT is_pro FROM users WHERE username = ?", (username,))
    user = c.fetchone()
    
    if not user or not user['is_pro']:
        conn.close()
        return "Acesso negado: Esta funcionalidade é exclusiva para membros PRO.", 403

    # 2. Buscar o nome do arquivo do vídeo
    c.execute("SELECT filename, filename_480p, filename_144p FROM videos WHERE id = ?", (video_id,))
    video = c.fetchone()
    conn.close()

    if not video:
        return "Vídeo não encontrado.", 404

    # Escolhe a melhor qualidade disponível para o download
    filename = video['filename'] or video['filename_480p'] or video['filename_144p']
    
    return send_from_directory(
        app.config['UPLOAD_FOLDER'], 
        filename, 
        as_attachment=True # Isso força o navegador a baixar em vez de dar play
    )
    
@app.route('/pro')
def pro_page():
    return render_template("pro.html")

@app.route('/api/upgrade-pro', methods=['POST'])
def upgrade_pro():
    username = session.get('username')
    if not username:
        return redirect(url_for('login'))

    conn = get_db()
    c = conn.cursor()
    
    # Atualiza o usuário para PRO no banco de dados
    c.execute("UPDATE users SET is_pro = 1 WHERE username = ?", (username,))
    conn.commit()
    conn.close()

    # Atualiza a sessão para o site reconhecer na hora
    session['is_pro'] = 1
    
    flash("Parabéns! Agora você é um membro PRO do Clippy!")
    return redirect(url_for('index'))
    
@app.route('/chat/<chat_id>')
def chat_especifico(chat_id):
    if 'username' not in session: return redirect(url_for('login'))
    username_logado = session['username']
    
    conn = get_db()
    conn.row_factory = sqlite3.Row # ESSA LINHA É OBRIGATÓRIA
    c = conn.cursor()
    
    # 1. VERIFICAÇÃO DE ACESSO
    c.execute("SELECT user1, user2 FROM chat_rooms WHERE chat_id = ?", (chat_id,))
    room = c.fetchone()
    
    if not room:
        conn.close()
        return "Chat não encontrado.", 404
    
    if username_logado != room['user1'] and username_logado != room['user2']:
        conn.close()
        return "Acesso Negado: Você não tem permissão para ler este chat.", 403

    # 2. BUSCA AS MENSAGENS (Sem a tentativa de descriptografia que estava travando tudo)
    c.execute("SELECT sender, message, file_path FROM chat_messages WHERE chat_id = ? ORDER BY timestamp ASC", (chat_id,))
    rows = c.fetchall()
    conn.close()

    # Converte as linhas do banco diretamente para uma lista que o HTML entende
    messages = [dict(row) for row in rows]

    return render_template("chat.html", messages=messages, chat_id=chat_id, username=username_logado)

@app.route('/api/chat/send/<chat_id>', methods=['POST']) # Adicionado <chat_id>
def chat_send(chat_id): # Adicionado chat_id como argumento
    if 'username' not in session: return redirect(url_for('login'))
    
    sender = session['username']
    message = request.form.get('message')
    file = request.files.get('file')
    file_path = None

    if file and file.filename != '':
        filename = secure_filename(file.filename)
        file.save(os.path.join(app.config['UPLOAD_FOLDER_CHAT'], filename))
        file_path = filename

    if message or file_path:
        conn = get_db()
        c = conn.cursor()
        # Salvando texto puro (sem msg_encrypted)
        c.execute("""
            INSERT INTO chat_messages (chat_id, sender, message, file_path)
            VALUES (?, ?, ?, ?)
        """, (chat_id, sender, message, file_path))
        conn.commit()
        conn.close()

    # Redireciona de volta para a mesma página de chat
    return redirect(url_for('chat_especifico', chat_id=chat_id))

@app.route('/iniciar_chat/<destinatario>')
def iniciar_chat(destinatario):
    username_logado = session.get('username')
    if not username_logado: 
        flash("Você precisa estar logado para iniciar uma conversa.")
        return redirect(url_for('login'))
    
    if username_logado == destinatario:
        return "Você não pode iniciar um chat consigo mesmo.", 400

    # Criamos um ID único baseado nos dois usuários (em ordem alfabética)
    par = sorted([username_logado, destinatario])
    chat_id = f"chat_{par[0]}_{par[1]}"
    
    conn = get_db()
    c = conn.cursor()
    
    # Registra a sala de chat se ela ainda não existir
    c.execute("""
        INSERT OR IGNORE INTO chat_rooms (chat_id, user1, user2) 
        VALUES (?, ?, ?)
    """, (chat_id, par[0], par[1]))
    
    conn.commit()
    conn.close()
    
    return redirect(url_for('chat_especifico', chat_id=chat_id))

@app.route('/chats')
def lista_chats():
    # Verifica se o usuário está logado
    if 'username' not in session:
        return redirect(url_for('login'))
    
    username_logado = session['username']
    
    conn = get_db()
    c = conn.cursor()
    
    # Busca todas as salas onde o usuário participa
    c.execute("""
        SELECT * FROM chat_rooms 
        WHERE user1 = ? OR user2 = ?
        ORDER BY created_at DESC
    """, (username_logado, username_logado))
    
    rooms = c.fetchall()
    conn.close()
    
    # Passamos os rooms e o username para o template
    return render_template("chats.html", chats=rooms, username=username_logado)

@app.route('/buscar_contas')
def buscar_contas():
    if 'username' not in session: return redirect(url_for('login'))
    
    query = request.args.get('q', '').strip()
    usuarios_encontrados = []
    
    if query:
        conn = get_db()
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        
        # Busca usuários que contenham o termo, ignorando o próprio usuário logado
        # Ajuste 'users' e 'username' conforme o nome da sua tabela/coluna
        c.execute("""
            SELECT username FROM users 
            WHERE username LIKE ? AND username != ?
            LIMIT 20
        """, (f'%{query}%', session['username']))
        
        usuarios_encontrados = c.fetchall()
        conn.close()
    
    return render_template('buscar_contas.html', 
                           usuarios=usuarios_encontrados, 
                           query=query)

@app.route('/iniciar_chat/<target_user>')
def iniciar__chat(target_user):
    if 'username' not in session: return redirect(url_for('login'))
    
    user1 = session['username']
    user2 = target_user
    
    # Cria um chat_id padronizado (sempre ordem alfabética para não duplicar)
    users = sorted([user1, user2])
    chat_id = f"chat_{users[0]}_{users[1]}"
    
    conn = get_db()
    c = conn.cursor()
    
    # Verifica se a sala de chat já existe, se não, cria
    c.execute("SELECT 1 FROM chat_rooms WHERE chat_id = ?", (chat_id,))
    if not c.fetchone():
        c.execute("INSERT INTO chat_rooms (chat_id, user1, user2) VALUES (?, ?, ?)", 
                  (chat_id, user1, user2))
        conn.commit()
    
    conn.close()
    
    # Redireciona para a rota que você já tem no app.py
    return redirect(url_for('chat_especifico', chat_id=chat_id))

@app.context_processor
def inject_user_settings():
    if 'username' in session:
        path = get_user_config_path(session['username'])
        if os.path.exists(path):
            with open(path, 'r') as f:
                return dict(user_settings=json.load(f))
    return dict(user_settings={'cor_fundo': '#f0f2f5', 'idade': '18'})

@app.route('/configs', methods=['GET', 'POST'])
def configs():
    if 'username' not in session: return redirect(url_for('login'))
    
    username = session['username']
    path = get_user_config_path(username)
    
    if request.method == 'POST':
        novas_configs = {
            'cor_fundo': request.form.get('cor_fundo'),
            'idade': request.form.get('idade'),
            'tema': request.form.get('tema')
        }
        with open(path, 'w') as f:
            json.dump(novas_configs, f)
        
        # Verifica se precisa de supervisão após salvar
        if precisa_supervisao(username) and not novas_configs.get('supervisao_ativa', False):
            flash("Modo infantil detectado! Configure a supervisão agora.")
            return redirect(url_for('supervisao_confirmar', etapa=1))  # Inicia o wizard na etapa 1
        
        flash("Configurações salvas!")
        return redirect(url_for('configs'))
    
    with open(path, 'r') as f:
        config_data = json.load(f)
    
    return render_template('configs.html', config=config_data)

@app.route('/sobre')
def sobre():
    return render_template('sobre.html')

# Listar todas as playlists do usuário logado (ou públicas)
@app.route('/playlists')
def playlists():
    if 'username' not in session:
        flash("Faça login para ver suas playlists.")
        return redirect(url_for('login'))
    
    username = session['username']
    conn = get_db()
    c = conn.cursor()
    
    # Minhas playlists + públicas de outros (opcional)
    c.execute("""
        SELECT id, title, description, is_public, created_at 
        FROM playlists 
        WHERE user_username = ? 
        ORDER BY updated_at DESC
    """, (username,))
    minhas_playlists = [dict(row) for row in c.fetchall()]
    
    conn.close()
    
    return render_template('playlists.html', 
                          minhas_playlists=minhas_playlists,
                          username=username)

# Criar nova playlist
@app.route('/criar-playlist', methods=['GET', 'POST'])
def criar_playlist():
    if 'username' not in session:
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        is_public = 1 if request.form.get('is_public') else 0
        
        if not title:
            flash("Dê um título para a playlist.")
            return redirect(url_for('criar_playlist'))
        
        playlist_id = uuid.uuid4().hex[:12]
        agora = datetime.now().isoformat()
        
        conn = get_db()
        c = conn.cursor()
        c.execute("""
            INSERT INTO playlists (id, user_username, title, description, is_public, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (playlist_id, session['username'], title, description, is_public, agora, agora))
        conn.commit()
        conn.close()
        
        flash("Playlist criada!")
        return redirect(url_for('playlist', playlist_id=playlist_id))
    
    return render_template('criar_playlist.html')

# Visualizar uma playlist específica
@app.route('/playlist/<playlist_id>')
def playlist(playlist_id):
    conn = get_db()
    c = conn.cursor()
    
    c.execute("SELECT * FROM playlists WHERE id = ?", (playlist_id,))
    playlist = c.fetchone()
    
    if not playlist:
        conn.close()
        return "Playlist não encontrada", 404
    
    playlist = dict(playlist)
    
    # Vídeos da playlist (com ordem)
    c.execute("""
        SELECT v.*, pi.position 
        FROM playlist_items pi
        JOIN videos v ON pi.video_id = v.id
        WHERE pi.playlist_id = ?
        ORDER BY pi.position ASC
    """, (playlist_id,))
    videos = [dict(row) for row in c.fetchall()]
    
    conn.close()
    
    is_dono = 'username' in session and playlist['user_username'] == session['username']
    
    return render_template('playlist.html',
                          playlist=playlist,
                          videos=videos,
                          is_dono=is_dono)

@app.route('/playlist/adicionar', methods=['POST'])
def adicionar_a_playlist():
    if 'username' not in session:
        return jsonify({'error': 'login necessário'}), 401
    
    playlist_id = request.form.get('playlist_id')
    video_id = request.form.get('video_id')
    
    if not playlist_id or not video_id:
        return jsonify({'error': 'dados incompletos'}), 400
    
    conn = get_db()
    c = conn.cursor()
    
    # Verifica se é dono
    c.execute("SELECT user_username FROM playlists WHERE id = ?", (playlist_id,))
    dono = c.fetchone()
    if not dono or dono['user_username'] != session['username']:
        conn.close()
        return jsonify({'error': 'sem permissão'}), 403
    
    # Verifica se vídeo já está na playlist
    c.execute("SELECT 1 FROM playlist_items WHERE playlist_id = ? AND video_id = ?", 
              (playlist_id, video_id))
    if c.fetchone():
        conn.close()
        return jsonify({'message': 'já está na playlist'})
    
    # Adiciona
    pos = datetime.now().isoformat()
    c.execute("""
        INSERT INTO playlist_items (playlist_id, video_id, position, added_at)
        VALUES (?, ?, (SELECT COALESCE(MAX(position), 0) + 1 FROM playlist_items WHERE playlist_id = ?), ?)
    """, (playlist_id, video_id, playlist_id, pos))
    
    # Atualiza updated_at da playlist
    c.execute("UPDATE playlists SET updated_at = ? WHERE id = ?", (pos, playlist_id))
    
    conn.commit()
    conn.close()
    
    return jsonify({'success': True, 'message': 'Adicionado à playlist!'})

@app.route('/supervisao-confirmar', methods=['GET', 'POST'])
def supervisao_confirmar():
    if 'username' not in session:
        flash("Você precisa estar logado para acessar esta página.")
        return redirect(url_for('login'))
    
    username = session['username']
    config_path = get_user_config_path(username)
    
    with open(config_path, 'r', encoding='utf-8') as f:
        configs = json.load(f)
    
    if not precisa_supervisao(username):
        flash("Sua conta não está em modo infantil. Não é necessária supervisão.")
        return redirect(url_for('configs'))
    
    if configs.get('supervisao_ativa', False):
        flash("A supervisão já foi ativada por um responsável.")
        return redirect(url_for('configs'))
    
    # Etapa atual (padrão 1)
    etapa = request.args.get('etapa', '1')
    
    # Armazena dados temporários na sessão (para multi-etapas)
    if 'supervisao_temp' not in session:
        session['supervisao_temp'] = {}
    
    if request.method == 'POST':
        acao = request.form.get('acao')
        if acao == 'cancelar':
            session.pop('supervisao_temp', None)  # Limpa dados temp
            flash("Configuração cancelada.")
            return redirect(url_for('configs'))
        
        # Processa cada etapa
        if etapa == '1':
            idade_corrigida = request.form.get('idade_corrigida')
            if idade_corrigida:
                configs['idade'] = idade_corrigida
                with open(config_path, 'w') as f:
                    json.dump(configs, f)
                flash("Idade corrigida! Verificando novamente...")
                if not precisa_supervisao(username):  # Se agora >11, sai
                    return redirect(url_for('configs'))
            
            # Upload foto opcional
            foto = request.files.get('foto_rosto')
            if foto:
                foto_path = os.path.join('users', username, 'foto_idade.jpg')
                foto.save(foto_path)
                session['supervisao_temp']['foto_salva'] = True
            
            return redirect(url_for('supervisao_confirmar', etapa=2))
        
        elif etapa == '2':
            # Etapa de info: só avança
            return redirect(url_for('supervisao_confirmar', etapa=3))
        
        elif etapa == '3':
            responsavel_username = request.form.get('responsavel_username', '').strip()
            senha_responsavel = request.form.get('senha_responsavel', '').strip()
    
            print(f"[DEBUG ETAPA 3] Username digitado: '{responsavel_username}' | Senha: '{senha_responsavel}'")
    
            if not responsavel_username or not senha_responsavel:
                flash("Preencha TODOS os campos: usuário e senha do responsável.", "error")
                print("[DEBUG ETAPA 3] Campos vazios")
                return redirect(url_for('supervisao_confirmar', etapa=3))
    
            conn = get_db()
            c = conn.cursor()
            c.execute("SELECT password FROM users WHERE username = ?", (responsavel_username,))
            user_data = c.fetchone()
            conn.close()
    
            if not user_data:
                flash(f"O usuário '{responsavel_username}' não existe no sistema.", "error")
                print(f"[DEBUG ETAPA 3] Usuário não encontrado: {responsavel_username}")
                return redirect(url_for('supervisao_confirmar', etapa=3))
    
            if user_data['password'] != senha_responsavel:
                flash("A senha do responsável está incorreta. Verifique e tente novamente.", "error")
                print(f"[DEBUG ETAPA 3] Senha incorreta para {responsavel_username}")
                return redirect(url_for('supervisao_confirmar', etapa=3))
    
            # Se chegou aqui → TUDO CERTO!
            session['supervisao_temp']['responsavel_username'] = responsavel_username
            session['supervisao_temp']['responsavel_confirmado'] = True
    
            print(f"[DEBUG ETAPA 3] SUCESSO! Dados salvos na sessão: {session['supervisao_temp']}")
    
            flash("Responsável validado! Avançando para a próxima etapa...", "success")
            return redirect(url_for('supervisao_confirmar', etapa=4))

        elif etapa == '4':
            classificacao = request.form.get('classificacao_maxima', '').strip()
    
            print(f"[DEBUG ETAPA 4] Valor recebido do select: '{classificacao}'")
    
            if not classificacao:
                flash("Selecione a classificação máxima de conteúdo permitida.", "error")
                print("[DEBUG ETAPA 4] Nenhum valor selecionado → voltou para etapa 4")
                return redirect(url_for('supervisao_confirmar', etapa=4))
    
            # Salva na sessão
            session['supervisao_temp']['classificacao_maxima'] = classificacao
    
            print(f"[DEBUG ETAPA 4] SUCESSO! Classificação salva na sessão: {session['supervisao_temp']}")
    
            flash("Classificação definida! Revise tudo na próxima etapa.", "success")
            return redirect(url_for('supervisao_confirmar', etapa=5))
        
        elif etapa == '5':
            # Confirma tudo
            if session.get('supervisao_temp', {}).get('responsavel_confirmado'):
                configs['supervisao_ativa'] = True
                configs['responsavel_username'] = f'@{session["supervisao_temp"]["responsavel_username"]}'
                configs['classificacao_maxima'] = session['supervisao_temp']['classificacao_maxima']
                configs['data_confirmacao'] = datetime.now().isoformat()
                
                # Salva as configurações
                with open(config_path, 'w', encoding='utf-8') as f:
                    json.dump(configs, f, ensure_ascii=False, indent=4)
                
                # Força recarregamento para evitar problemas de cache
                with open(config_path, 'r', encoding='utf-8') as f:
                    configs_atualizado = json.load(f)
                
                if configs_atualizado.get('supervisao_ativa', False):
                    flash("Supervisão ativada com sucesso! Agora você pode usar as funções liberadas.")
                else:
                    flash("Erro ao ativar supervisão. Verifique o arquivo de configuração.")
                
                session.pop('supervisao_temp', None)  # Limpa sessão
                return redirect(url_for('configs'))
            else:
                flash("Dados incompletos. Reinicie o processo.")
                return redirect(url_for('supervisao_confirmar', etapa=1))
    
    # GET: Renderiza a etapa atual
    return render_template('supervisao_confirmar.html',
                           etapa=etapa,
                           username=username,
                           configs=configs,
                           temp_data=session.get('supervisao_temp', {}))

# ================= conta ================ #

@app.route('/conta')
def conta():
    if 'username' not in session:
        flash("Faça login para acessar sua conta.")
        return redirect(url_for('login'))
    
    username = session['username']
    
    # Carrega configs do usuário
    config_path = get_user_config_path(username)
    configs = {}
    if os.path.exists(config_path):
        with open(config_path, 'r', encoding='utf-8') as f:
            configs = json.load(f)
    
    # Carrega infos do canal (se existir)
    channel = get_channel_info(username)
    
    # Verifica se tem studio.txt
    studio_link = None
    studio_path = os.path.join("users", username, "studio.txt")
    if os.path.exists(studio_path):
        with open(studio_path, "r", encoding="utf-8") as f:
            relative_path = f.read().strip()
        studio_link = f"http://192.168.0.150:7072/studio/{username}"  # ou use STUDIO_BASE_URL se definido
    
    return render_template('conta.html',
                           username=username,
                           configs=configs,
                           channel=channel,
                           studio_link=studio_link)

@app.route('/editar-video/<video_id>', methods=['GET', 'POST'])
def editar_video(video_id):
    if 'username' not in session:
        flash("Faça login para editar vídeos.")
        return redirect(url_for('login'))

    video = get_video(video_id)
    if not video:
        return "Vídeo não encontrado", 404

    # Verifica se o usuário é dono do canal do vídeo
    if video.get('channel') != session['username']:
        return "Você não tem permissão para editar este vídeo.", 403

    if request.method == 'POST':
        new_title = request.form.get('title')
        new_description = request.form.get('description')
        new_chapters = request.form.get('chapters')  # ex: "0:00 Introdução\n2:30 Parte 1\n..."

        conn = get_db()
        c = conn.cursor()
        c.execute("""
            UPDATE videos 
            SET title = ?, description = ?, subtitles = ?
            WHERE id = ?
        """, (new_title, new_description, new_chapters, video_id))
        conn.commit()
        conn.close()

        flash("Vídeo atualizado com sucesso!")
        return redirect(url_for('player', item_id=video_id))

    return render_template('editar_video.html', video=video)

@app.route('/api/videos')
def api_videos():
    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 12))
    offset = (page - 1) * per_page

    conn = get_db()
    c = conn.cursor()
    c.execute("""
        SELECT id, title, views, channel, thumb 
        FROM videos 
        ORDER BY views DESC 
        LIMIT ? OFFSET ?
    """, (per_page, offset))
    videos = [dict(r) for r in c.fetchall()]
    conn.close()

    return jsonify({
        'videos': videos,
        'static_url': STATIC_SERVER_URL
    })

# Run
if __name__ == '__main__':
    # run with eventlet recommended for socketio
    try:
        socketio.run(
        app,
        host="0.0.0.0",
        port=7070,
        debug=True,
        ssl_context=('192.168.0.150.pem', '192.168.0.150-key.pem')
    )
    except Exception:
        # fallback to flask dev server if socketio missing
        app.run(host="0.0.0.0", port=7070, debug=True, threaded=True, ssl_context=('192.168.0.150.pem', '192.168.0.150-key.pem'))
