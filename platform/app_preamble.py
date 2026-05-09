"""
AI Lending Company — Complete Application
Fully automated, AI-native personal lending platform.
Single-file Flask app with all routes, templates, and business logic.
"""

import sys, os, json, hashlib, uuid, logging, re, math
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path

UNDERWRITING_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'underwriting')
sys.path.insert(0, UNDERWRITING_DIR)

from flask import (Flask, request, jsonify, redirect, url_for,
                   render_template_string, make_response, session, g, flash)
import jwt

from config import Config
from models import get_db, init_db, audit_log

app = Flask(__name__)
app.config.from_object(Config)
app.secret_key = Config.SECRET_KEY

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("ai-lending")
init_db()

# ── Auth ──

def hash_password(password):
    salt = Config.JWT_SECRET[:16]
    return hashlib.sha256((salt + password).encode()).hexdigest()

def check_password(password, pw_hash):
    return hash_password(password) == pw_hash

def generate_jwt(uid, email, role='borrower'):
    return jwt.encode({
        'borrower_id': uid, 'email': email, 'role': role,
        'exp': datetime.now(timezone.utc) + timedelta(hours=24),
        'iat': datetime.now(timezone.utc), 'jti': uuid.uuid4().hex,
    }, Config.JWT_SECRET, algorithm='HS256')

def decode_jwt(token):
    try:
        return jwt.decode(token, Config.JWT_SECRET, algorithms=['HS256'])
    except:
        return None

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = session.get('token') or request.headers.get('Authorization', '').replace('Bearer ', '')
        payload = decode_jwt(token) if token else None
        if not payload:
            if request.is_json or request.path.startswith('/api/'):
                return jsonify({'error': 'auth_required'}), 401
            return redirect('/login')
        g.borrower_id = payload['borrower_id']
        g.email = payload['email']
        g.role = payload.get('role', 'borrower')
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = session.get('admin_token') or request.headers.get('Authorization', '').replace('Bearer ', '')
        payload = decode_jwt(token) if token else None
        if not payload or payload.get('role') != 'admin':
            if request.is_json: return jsonify({'error': 'admin_required'}), 403
            return redirect('/admin/login')
        return f(*args, **kwargs)
    return decorated

# ── Underwriting Engine ──

_loan_scorer = None
def get_scorer():
    global _loan_scorer
    if _loan_scorer is None:
        try:
            from scorer import LoanScorer
            _loan_scorer = LoanScorer(model_dir=UNDERWRITING_DIR)
            mp = os.path.join(UNDERWRITING_DIR, 'model_weights.json')
            if os.path.exists(mp):
                _loan_scorer.load(mp)
                log.info("Underwriting engine loaded")
        except Exception as e:
            log.error("Engine load failed: %s", e)
    return _loan_scorer
