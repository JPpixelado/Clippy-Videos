import os
from flask import Blueprint, render_template, request, redirect, url_for, session, abort, flash
import sqlite3
from datetime import datetime

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

def get_db():
    # Reutilize a mesma função do app principal
    conn = sqlite3.connect('D:\\sqlite\\app.db' if os.name == 'nt' else 'app.db', check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

@admin_bp.before_request
def check_admin():
    """Verifica se o usuário logado é admin"""
    if session.get('username') != 'p1xelado':  # Ajuste para o seu admin real
        abort(403)

@admin_bp.route('/')
def dashboard():
    conn = get_db()
    c = conn.cursor()
    
    # Vídeos
    c.execute("""
        SELECT id, title, channel, status, classificacao 
        FROM videos 
        ORDER BY id DESC
    """)
    videos = [dict(row) for row in c.fetchall()]
    
    # Usuários
    c.execute("""
        SELECT username, nome, email 
        FROM users 
        ORDER BY username
    """)
    users = [dict(row) for row in c.fetchall()]
    
    conn.close()
    
    return render_template('admin_dashboard.html', videos=videos, users=users)

@admin_bp.route('/delete_video/<video_id>', methods=['POST'])
def delete_video(video_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("DELETE FROM videos WHERE id = ?", (video_id,))
    conn.commit()
    conn.close()
    flash("Vídeo excluído com sucesso!")
    return redirect(url_for('admin.dashboard'))

@admin_bp.route('/block_video/<video_id>', methods=['POST'])
def block_video(video_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE videos SET status = 'bloqueado' WHERE id = ?", (video_id,))
    conn.commit()
    conn.close()
    flash("Vídeo bloqueado!")
    return redirect(url_for('admin.dashboard'))

@admin_bp.route('/unblock_video/<video_id>', methods=['POST'])
def unblock_video(video_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE videos SET status = 'pendente' WHERE id = ?", (video_id,))
    conn.commit()
    conn.close()
    flash("Vídeo desbloqueado!")
    return redirect(url_for('admin.dashboard'))

@admin_bp.route('/delete_user/<username>', methods=['POST'])
def delete_user(username):
    if username == 'p1xelado':
        flash("Não é possível excluir o admin principal!", "error")
        return redirect(url_for('admin.dashboard'))
    
    conn = get_db()
    c = conn.cursor()
    c.execute("DELETE FROM users WHERE username = ?", (username,))
    conn.commit()
    conn.close()
    
    flash(f"Usuário @{username} excluído!")
    return redirect(url_for('admin.dashboard'))

@admin_bp.route('/editar_classificacao/<video_id>', methods=['GET', 'POST'])
def editar_classificacao(video_id):
    conn = get_db()
    c = conn.cursor()
    
    if request.method == 'POST':
        nova_class = request.form.get('classificacao')
        if nova_class in ['L', '10', 'A10', '12', 'A12', '14', 'A14', '16', 'A16', '18', 'A18']:
            c.execute("UPDATE videos SET classificacao = ? WHERE id = ?", (nova_class, video_id))
            conn.commit()
            flash(f"Classificação atualizada para {nova_class}")
        else:
            flash("Classificação inválida.", "error")
        conn.close()
        return redirect(url_for('admin.dashboard'))
    
    c.execute("SELECT id, title, classificacao FROM videos WHERE id = ?", (video_id,))
    video = c.fetchone()
    conn.close()
    
    if not video:
        abort(404)
    
    return render_template('admin_editar_classificacao.html', video=dict(video))