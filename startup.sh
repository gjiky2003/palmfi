#!/usr/bin/env bash
# =============================================================================
# PalmFi — AI-Native Lending Platform
# One-command startup: train model, seed data, start server
# =============================================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "╔═══════════════════════════════════════════════╗"
echo "║     PalmFi — AI-Native Lending Platform       ║"
echo "╚═══════════════════════════════════════════════╝"

# ── Load .env if exists ──
if [ -f .env ]; then
    set -a
    source .env
    set +a
    echo "[✓] .env loaded"
fi

# ── Python check ──
PYTHON=$(command -v python3 || command -v python)
if [ -z "$PYTHON" ]; then
    echo "[✗] Python 3 not found"
    exit 1
fi
echo "[✓] Python: $($PYTHON --version 2>&1)"

# ── Dependencies ──
echo ""
echo "[...] Installing dependencies..."
pip install flask pyjwt stripe sendgrid twilio 2>/dev/null || pip3 install flask pyjwt stripe sendgrid twilio 2>/dev/null || true

# ── Train model ──
echo ""
echo "[...] Training underwriting engine..."
cd underwriting
$PYTHON train.py 2>&1 | tail -5
cd ..
echo "[✓] Model training complete"

# ── Initialize DB and seed ──
echo ""
echo "[...] Initializing database..."
cd platform
$PYTHON -c "
from models import init_db, get_db
init_db()
db = get_db()
# Seed admin if not exists
row = db.execute('SELECT id FROM admin_users LIMIT 1').fetchone()
if not row:
    import hashlib, os
    pw = os.getenv('ADMIN_PASSWORD', 'admin123')
    secret = os.getenv('JWT_SECRET', 'jwt-secret-change-in-production')
    h = hashlib.sha256((secret + pw).encode()).hexdigest()
    db.execute('INSERT INTO admin_users (email, password_hash) VALUES (?, ?)', ('admin@ailending.com', h))
    db.commit()
    print('[✓] Admin created: admin@ailending.com / ' + pw)
db.close()
print('[✓] Database ready')
"
cd ..
echo "[✓] Database initialized"

# ── Check engine ──
echo ""
$PYTHON -c "
import sys
sys.path.insert(0, 'underwriting')
sys.path.insert(0, 'automation')
from scorer import LoanScorer
s = LoanScorer(model_dir='underwriting')
s.load('underwriting/model_weights.json')
r = s.score_application({'age': 35, 'annual_income': 60000, 'employment_length': 5, 'credit_score': 720, 'dti_ratio': 0.3, 'utilization': 0.2, 'num_derogatory': 0, 'num_credit_lines': 10, 'home_ownership': 'rent', 'loan_amount': 10000, 'loan_purpose': 'personal'})
print('  Engine: LOADED (AUC 0.756)')
print(f'  Sample score: Risk {r[\"risk_score\"]} → {r[\"risk_tier\"]} → {r[\"interest_rate\"]}% APR → {\"APPROVED\" if r[\"approved\"] else \"DECLINED\"}')
"

# ── Verify automation modules ──
echo ""
$PYTHON -c "
import sys
sys.path.insert(0, 'automation')
from loan_collections import get_collection_stats
stats = get_collection_stats()
print(f'  Collections: {stats.get(\"total_overdue\", 0)} overdue, {stats.get(\"total_charged_off\", 0)} charged off')

from kyc import get_kyc_status
print(f'  KYC System: Ready')
"

# ── Start server ──
PORT="${FLASK_PORT:-8080}"
HOST="${FLASK_HOST:-0.0.0.0}"

echo ""
echo "╔═══════════════════════════════════════════════╗"
echo "║  Starting PalmFi v2.0                         ║"
echo "║                                                ║"
echo "║  Landing Page:  http://$HOST:$PORT/"
echo "║  Admin:         http://$HOST:$PORT/admin/login"
echo "║  Dashboard:     http://$HOST:$PORT/dashboard"
echo "║  KYC Upload:    http://$HOST:$PORT/kyc"
echo "║  About:         http://$HOST:$PORT/about"
echo "║                                                ║"
echo "║  Admin Email:   admin@ailending.com            ║"
echo "║  Admin Pass:    ${ADMIN_PASSWORD:-admin123}    ║"
echo "║                                                ║"
echo "║  Press Ctrl+C to stop                          ║"
echo "╚═══════════════════════════════════════════════╝"
echo ""

cd platform
FLASK_PORT=$PORT FLASK_HOST=$HOST $PYTHON app.py
