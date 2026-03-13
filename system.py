# system.py
# Camadas de segurança centralizadas para o projeto Clippy
# Uso: from system import secure_app, configure_logging

import os
import json
import secrets
from datetime import datetime, timedelta
from flask import Flask, request, session, jsonify, abort, make_response
from flask_wtf.csrf import CSRFProtect
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.exceptions import BadRequest
import logging
from logging.handlers import RotatingFileHandler

BLOCKLIST_FILE = 'blocked_ips.json'
BLOCKED_IPS = set()  # Carregado dinamicamente

def load_blocked_ips():
    """Carrega IPs bloqueados de arquivo JSON ao iniciar"""
    global BLOCKED_IPS
    if os.path.exists(BLOCKLIST_FILE):
        try:
            with open(BLOCKLIST_FILE, 'r') as f:
                BLOCKED_IPS = set(json.load(f))
        except Exception as e:
            print(f"Erro ao carregar blocklist: {e}")
            BLOCKED_IPS = set()

def save_blocked_ips():
    """Salva IPs bloqueados em arquivo JSON"""
    try:
        with open(BLOCKLIST_FILE, 'w') as f:
            json.dump(list(BLOCKED_IPS), f)
    except Exception as e:
        print(f"Erro ao salvar blocklist: {e}")

def configure_logging(app: Flask):
    """Configura logging seguro com rotação e proteção contra flood"""
    if not os.path.exists('logs'):
        os.makedirs('logs')
    
    handler = RotatingFileHandler(
        'logs/clippy.log',
        maxBytes=10 * 1024 * 1024,  # 10 MB
        backupCount=5
    )
    handler.setLevel(logging.INFO)
    
    formatter = logging.Formatter(
        '[%(asctime)s] %(levelname)s in %(module)s: %(message)s '
        '(%(pathname)s:%(lineno)d)'
    )
    handler.setFormatter(formatter)
    
    app.logger.addHandler(handler)
    app.logger.setLevel(logging.INFO)
    
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    app.logger.addHandler(console_handler)

def secure_app(app: Flask):
    """
    Aplica configurações de segurança recomendadas para Flask.
    Deve ser chamado logo após criar a instância app = Flask(__name__)
    """
    # Carrega IPs bloqueados ao iniciar a aplicação
    load_blocked_ips()

    # =============================================
    # 1. Cabeçalhos de segurança HTTP obrigatórios
    # =============================================
    @app.after_request
    def apply_security_headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'SAMEORIGIN'
        response.headers['X-XSS-Protection'] = '1; mode=block'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        response.headers['frame-ancestors'] = "'self'"
        response.headers['Content-Security-Policy'] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "img-src 'self' data: https://192.168.0.150:7071; "
            "media-src 'self' https://192.168.0.150:7071; "
            "connect-src 'self'; "
            "frame-ancestors 'self'; "
            "form-action 'self'"
        )
        response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains; preload'
        response.headers['Permissions-Policy'] = (
            "geolocation=(), microphone=(), camera=(), payment=()"
        )
        return response

    # =============================================
    # 2. CSRF Protection (Flask-WTF)
    # =============================================
    csrf = CSRFProtect(app)

    # =============================================
    # 3. Limite de taxa (rate limiting básico)
    # =============================================
    rate_limit_store = {}

    @app.before_request
    def rate_limit():
        ip = request.remote_addr
        now = datetime.utcnow()
        
        if ip not in rate_limit_store:
            rate_limit_store[ip] = []
        
        # Remove entradas antigas (> 60 segundos)
        rate_limit_store[ip] = [t for t in rate_limit_store[ip] if now - t < timedelta(seconds=60)]
        
        # Máximo 60 requisições por minuto por IP
        if len(rate_limit_store[ip]) > 60:
            app.logger.warning(f"Rate limit exceeded for IP: {ip}")
            abort(429, description="Muitas requisições. Tente novamente mais tarde.")
        
        rate_limit_store[ip].append(now)

    # =============================================
    # 4. Bloqueio de IPs maliciosos (estático + dinâmico)
    # =============================================
    MANUAL_BLOCKLIST = {
        # Adicione IPs conhecidos aqui (exemplos fictícios)
        '45.79.123.45',
        '198.51.100.1',
    }

    @app.before_request
    def ip_block_check():
        ip = request.remote_addr
        
        # 1. Bloqueio manual (lista estática)
        if ip in MANUAL_BLOCKLIST:
            app.logger.warning(f"IP bloqueado pela lista manual: {ip} - Requisição: {request.path}")
            abort(403, description="Acesso negado: Endereço IP bloqueado por motivos de segurança.")
        
        # 2. Bloqueio dinâmico em endpoints sensíveis
        sensitive_paths = ['/login', '/cadastro', '/api/live/create', '/upload_video']
        if request.path in sensitive_paths:
            key = f"attempts:{ip}:{request.path}"
            attempts = session.get(key, 0)
            if attempts >= 5:  # Limite ajustável
                BLOCKED_IPS.add(ip)
                save_blocked_ips()
                app.logger.warning(f"IP {ip} bloqueado dinamicamente por excesso de tentativas em {request.path}")
                abort(403, description="Acesso temporariamente bloqueado por comportamento suspeito.")
            else:
                session[key] = attempts + 1
                session.modified = True

        # 3. Bloqueio permanente para IPs já na lista dinâmica
        if ip in BLOCKED_IPS:
            abort(403, description="Acesso negado: Endereço IP bloqueado por comportamento suspeito.")

    # =============================================
    # 5. Proteção contra uploads maliciosos
    # =============================================
    @app.before_request
    def validate_upload():
        if request.method == 'POST' and 'multipart/form-data' in request.headers.get('Content-Type', ''):
            for file_key in request.files:
                file = request.files[file_key]
                if file and file.filename:
                    forbidden_ext = {'.php', '.phtml', '.exe', '.bat', '.sh', '.js', '.jsp', '.asp'}
                    ext = os.path.splitext(file.filename)[1].lower()
                    if ext in forbidden_ext:
                        abort(400, "Tipo de arquivo não permitido")
                    
                    # Limita tamanho individual (além do global)
                    file_content = file.read()
                    if len(file_content) > 5 * 1024 * 1024 * 1024:
                        abort(413, "Arquivo muito grande")
                    file.seek(0)

    # =============================================
    # 6. Sessão segura
    # =============================================
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SECURE'] = True      # Requer HTTPS
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)

    # =============================================
    # 7. Proxy Fix
    # =============================================
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1, x_prefix=1)

    # =============================================
    # 8. Desabilita debug em produção
    # =============================================
    if os.getenv('FLASK_ENV') != 'development':
        app.config['DEBUG'] = False
        app.config['TESTING'] = False

    app.logger.info("Camadas de segurança aplicadas com sucesso.")