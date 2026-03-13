# studio.py (servidor Flask independente para o Studio)

import os
import uuid
import subprocess
import sqlite3
import json
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash
from werkzeug.utils import secure_filename
from flask import current_app
from system import secure_app, configure_logging

# Configurações globais
STATIC_SERVER_URL = "https://192.168.0.150:7071/"  # Servidor estático separado
APP_BASE_URL = "https://192.168.0.150:7070/"       # URL do app principal
SQLITE_DB = r'D:\sqlite\app.db' if os.name == 'nt' else 'app.db'  # Banco compartilhado
UPLOAD_FOLDER = r'D:\cstatic\static\uploads' if os.name == 'nt' else 'static/uploads'
FFMPEG_PATH = r'D:\ffmpeg\bin\ffmpeg.exe' if os.name == 'nt' else 'ffmpeg'

# Cria o app Flask independente
studio_app = Flask(__name__)
studio_app.secret_key = 'chave-secreta-studio'
studio_app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
studio_app.config['MAX_CONTENT_LENGTH'] = int(5 * 1024 * 1024 * 1024)  # 5GB max
studio_app.config['FFMPEG_PATH'] = FFMPEG_PATH

# Garante pasta de uploads
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

#ego
from system import secure_app, configure_logging

#AURA
configure_logging(studio_app)
secure_app(studio_app)

# Função para configs do usuário (copiada para independência)
def get_user_config_path(username):
    user_folder = os.path.join('users', username)
    if not os.path.exists(user_folder):
        os.makedirs(user_folder)
    config_path = os.path.join(user_folder, 'configs.json')
    if not os.path.exists(config_path):
        default_configs = {
            'cor_fundo': '#f0f2f5',
            'idade': '18',
            'tema': 'claro'
        }
        with open(config_path, 'w') as f:
            json.dump(default_configs, f)
    return config_path
# Context processor para injetar user_settings (corrige o erro no template)
@studio_app.context_processor
def inject_user_settings():
    if 'username' in session:
        path = get_user_config_path(session['username'])
        if os.path.exists(path):
            with open(path, 'r') as f:
                return dict(user_settings=json.load(f))
    return dict(user_settings={'cor_fundo': '#f0f2f5', 'idade': '18'})

# Funções do banco (independentes)
def get_db():
    conn = sqlite3.connect(SQLITE_DB, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def get_channel_info(username):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM channels WHERE username = ?", (username,))
    r = c.fetchone()
    conn.close()
    return dict(r) if r else None

def load_videos():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM videos")
    rows = c.fetchall()
    videos = [dict(r) for r in rows]
    for v in videos:
        v['subtitles'] = json.loads(v['subtitles']) if v.get('subtitles') else []
    conn.close()
    return videos

def get_video(video_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM videos WHERE id = ?", (str(video_id),))
    row = c.fetchone()
    conn.close()
    if not row:
        return None
    v = dict(row)
    v['subtitles'] = json.loads(v['subtitles']) if v.get('subtitles') else []
    return v

def save_video_entry(video_entry):
    conn = get_db()
    c = conn.cursor()
    subtitles_json = json.dumps(video_entry.get('subtitles', []), ensure_ascii=False)
    c.execute("""
        INSERT OR REPLACE INTO videos (
            id, filename, filename_144p, filename_360p, filename_480p,
            title, description, views, channel, thumb,
            subtitles, status
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        video_entry['id'],
        video_entry.get('filename'),
        video_entry.get('filename_144p', ''),
        video_entry.get('filename_360p', ''),
        video_entry.get('filename_480p', ''),
        video_entry.get('title'),
        video_entry.get('description', ''),
        int(video_entry.get('views', 0)),
        video_entry.get('channel'),
        video_entry.get('thumb'),
        subtitles_json,
        video_entry.get('status', 'pendente')
    ))
    conn.commit()
    conn.close()

def create_channel_record(username, display_name, bio, password, foto_path=None):
    conn = get_db()
    c = conn.cursor()
    c.execute("""
        INSERT OR REPLACE INTO channels (username, display_name, bio, password, foto_path) VALUES (?, ?, ?, ?, ?)
    """, (username, display_name, bio, password, foto_path))
    conn.commit()
    conn.close()

def verify_channel_password(senha_digitada, senha_salva):
    return senha_digitada == senha_salva

# --- Rotas do Studio (com prefixo /studio/<username> onde faz sentido) ---

@studio_app.route('/create', methods=['GET', 'POST'])
def create_channel():
    if request.method == 'POST':
        username = request.form.get('username').strip()
        display_name = request.form.get('display_name').strip()
        bio = request.form.get('bio').strip()
        password = request.form.get('password', 'admin').strip()
        foto = request.files.get('foto')

        if not all([username, display_name, bio]):
            return 'Todos os campos são obrigatórios', 400

        channel_path = os.path.join('channels', f'@{username}')
        if os.path.exists(channel_path):
            return 'Este canal já existe', 409
        os.makedirs(channel_path, exist_ok=True)

        # Salva info.txt para compatibilidade
        info_path = os.path.join(channel_path, 'info.txt')
        with open(info_path, 'w', encoding='utf-8') as f:
            f.write(f"{display_name}\n{bio}\n")

        foto_path = None
        if foto and foto.filename != '':
            foto_path = os.path.join(channel_path, "foto.jpg")
            foto.save(foto_path)

        # Salva no banco
        create_channel_record(username, display_name, bio, password, foto_path)

        return redirect(url_for('studio', username=username))

    return render_template('create.html')

@studio_app.route('/studio/<username>')
def studio(username):
    ch = get_channel_info(username)
    if not ch:
        return 'Canal não encontrado', 404
    display_name = ch.get('display_name', username)
    bio = ch.get('bio', '')

    videos = [v for v in load_videos() if v.get('channel') == username]
    total_views = sum(int(v.get('views', 0)) for v in videos)
    total_videos = len(videos)

    # Contagem de subscribers
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) AS cnt FROM subscribers WHERE channel = ?", (username,))
    subscribers = c.fetchone()['cnt']
    conn.close()

    # Collabs
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT video_id, name, role, status FROM collabs WHERE channel = ?", (username,))
    collabs_rows = c.fetchall()
    conn.close()
    collabs_data = {}
    for r in collabs_rows:
        collabs_data.setdefault(r['video_id'], []).append(dict(r))

    return render_template('studio.html',
                           username=username,
                           display_name=display_name,
                           bio=bio,
                           channel_videos=videos,
                           total_views=total_views,
                           total_videos=total_videos,
                           subscribers=subscribers,
                           collabs_data=collabs_data)

@studio_app.route('/upload', methods=['GET', 'POST'])
def studio_mobile_upload(username):
    if request.method == 'POST':
        senha_digitada = request.form.get('password')
        ch = get_channel_info(username)
        if not ch:
            return 'Canal não encontrado', 404
        if not verify_channel_password(senha_digitada, ch.get('password', '')):
            return 'Senha do canal incorreta', 403

        title = request.form.get('title')
        description = request.form.get('description')
        video_file = request.files.get('video')
        thumb_file = request.files.get('thumb')

        if not video_file or not title:
            return 'Título e vídeo são obrigatórios', 400

        upload_folder = current_app.config['UPLOAD_FOLDER']
        
        filename = secure_filename(video_file.filename)
        unique_name = f"{uuid.uuid4().hex[:8]}_{filename}"
        video_path = os.path.join(upload_folder, unique_name)
        video_file.save(video_path)

        # Thumbnail automática
        thumb_filename = f"thumb_{os.path.splitext(unique_name)[0]}.jpg"
        thumb_path = os.path.join(upload_folder, thumb_filename)
        ffmpeg_path = current_app.config.get('FFMPEG_PATH', 'ffmpeg')
        try:
            subprocess.run([
                ffmpeg_path, '-i', video_path, '-ss', '00:00:01', '-vframes', '1', thumb_path
            ], check=True)
        except Exception as e:
            print("Erro ao gerar thumb:", e)
            thumb_filename = 'default_thumb.jpg'

        # Thumb manual
        if thumb_file and thumb_file.filename != '':
            thumb_filename = f"thumb_manual_{uuid.uuid4().hex[:5]}.jpg"
            thumb_file.save(os.path.join(upload_folder, thumb_filename))

        # Transcodes (144p, 360p, 480p)
        filename_144p = f'144p_{unique_name}'
        video_path_144p = os.path.join(upload_folder, filename_144p)
        try:
            subprocess.run([ffmpeg_path, '-i', video_path, '-vf', 'scale=256:-2', '-c:v', 'libx264', '-preset', 'fast',
                            '-crf', '28', '-c:a', 'aac', '-b:a', '64k', video_path_144p], check=True)
        except Exception as e:
            print("Erro 144p:", e)
            filename_144p = ''

        filename_360p = f'360p_{unique_name}'
        video_path_360p = os.path.join(upload_folder, filename_360p)
        try:
            subprocess.run([ffmpeg_path, '-i', video_path, '-vf', 'scale=640:-2', '-c:v', 'libx264', '-preset', 'fast',
                            '-crf', '25', '-c:a', 'aac', '-b:a', '96k', video_path_360p], check=True)
        except Exception as e:
            print("Erro 360p:", e)
            filename_360p = ''

        filename_480p = f'480p_{unique_name}'
        video_path_480p = os.path.join(upload_folder, filename_480p)
        try:
            subprocess.run([ffmpeg_path, '-i', video_path, '-vf', 'scale=854:-2', '-c:v', 'libx264', '-preset', 'fast',
                            '-crf', '23', '-c:a', 'aac', '-b:a', '128k', video_path_480p], check=True)
        except Exception as e:
            print("Erro 480p:", e)
            filename_480p = ''

        video_id = uuid.uuid4().hex[:10]
        video_entry = {
            'id': video_id,
            'filename': unique_name,
            'filename_144p': filename_144p,
            'filename_360p': filename_360p,
            'filename_480p': filename_480p,
            'title': title,
            'description': description,
            'views': 0,
            'channel': username,
            'thumb': thumb_filename,
            'subtitles': [],
            'status': 'pendente'
        }
        
        save_video_entry(video_entry)
        
        return redirect(f'/lang=mobile/video/{video_id}')

    return render_template('studio_mobile.html', username=username)

@studio_app.route('/studio/<username>/upload_video', methods=['POST'])
def upload_video(username):
    senha_digitada = request.form.get('password')
    ch = get_channel_info(username)
    if not ch:
        return 'Canal não encontrado', 404
    if not verify_channel_password(senha_digitada, ch.get('password', '')):
        return 'Senha do canal incorreta', 403

    title = request.form.get('title')
    description = request.form.get('description')
    video = request.files.get('video')
    thumb = request.files.get('thumb')

    if not all([title, description, video]):
        return 'Dados incompletos', 400

    # Use o objeto app diretamente (studio_app)
    upload_folder = studio_app.config['UPLOAD_FOLDER']
    ffmpeg_path = studio_app.config.get('FFMPEG_PATH', 'ffmpeg')

    filename = secure_filename(video.filename)
    video_path = os.path.join(upload_folder, filename)
    video.save(video_path)

    # Thumbnail automática
    thumb_filename = f"thumb_{os.path.splitext(filename)[0]}.jpg"
    thumb_path = os.path.join(upload_folder, thumb_filename)
    try:
        subprocess.run([ffmpeg_path, '-i', video_path, '-ss', '00:00:01', '-vframes', '1', thumb_path], check=True)
    except Exception as e:
        print("Erro ao gerar thumb:", e)
        thumb_filename = ''

    # Thumb manual
    if thumb and thumb.filename != '':
        thumb_filename = 'thumb_' + secure_filename(thumb.filename)
        thumb.save(os.path.join(upload_folder, thumb_filename))

    # Transcodes (144p, 360p, 480p)
    filename_144p = f'144p_{filename}'
    video_path_144p = os.path.join(upload_folder, filename_144p)
    try:
        subprocess.run([ffmpeg_path, '-i', video_path, '-vf', 'scale=256:-2', '-c:v', 'libx264', '-preset', 'fast',
                        '-crf', '28', '-c:a', 'aac', '-b:a', '64k', video_path_144p], check=True)
    except Exception as e:
        print("Erro 144p:", e)
        filename_144p = ''

    filename_360p = f'360p_{filename}'
    video_path_360p = os.path.join(upload_folder, filename_360p)
    try:
        subprocess.run([ffmpeg_path, '-i', video_path, '-vf', 'scale=640:-2', '-c:v', 'libx264', '-preset', 'fast',
                        '-crf', '25', '-c:a', 'aac', '-b:a', '96k', video_path_360p], check=True)
    except Exception as e:
        print("Erro 360p:", e)
        filename_360p = ''

    filename_480p = f'480p_{filename}'
    video_path_480p = os.path.join(upload_folder, filename_480p)
    try:
        subprocess.run([ffmpeg_path, '-i', video_path, '-vf', 'scale=854:-2', '-c:v', 'libx264', '-preset', 'fast',
                        '-crf', '23', '-c:a', 'aac', '-b:a', '128k', video_path_480p], check=True)
    except Exception as e:
        print("Erro 480p:", e)
        filename_480p = ''

    vid = uuid.uuid4().hex[:10]
    video_entry = {
        'id': vid,
        'filename': filename,
        'filename_144p': filename_144p,
        'filename_360p': filename_360p,
        'filename_480p': filename_480p,
        'title': title,
        'description': description,
        'views': 0,
        'channel': username,
        'thumb': thumb_filename,
        'subtitles': [],
        'status': 'pendente'
    }
    save_video_entry(video_entry)

    return redirect(url_for('studio', username=username))

@studio_app.route('/trocar_foto', methods=['POST'])
def trocar_foto(username):
    senha_digitada = request.form.get('password')
    ch = get_channel_info(username)
    if not ch:
        return "Canal não encontrado.", 404
    if not verify_channel_password(senha_digitada, ch.get('password', '')):
        return "Senha incorreta.", 403

    foto = request.files.get('nova_foto')
    if not foto:
        return "Nenhuma imagem enviada.", 400

    channel_dir = os.path.join("channels", f"@{username}")
    foto_path = os.path.join(channel_dir, "foto.jpg")
    foto.save(foto_path)

    create_channel_record(username, ch.get('display_name', username), ch.get('bio', ''), ch.get('password', ''), foto_path)

    return redirect(url_for('studio', username=username))

@studio_app.route('/request_collab', methods=['POST'])
def request_collab():
    video_id = request.form.get('video_id')
    channel = request.form.get('channel')
    name = request.form.get('name')
    role = request.form.get('role')
    username_form = request.form.get('username')  # optional

    if not all([video_id, channel, name, role]):
        return 'Dados incompletos', 400

    conn = get_db()
    c = conn.cursor()

    vid = get_video(video_id)
    title = vid.get('title') if vid else "Título desconhecido"

    c.execute("INSERT INTO collabs (video_id, video_title, channel, name, role, status) VALUES (?, ?, ?, ?, ?, ?)",
              (video_id, title, channel, name, role, "pedido"))

    conn.commit()
    conn.close()

    return 'Pedido de colaboração registrado com sucesso'

@studio_app.route('/studio/<username>/posts', methods=['GET', 'POST'])
def studio_posts(username):
    conn = get_db()
    c = conn.cursor()

    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'create':
            title = request.form.get('title')
            content = request.form.get('content')
            date = datetime.now().strftime("%d/%m/%Y")
            post_id = str(uuid.uuid4())[:8]
            c.execute("INSERT INTO posts (id, channel, title, content, date) VALUES (?, ?, ?, ?, ?)",
                      (post_id, username, title, content, date))
        elif action == 'delete':
            post_id = request.form.get('post_id')
            c.execute("DELETE FROM posts WHERE id = ?", (post_id,))
        conn.commit()

    c.execute("SELECT id, title, content, date FROM posts WHERE channel = ?", (username,))
    posts = [dict(r) for r in c.fetchall()]
    conn.close()

    return render_template('studio_posts.html', username=username, posts=posts)

@studio_app.route('/delete_video/<video_id>', methods=['POST'])
def delete_video(video_id):
    username = session.get('username')
    if not username:
        return "Não logado", 403

    video = get_video(video_id)
    if not video or video.get('channel') != username:
        return "Vídeo não encontrado ou não pertence ao canal", 404

    conn = get_db()
    c = conn.cursor()
    c.execute("DELETE FROM videos WHERE id = ?", (str(video_id),))
    conn.commit()
    conn.close()

    upload_folder = current_app.config['UPLOAD_FOLDER']
    for fname in [video.get('filename'), video.get('filename_144p'), video.get('filename_360p'), video.get('filename_480p')]:
        if fname:
            path = os.path.join(upload_folder, fname)
            if os.path.exists(path):
                os.remove(path)

    return redirect(url_for('studio', username=username))

@studio_app.route('/api/collab/gerenciar', methods=['POST'])
def api_gerenciar_collab():
    username = session.get('username')
    if not username:
        return jsonify({'error': 'Não autorizado'}), 403

    action = request.form.get('action')
    collab_id = request.form.get('collab_id')

    conn = get_db()
    c = conn.cursor()

    c.execute("SELECT channel FROM collabs WHERE id = ?", (collab_id,))
    row = c.fetchone()

    if not row or row['channel'] != username:
        conn.close()
        return jsonify({'error': 'Acesso negado ou collab não encontrada'}), 403

    if action == 'aceitar':
        c.execute("UPDATE collabs SET status = 'aceito' WHERE id = ?", (collab_id,))
    elif action in ['rejeitar', 'remover']:
        c.execute("DELETE FROM collabs WHERE id = ?", (collab_id,))

    conn.commit()
    conn.close()

    return redirect(url_for('gerenciar_collabs', username=username))

@studio_app.route('/studio/<username>/collabs')
def gerenciar_collabs(username):
    conn = get_db()
    c = conn.cursor()

    c.execute("""
        SELECT * FROM collabs 
        WHERE channel = ? 
        ORDER BY status DESC, id DESC
    """, (username,))
    all_collabs = [dict(r) for r in c.fetchall()]
    conn.close()

    pedidos = [c for c in all_collabs if c['status'] == 'pedido']
    ativos = [c for c in all_collabs if c['status'] == 'aceito']

    return render_template("collabs.html", username=username, pedidos=pedidos, ativos=ativos)

if __name__ == '__main__':
    studio_app.run(host="0.0.0.0", port=7072, debug=True, ssl_context=('192.168.0.150.pem', '192.168.0.150-key.pem'))  # Porta separada para independência