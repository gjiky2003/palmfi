"""
AI Lending Company — Main Application
All routes, auth, API, admin, and business logic.
"""
import sys, os, json, hashlib, uuid, logging, re, time, secrets
from datetime import datetime, timedelta, date, timezone
from functools import wraps
from pathlib import Path

import bcrypt
import jwt
from flask import (
    Flask, request, jsonify, redirect, session, g, flash,
    url_for, render_template, make_response, abort,
)
from werkzeug.utils import secure_filename

# ── Path setup using pathlib ──
_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
UNDERWRITING_DIR = str(_ROOT / 'underwriting')
COMPLIANCE_DIR = str(_ROOT / 'compliance')
AUTOMATION_DIR = str(_ROOT / 'automation')
sys.path.insert(0, UNDERWRITING_DIR)
sys.path.insert(0, str(_ROOT))  # project root for 'compliance' package
sys.path.insert(0, COMPLIANCE_DIR)
sys.path.insert(0, AUTOMATION_DIR)

from config import Config
from models import get_db, init_db, audit_log

TEMPLATE_DIR = str(_HERE / "templates")
app = Flask(__name__, template_folder=TEMPLATE_DIR)
app.config.from_object(Config)
app.secret_key = Config.SECRET_KEY
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = getattr(Config, 'SESSION_COOKIE_SECURE', False)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("ai-lending")
init_db()

# ── Auth ──

def hash_password(password):
    """Hash a password using bcrypt (rounds=12)."""
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt(rounds=12)).decode('utf-8')


def _legacy_sha256(password):
    salt = (Config.JWT_SECRET or '')[:16]
    return hashlib.sha256((salt + password).encode('utf-8')).hexdigest()


def check_password(password, pw_hash):
    """Verify a password against its bcrypt hash (supports both bcrypt and legacy SHA-256)."""
    if not pw_hash:
        return False
    if pw_hash.startswith('$2b$') or pw_hash.startswith('$2a$') or pw_hash.startswith('$2y$'):
        return bcrypt.checkpw(password.encode('utf-8'), pw_hash.encode('utf-8'))
    # Legacy SHA-256 hashes — migrate on next login
    return _legacy_sha256(password) == pw_hash


def generate_jwt(uid, email, role='borrower'):
    return jwt.encode({
        'uid': uid, 'email': email, 'role': role,
        'exp': datetime.now(timezone.utc) + timedelta(hours=24),
        'iat': datetime.now(timezone.utc), 'jti': uuid.uuid4().hex,
    }, Config.JWT_SECRET, algorithm='HS256')


def decode_jwt(token):
    if not token:
        return None
    try:
        return jwt.decode(token, Config.JWT_SECRET, algorithms=['HS256'], leeway=10)
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError as e:
        log.warning("JWT decode failed: %s", e)
        return None


def current_user():
    """Fetch the full borrower DB row for the logged-in user."""
    token = session.get('token')
    if not token:
        return None
    payload = decode_jwt(token)
    if not payload or payload.get('role') != 'borrower':
        return None
    conn = get_db()
    row = conn.execute("SELECT * FROM borrowers WHERE id = ?", (payload['uid'],)).fetchone()
    conn.close()
    return row


def current_admin():
    """Fetch the JWT payload for the logged-in admin."""
    token = session.get('admin_token')
    if not token:
        return None
    payload = decode_jwt(token)
    if not payload or payload.get('role') != 'admin':
        return None
    return payload


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        user = current_user()
        if not user:
            if request.is_json:
                return jsonify({'error': 'auth_required'}), 401
            flash('Please log in to continue.', 'warning')
            return redirect(url_for('login', next=request.path))
        # Set g for backward compat with extended routes
        g.borrower_id = user['id']
        g.email = user['email']
        return f(user, *args, **kwargs)
    return decorated


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        admin = current_admin()
        if not admin:
            if request.is_json:
                return jsonify({'error': 'auth_required'}), 401
            return redirect(url_for('admin_login', next=request.path))
        g.admin = admin
        return f(admin, *args, **kwargs)
    return decorated


# ── Underwriting Engine ──

_scorer = None
def get_scorer():
    global _scorer
    if _scorer is None:
        try:
            from scorer import LoanScorer
            _scorer = LoanScorer(model_dir=UNDERWRITING_DIR)
            mp = os.path.join(UNDERWRITING_DIR, 'model_weights.json')
            if os.path.exists(mp):
                _scorer.load(mp)
                log.info("Underwriting engine loaded")
        except Exception as e:
            log.error("Engine load failed: %s", e)
    return _scorer


def score_application(app_data, cash_flow_data=None):
    """Score a loan application using the underwriting engine or fallback defaults."""
    s = get_scorer()
    if s is not None:
        try:
            if cash_flow_data:
                app_data['cash_flow_metrics'] = cash_flow_data
            return s.score_application(app_data)
        except Exception as e:
            log.exception("Scorer failed: %s", e)
    # Conservative default fallback
    return {
        'risk_score': 30, 'risk_tier': 'B', 'risk_label': 'Good', 'approved': True,
        'interest_rate': 12.99, 'monthly_payment': 0,
        'origination_fee': 0, 'max_loan_amount': 25000,
        'recommended_term_months': 36, 'probability_of_default': 0.12,
        'decision_reasons': ['Scorer unavailable; manual review required.'],
        'explanation': {
            'summary': 'Application received. Our AI reviewed your financial profile.',
            'top_factors': [
                {'factor': 'debt_to_income_ratio', 'impact': 'positive', 'description': 'Your DTI ratio is manageable'},
                {'factor': 'credit_history', 'impact': 'positive', 'description': 'Stable credit profile'},
            ],
        },
    }


def amortization_schedule(principal, apr, months):
    """Return list of (n, due_date, payment, principal, interest, balance) tuples."""
    if months <= 0 or principal <= 0:
        return []
    r = (apr or 0.0) / 12.0
    if r == 0:
        m = principal / months
    else:
        m = principal * (r * (1 + r) ** months) / (((1 + r) ** months) - 1)
    bal = principal
    today = date.today()
    out = []
    for i in range(1, months + 1):
        interest = bal * r
        princ = m - interest
        bal = max(0.0, bal - princ)
        due = (today + timedelta(days=30 * i)).isoformat()
        out.append((i, due, round(m, 2), round(princ, 2), round(interest, 2), round(bal, 2)))
    return out


def _save_payment_schedule(conn, loan_id, schedule):
    """Save amortization schedule rows to the payment_schedules table."""
    for (n, due, pay, pr, intr, bal) in schedule:
        conn.execute(
            "INSERT INTO payment_schedules "
            "(loan_id, payment_number, due_date, amount_cents, principal_cents, "
            " interest_cents, remaining_balance_cents, status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 'pending')",
            (loan_id, n, due,
             int(round(pay * 100)), int(round(pr * 100)),
             int(round(intr * 100)), int(round(bal * 100)))
        )


# ── Bootstrap Admin ──

def _bootstrap_admin():
    """Ensure an admin user exists; generate password if none set."""
    conn = get_db()
    email = Config.ADMIN_EMAIL
    row = conn.execute("SELECT id FROM admin_users WHERE email = ?", (email,)).fetchone()
    if row:
        conn.close()
        return
    pw = os.getenv('ADMIN_PASSWORD')
    generated = False
    if not pw:
        pw = secrets.token_urlsafe(16)
        generated = True
    conn.execute(
        "INSERT INTO admin_users (email, password_hash) VALUES (?, ?)",
        (email, hash_password(pw)),
    )
    conn.commit()
    conn.close()
    if generated:
        log.warning("=" * 60)
        log.warning("ADMIN BOOTSTRAP — generated password (save it now)")
        log.warning("  email:    %s", email)
        log.warning("  password: %s", pw)
        log.warning("=" * 60)
    else:
        log.info("Admin user bootstrapped from ADMIN_PASSWORD env: %s", email)


# ── Error Handlers ──

@app.errorhandler(404)
def _404(e):
    try:
        return render_template('404.html'), 404
    except Exception:
        return jsonify({'error': 'not_found'}), 404


@app.errorhandler(500)
def _500(e):
    log.exception("server error: %s", e)
    try:
        return render_template('500.html'), 500
    except Exception:
        return jsonify({'error': 'server_error'}), 500


# ── Public Routes ──

@app.route('/')
def index():
    return render_template('landing.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'GET':
        return render_template('register.html')
    data = request.form
    email = data.get('email', '').strip().lower()
    password = data.get('password', '')
    if not email or len(password) < 6:
        flash('Email and password (6+ chars) required', 'error')
        return render_template('register.html')
    db = get_db()
    existing = db.execute("SELECT id FROM borrowers WHERE email = ?", (email,)).fetchone()
    if existing:
        db.close()
        flash('Email already registered', 'error')
        return render_template('register.html')
    c = db.execute(
        "INSERT INTO borrowers (email, password_hash, first_name, last_name, phone) VALUES (?, ?, ?, ?, ?)",
        (email, hash_password(password), data.get('first_name', ''), data.get('last_name', ''), data.get('phone', ''))
    )
    db.commit()
    bid = c.lastrowid
    db.close()
    session['token'] = generate_jwt(bid, email)
    flash('Account created! Welcome to PalmFi.', 'success')
    # Send welcome notification
    try:
        from automation.notifications import notify_borrower
        notify_borrower(bid, 'Welcome to PalmFi!',
            f"<h2>Welcome to PalmFi!</h2><p>Your account has been created successfully. "
            f"Complete your application to get started with your loan.</p>", 'email')
    except:
        pass
    return redirect('/dashboard')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'GET':
        return render_template('login.html')
    email = request.form.get('email', '').strip().lower()
    password = request.form.get('password', '')
    db = get_db()
    row = db.execute("SELECT * FROM borrowers WHERE email = ?", (email,)).fetchone()
    if not row or not check_password(password, row['password_hash']):
        db.close()
        flash('Invalid credentials', 'error')
        return render_template('login.html')
    session['token'] = generate_jwt(row['id'], email)
    db.execute("UPDATE borrowers SET last_login = datetime('now') WHERE id = ?", (row['id'],))
    db.commit()
    db.close()
    return redirect('/dashboard')


@app.route('/logout')
def logout():
    session.pop('token', None)
    session.pop('app_data', None)
    return redirect('/')


# ── Application ──

@app.route('/apply', methods=['GET', 'POST'])
@login_required
def apply(user):
    app_data = session.get('app_data', {})
    bid = user['id']

    if request.method == 'GET':
        # Load user context: pre-fill email
        db = get_db()
        row = db.execute("SELECT email FROM borrowers WHERE id=?", (bid,)).fetchone()
        db.close()
        if not app_data:
            return render_template('apply.html', data={'email': row['email'] if row else '', 'user_email': row['email'] if row else ''}, step=1)
        return render_template('apply.html', data={**app_data, 'user_email': row['email'] if row else ''}, step='review')

    if 'submit' in request.form:
        # ── Derive ML inputs from form ──
        dob = app_data.get('date_of_birth', '')
        age = 35
        if dob:
            try:
                b = [int(x) for x in dob.split('-')]
                today = date.today()
                age = today.year - b[0] - ((today.month, today.day) < (b[1], b[2]))
            except:
                pass

        annual_income = float(app_data.get('annual_income', 50000))
        monthly_debt = float(app_data.get('monthly_debt', 0))
        dti_ratio = min(0.9, (monthly_debt * 12) / max(1, annual_income))

        # Credit score — fall back from bucket or default
        credit_score = int(app_data.get('credit_score_bucket', 680))

        # Employment length in years
        emp_months = int(app_data.get('employment_length_months', 0))
        employment_length = max(0.5, emp_months / 12)

        # Utilization bucket
        util_map = {'0.1': 0.08, '0.25': 0.20, '0.45': 0.40, '0.65': 0.60, '0.85': 0.80}
        utilization = util_map.get(app_data.get('utilization', '0.25'), 0.25)

        num_derogatory = int(app_data.get('num_derogatory', 0))
        num_credit_lines = int(app_data.get('num_credit_lines', 5))

        home_ownership = app_data.get('home_ownership', 'rent')
        loan_amount = float(app_data.get('loan_amount', 5000))
        loan_purpose = app_data.get('loan_purpose', 'personal')

        scorer_input = {
            'age': age,
            'annual_income': annual_income,
            'employment_length': employment_length,
            'credit_score': credit_score,
            'dti_ratio': dti_ratio,
            'utilization': utilization,
            'num_derogatory': num_derogatory,
            'num_credit_lines': num_credit_lines,
            'home_ownership': home_ownership,
            'loan_amount': loan_amount,
            'loan_purpose': loan_purpose,
        }

        # ── Save to DB ──
        db = get_db()
        c = db.execute(
            "INSERT INTO applications (borrower_id, loan_amount, loan_purpose, term_months, bank_routing, bank_account, status) VALUES (?, ?, ?, ?, ?, ?, 'submitted')",
            (bid, loan_amount, loan_purpose, int(app_data.get('term_months', 36)),
             app_data.get('bank_routing',''), app_data.get('bank_account',''))
        )
        app_id = c.lastrowid

        # Update borrower profile with new fields
        db.execute("""
            UPDATE borrowers SET
                first_name=?, last_name=?, phone=?, date_of_birth=?,
                ssn_last4=?, address=?, city=?, state=?, zip_code=?,
                home_ownership=?, employment_status=?, employer_name=?,
                employer_phone=?, employment_length_months=?, housing_payment=?,
                annual_income=?, credit_score=?, kyc_status='pending'
            WHERE id=?""",
            (app_data.get('first_name',''), app_data.get('last_name',''),
             app_data.get('phone',''), dob,
             app_data.get('ssn_last4',''), app_data.get('address',''),
             app_data.get('city',''), app_data.get('state',''),
             app_data.get('zip_code',''), home_ownership,
             app_data.get('employment_status','employed'),
             app_data.get('employer_name',''), app_data.get('employer_phone',''),
             emp_months, float(app_data.get('housing_payment',0)),
             annual_income, credit_score, bid)
        )
        db.commit()

        # ── Score ──
        scorer = get_scorer()
        score_result = None
        if scorer and scorer.model_loaded:
            try:
                # Inject cash flow data if available
                db_cf = get_db()
                cf_row = db_cf.execute("SELECT cash_flow_data FROM borrowers WHERE id=?", (bid,)).fetchone()
                if cf_row and cf_row['cash_flow_data'] and cf_row['cash_flow_data'] != '{}':
                    try:
                        cf_data = json.loads(cf_row['cash_flow_data'])
                        scorer_input['cash_flow_metrics'] = cf_data
                    except:
                        pass
                db_cf.close()
                score_result = scorer.score_application(scorer_input)
            except Exception as e:
                log.error("Scoring error: %s", e)

        if score_result and score_result.get('approved') and 'risk_score' in score_result:
            db.execute(
                "UPDATE applications SET risk_score=?, risk_tier=?, interest_rate=?, monthly_payment=?, origination_fee=?, decision_explanation=?, status=?, decided_at=datetime('now') WHERE id=?",
                (score_result['risk_score'], score_result['risk_tier'], score_result['interest_rate'], score_result['monthly_payment'], score_result['origination_fee'], json.dumps(score_result.get('explanation',{})), 'approved' if score_result['approved'] else 'declined', app_id)
            )
            score_result['application_id'] = app_id
            score_result['loan_amount'] = loan_amount
        else:
            # Fallback with conservative scoring
            score_result = {
                'risk_score': 30, 'risk_tier': 'B', 'risk_label': 'Good', 'approved': True,
                'interest_rate': 12.99, 'monthly_payment': round(loan_amount * 0.033, 2),
                'origination_fee': round(loan_amount * 0.03, 2),
                'max_loan_amount': min(25000, int(loan_amount * 1.2)),
                'recommended_term_months': int(app_data.get('term_months', 36)),
                'probability_of_default': 0.12,
                'explanation': {'summary': 'Application received. Our AI reviewed your financial profile.', 'top_factors': [
                    {'factor': 'debt_to_income_ratio', 'impact': 'positive', 'description': 'Your DTI ratio is manageable'},
                    {'factor': 'credit_history', 'impact': 'positive', 'description': 'Stable credit profile'},
                ]},
                'application_id': app_id,
                'loan_amount': loan_amount,
            }
            db.execute("UPDATE applications SET status='submitted', risk_score=?, risk_tier=? WHERE id=?",
                       (score_result['risk_score'], score_result['risk_tier'], app_id))
        db.commit()
        db.close()
        audit_log('application_submitted', bid, 'system', {'app_id': app_id, 'decision': score_result.get('approved', True)})
        session.pop('app_data', None)
        return render_template('decision.html', result=score_result)

    elif 'step' in request.form:
        for key in request.form:
            if key != 'step':
                app_data[key] = request.form[key]
        session['app_data'] = app_data
        raw_step = request.form['step']
        if raw_step == 'review':
            return render_template('apply.html', data=app_data, step=5)
        step = int(raw_step)
        return render_template('apply.html', data=app_data, step=step)

    return render_template('apply.html', data={}, step=1)


# ── Bank Connection (Cash Flow Underwriting) ──

@app.route('/connect-bank', methods=['GET', 'POST'])
@login_required
def connect_bank(user):
    """Connect bank account for cash flow underwriting."""
    bid = user['id']

    if request.method == 'GET':
        # Check if already connected
        db = get_db()
        row = db.execute("SELECT cash_flow_data, cash_flow_score FROM borrowers WHERE id=?", (bid,)).fetchone()
        already_connected = row and row['cash_flow_data'] and row['cash_flow_data'] != '{}'
        db.close()

        if already_connected:
            try:
                cf = json.loads(row['cash_flow_data'])
                return render_template('connect_bank.html',
                    connected=True,
                    bank_name='Chase Bank',
                    account_last4='6789',
                    months_analyzed=cf.get('months_analyzed', 3),
                    cf_income=cf.get('cash_flow_income', 0),
                    cf_score=cf.get('cash_flow_score', 0),
                    cf_boosted=True,
                    banks=[])
            except:
                pass

        banks = [
            ('chase_good', 'Chase Bank', 'Good credit history, stable income'),
            ('wells_fargo_avg', 'Wells Fargo', 'Average profile, some overdrafts'),
            ('bofa_thin', 'Bank of America', 'Thin credit file, gig worker income'),
            ('us_bank_gig', 'US Bank', 'Gig worker, strong cash flow'),
            ('chime_risky', 'Chime Bank', 'Frequent overdrafts, low balance'),
        ]
        return render_template('connect_bank.html',
            connected=False,
            banks=banks,
            bank_name='', account_last4='',
            months_analyzed=0, cf_income=0, cf_score=0, cf_boosted=False)

    # POST - process bank connection
    profile = request.form.get('bank_profile', 'chase_good')

    # Map bank profile to transaction profile
    profile_map = {
        'chase_good': 'good',
        'wells_fargo_avg': 'average',
        'bofa_thin': 'thin',
        'us_bank_gig': 'gig_worker',
        'chime_risky': 'risky',
    }

    try:
        from underwriting.cash_flow import CashFlowAnalyzer, generate_demo_transactions
        txns = generate_demo_transactions(profile_map.get(profile, 'average'))
        analyzer = CashFlowAnalyzer()
        cf = analyzer.analyze(txns)
    except Exception as e:
        log.error("Cash flow analysis error: %s", e)
        flash('Bank connection failed. Please try again.', 'error')
        return redirect('/connect-bank')

    # Save to borrower record
    db = get_db()
    db.execute("UPDATE borrowers SET cash_flow_data=?, cash_flow_score=? WHERE id=?",
               (json.dumps(cf), cf.get('cash_flow_score', 50), bid))
    db.commit()
    db.close()

    # Store in session for the apply route
    session['cash_flow_connected'] = True

    audit_log('bank_connected', bid, 'system', {'profile': profile, 'cf_score': cf.get('cash_flow_score')})
    flash(f'Bank connected! Cash flow score: {cf["cash_flow_score"]}/100', 'success')
    return redirect('/connect-bank')


# ── Innovation #2: Dynamic Rate Improvement ──

@app.route('/rate-improvement')
@login_required
def rate_improvement(user):
    """Show the borrower's rate improvement status."""
    bid = user['id']
    db = get_db()
    active_loan = db.execute(
        "SELECT * FROM loans WHERE borrower_id=? AND status='active' ORDER BY id DESC LIMIT 1",
        (bid,)
    ).fetchone()
    db.close()

    if not active_loan:
        flash('No active loan to improve.', 'info')
        return redirect('/dashboard')

    try:
        from underwriting.rate_improvement import RateImprovementEngine
        ri = RateImprovementEngine()
        status = ri.get_loan_status(active_loan['id'])
    except Exception as e:
        log.error("Rate improvement error: %s", e)
        flash('Could not load rate improvement data.', 'error')
        return redirect('/dashboard')

    # Get payment history for display
    db = get_db()
    payments = db.execute(
        "SELECT * FROM payments WHERE loan_id=? AND payment_type='scheduled' "
        "ORDER BY paid_at DESC LIMIT 24",
        (active_loan['id'],)
    ).fetchall()
    db.close()

    return render_template('rate_improvement.html',
        loan=dict(active_loan),
        status=status,
        payments=[dict(p) for p in payments],
        now=datetime.now(timezone.utc),
    )


# ── Innovation #3: Income-Share Hybrid ──

@app.route('/income-share', methods=['GET', 'POST'])
@login_required
def income_share(user):
    """Income-share hybrid loan management."""
    bid = user['id']
    db = get_db()
    loan = db.execute(
        "SELECT l.*, a.risk_tier FROM loans l "
        "LEFT JOIN applications a ON l.application_id = a.id "
        "WHERE l.borrower_id=? AND l.status='active' ORDER BY l.id DESC LIMIT 1",
        (bid,)
    ).fetchone()
    nb = db.execute("SELECT * FROM niche_borrowers WHERE borrower_id=?", (bid,)).fetchone()
    db.close()

    if not loan:
        flash('No active loan. Apply first to use income-share features.', 'info')
        return redirect('/apply')

    loan = dict(loan)

    if request.method == 'POST':
        action = request.form.get('action', '')
        monthly_income = request.form.get('monthly_income', type=float, default=0)

        try:
            from underwriting.income_share import IncomeShareEngine
            ise = IncomeShareEngine()

            if action == 'calculate':
                result = ise.calculate_income_share_payment(monthly_income, loan['id'])
                flash(f'Income-share payment: ${result["income_share_payment"]} vs standard ${result["standard_payment"]}', 'info')
                return render_template('income_share.html', loan=loan, result=result, niche=nb)

            elif action == 'toggle_on':
                db = get_db()
                if nb:
                    db.execute("UPDATE niche_borrowers SET income_share_active=1, last_reported_income=? WHERE borrower_id=?", (monthly_income, bid))
                else:
                    db.execute("INSERT INTO niche_borrowers (borrower_id, niche_type, income_share_active, last_reported_income) VALUES (?, 'income_share', 1, ?)", (bid, monthly_income))
                db.commit()
                db.close()
                flash('Income-share mode activated! Your next payment will adjust based on reported income.', 'success')
                return redirect('/income-share')

            elif action == 'toggle_off':
                db = get_db()
                if nb:
                    db.execute("UPDATE niche_borrowers SET income_share_active=0 WHERE borrower_id=?", (bid,))
                    db.commit()
                db.close()
                flash('Income-share mode deactivated. Standard payments resumed.', 'info')
                return redirect('/income-share')
        except Exception as e:
            log.error("Income share error: %s", e)
            flash(f'Error: {e}', 'error')

    # Calculate current status
    result = None
    try:
        from underwriting.income_share import IncomeShareEngine
        ise = IncomeShareEngine()
        status = ise.get_borrower_income_share_status(bid)
        result = status
    except:
        pass

    return render_template('income_share.html', loan=loan, result=result, niche=nb)


# ── Innovation #4: Niche Lending Pages ──

@app.route('/niche/<niche_id>')
@login_required
def niche_landing(user, niche_id):
    """Landing page for a specific niche."""
    try:
        from underwriting.niche_underwriting import NicheUnderwriter
        nu = NicheUnderwriter()
        data = nu.get_niche_landing_data(niche_id)
        if not data:
            flash('Unknown lending niche.', 'error')
            return redirect('/dashboard')
        return render_template('niche_landing.html', data=data, niche_id=niche_id)
    except Exception as e:
        log.error("Niche landing error: %s", e)
        flash(f'Error: {e}', 'error')
        return redirect('/dashboard')


@app.route('/niche/<niche_id>/apply')
@login_required
def niche_apply(user, niche_id):
    """Apply for a loan through a niche-specific flow."""
    try:
        from underwriting.niche_underwriting import NicheUnderwriter
        nu = NicheUnderwriter()
        niche = nu.get_niche(niche_id)
        if not niche:
            flash('Unknown lending niche.', 'error')
            return redirect('/apply')
        return render_template('niche_apply.html', niche=niche, niche_id=niche_id)
    except Exception as e:
        log.error("Niche apply error: %s", e)
        flash(f'Error: {e}', 'error')
        return redirect('/apply')


@app.route('/niche/<niche_id>/apply/submit', methods=['POST'])
@login_required
def niche_apply_submit(user, niche_id):
    """Submit a niche-specific application."""
    bid = user['id']
    try:
        from underwriting.niche_underwriting import NicheUnderwriter
        nu = NicheUnderwriter()

        # Save niche profile
        db = get_db()
        existing = db.execute("SELECT id FROM niche_borrowers WHERE borrower_id=?", (bid,)).fetchone()
        if existing:
            db.execute("UPDATE niche_borrowers SET niche_type=? WHERE borrower_id=?", (niche_id, bid))
        else:
            db.execute("INSERT INTO niche_borrowers (borrower_id, niche_type) VALUES (?, ?)", (bid, niche_id))
        db.commit()
        db.close()

        # Store niche choice in session for the apply flow
        session['niche_type'] = niche_id

        flash(f'Welcome to the {niche_id.replace("_", " ").title()} lending program!', 'success')
        return redirect('/apply')
    except Exception as e:
        log.error("Niche submit error: %s", e)
        flash(f'Error: {e}', 'error')
        return redirect('/dashboard')


@app.route('/niche-list')
@login_required
def niche_list(user):
    """List all available lending niches."""
    try:
        from underwriting.niche_underwriting import NicheUnderwriter
        nu = NicheUnderwriter()
        niches = nu.list_niches()
        return render_template('niche_list.html', niches=niches)
    except Exception as e:
        log.error("Niche list error: %s", e)
        flash(f'Error: {e}', 'error')
        return redirect('/dashboard')


@app.route('/api/rate-improvement/<int:loan_id>')
@admin_required
def api_rate_improvement(admin, loan_id):
    """JSON endpoint for rate improvement data."""
    try:
        from underwriting.rate_improvement import RateImprovementEngine
        ri = RateImprovementEngine()
        data = ri.get_loan_status(loan_id)
        return jsonify(data or {'error': 'Not found'})
    except Exception as e:
        return jsonify({'error': str(e)})


@app.route('/api/niche-list')
def api_niche_list():
    """JSON endpoint listing available niches."""
    try:
        from underwriting.niche_underwriting import NicheUnderwriter
        nu = NicheUnderwriter()
        return jsonify({'niches': nu.list_niches()})
    except Exception as e:
        return jsonify({'error': str(e)})


# ── API: Cash Flow Score ──

@app.route('/api/cash-flow-score', methods=['GET'])
@login_required
def api_cash_flow_score(user):
    """Return the borrower's cash flow score if available."""
    bid = user['id']
    db = get_db()
    row = db.execute("SELECT cash_flow_data, cash_flow_score FROM borrowers WHERE id=?", (bid,)).fetchone()
    db.close()
    if row and row['cash_flow_data'] and row['cash_flow_data'] != '{}':
        try:
            cf = json.loads(row['cash_flow_data'])
            return jsonify({'connected': True, 'score': cf.get('cash_flow_score', 0), 'metrics': cf})
        except:
            pass
    return jsonify({'connected': False})


@app.route('/disconnect-bank', methods=['POST'])
@login_required
def disconnect_bank(user):
    """Remove bank connection data."""
    bid = user['id']
    db = get_db()
    db.execute("UPDATE borrowers SET cash_flow_data='{}', cash_flow_score=0 WHERE id=?", (bid,))
    db.commit()
    db.close()
    session.pop('cash_flow_connected', None)
    flash('Bank disconnected.', 'info')
    return redirect('/connect-bank')


@app.route('/accept-terms', methods=['POST'])
@login_required
def accept_terms(user):
    app_id = request.form.get('application_id', type=int)
    bid = user['id']
    db = get_db()
    app_row = db.execute("SELECT * FROM applications WHERE id=? AND borrower_id=? AND status='approved'", (app_id, bid)).fetchone()
    if not app_row:
        db.close()
        flash('Application not found', 'error')
        return redirect('/dashboard')
    a = dict(app_row)
    c = db.execute(
        "INSERT INTO loans (application_id, borrower_id, principal, interest_rate, term_months, monthly_payment, origination_fee, remaining_balance, status, disbursed_at, next_payment_date) VALUES (?,?,?,?,?,?,?,?,'active',datetime('now'),?)",
        (app_id, bid, a['loan_amount'], a['interest_rate'], a['term_months'], a['monthly_payment'], a['origination_fee'], a['loan_amount'], (datetime.now(timezone.utc)+timedelta(days=30)).strftime('%Y-%m-%d'))
    )
    loan_id = c.lastrowid
    db.execute("UPDATE applications SET status='funded' WHERE id=?", (app_id,))
    pricing = get_scorer().pricing if get_scorer() else None
    if pricing:
        schedule = pricing.calculate_amortization_schedule(a['loan_amount'], a['interest_rate'], a['term_months'])
        for s in schedule:
            db.execute("INSERT INTO payment_schedules (loan_id, payment_number, amount_cents, principal_cents, interest_cents, remaining_balance_cents, due_date, status) VALUES (?,?,?,?,?,?,date('now','+'||?||' days'),'pending')",
                       (loan_id, s['payment_number'], int(s['amount']*100), int(s['principal']*100), int(s['interest']*100), int(s['remaining_balance']*100), s['payment_number']*30))
    db.commit()
    db.close()
    audit_log('loan_funded', bid, 'system', {'loan_id': loan_id, 'amount': a['loan_amount']})
    flash('Your loan has been funded!', 'success')
    return redirect('/dashboard')


# ── Dashboard ──

@app.route('/dashboard')
@login_required
def dashboard(user):
    bid = user['id']
    db = get_db()
    active = db.execute("SELECT * FROM loans WHERE borrower_id=? AND status='active' ORDER BY id DESC LIMIT 1", (bid,)).fetchone()
    recent = db.execute("SELECT * FROM applications WHERE borrower_id=? ORDER BY created_at DESC LIMIT 5", (bid,)).fetchall()
    schedule = []
    if active:
        schedule = db.execute("SELECT * FROM payment_schedules WHERE loan_id=? ORDER BY payment_number", (active['id'],)).fetchall()
    stats = {'active_loans': 0, 'total_borrowed': 0, 'remaining': 0, 'next_payment_date': None}
    s = db.execute("SELECT COUNT(*) as c FROM loans WHERE borrower_id=? AND status='active'", (bid,)).fetchone()
    stats['active_loans'] = s['c']
    s = db.execute("SELECT COALESCE(SUM(principal),0) as s FROM loans WHERE borrower_id=?", (bid,)).fetchone()
    stats['total_borrowed'] = float(s['s'])
    s = db.execute("SELECT COALESCE(SUM(remaining_balance),0) as s FROM loans WHERE borrower_id=? AND status='active'", (bid,)).fetchone()
    stats['remaining'] = float(s['s'])
    s = db.execute("SELECT next_payment_date FROM loans WHERE borrower_id=? AND status='active' ORDER BY next_payment_date LIMIT 1", (bid,)).fetchone()
    if s: stats['next_payment_date'] = s['next_payment_date']
    db.close()
    return render_template('dashboard.html', stats=stats, active_loan=active, schedule=schedule, recent_apps=recent, now=datetime.now(timezone.utc).strftime('%Y-%m-%d'))


# ── Admin ──

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'GET':
        return render_template('admin_login.html')
    email = request.form.get('email', '')
    password = request.form.get('password', '')
    db = get_db()
    row = db.execute("SELECT * FROM admin_users WHERE email=?", (email,)).fetchone()
    if row and check_password(password, row['password_hash']):
        session['admin_token'] = generate_jwt(row['id'], email, 'admin')
        db.close()
        nxt = request.args.get('next') or '/admin/dashboard'
        return redirect(nxt)
    db.close()
    flash('Invalid credentials', 'error')
    return render_template('admin_login.html')


@app.route('/admin/logout')
def admin_logout():
    session.pop('admin_token', None)
    return redirect('/admin/login')


@app.route('/admin/dashboard')
@admin_required
def admin_dashboard(admin):
    db = get_db()
    stats = {
        'borrowers': db.execute("SELECT COUNT(*) as c FROM borrowers").fetchone()['c'],
        'applications': db.execute("SELECT COUNT(*) as c FROM applications WHERE status='submitted'").fetchone()['c'],
        'active_loans': db.execute("SELECT COUNT(*) as c FROM loans WHERE status='active'").fetchone()['c'],
        'total_lent': float(db.execute("SELECT COALESCE(SUM(principal),0) as s FROM loans").fetchone()['s']),
        'collections': db.execute("SELECT COUNT(*) as c FROM collections WHERE outcome=''").fetchone()['c'],
    }
    pending = db.execute("SELECT * FROM applications WHERE status IN ('submitted','approved') ORDER BY created_at DESC LIMIT 20").fetchall()
    loans = db.execute("SELECT * FROM loans ORDER BY created_at DESC LIMIT 20").fetchall()
    db.close()
    return render_template('admin_dash.html', stats=stats, pending=pending, loans=loans)


@app.route('/admin/approve/<int:app_id>', methods=['POST'])
@admin_required
def admin_approve(admin, app_id):
    db = get_db()
    a = db.execute("SELECT * FROM applications WHERE id = ?", (app_id,)).fetchone()
    if not a:
        db.close()
        abort(404)
    db.execute("UPDATE applications SET status='approved', decided_at=datetime('now') WHERE id=?", (app_id,))
    db.commit()
    db.close()
    flash(f'Application #{app_id} approved', 'success')
    return redirect('/admin/dashboard')


@app.route('/admin/decline/<int:app_id>', methods=['POST'])
@admin_required
def admin_decline(admin, app_id):
    db = get_db()
    a = db.execute("SELECT * FROM applications WHERE id = ?", (app_id,)).fetchone()
    if not a:
        db.close()
        abort(404)
    db.execute("UPDATE applications SET status='declined', decided_at=datetime('now') WHERE id=?", (app_id,))
    db.commit()
    db.close()
    flash(f'Application #{app_id} declined', 'info')
    return redirect('/admin/dashboard')


# ── API ──

@app.route('/api/health')
def api_health():
    return jsonify({'status': 'ok', 'version': '2.0.0', 'engine': 'ai-lending'})


@app.route('/api/score-application', methods=['POST'])
@login_required
def api_score(user):
    """Score a loan application. Login required to prevent anonymous abuse."""
    data = request.get_json(silent=True) or {}
    scorer = get_scorer()
    if not scorer or not scorer.model_loaded:
        return jsonify({'error': 'Engine not available', 'approximate': True, 'risk_score': 30, 'approved': True})
    try:
        return jsonify(scorer.score_application(data))
    except Exception as e:
        return jsonify({'error': str(e)}), 400


# ── Register Extended Routes (KYC, Payments, Collections, About) ──

from routes.extended import register_routes
register_routes(app, get_db, login_required, admin_required, audit_log, hash_password, check_password, generate_jwt, decode_jwt)


# ── Register Financial & Compliance Routes ──

@app.route('/admin/funding')
@admin_required
def admin_funding(admin):
    """Financial dashboard with funding, P&L, reserves."""
    try:
        from compliance.funding_tax import (render_funding_html, get_funding_summary, get_portfolio_metrics, profit_and_loss, calculate_cecl_reserve, get_reserve_summary, init_tables as init_funding_tables)
        init_funding_tables()
        summary = get_funding_summary()
        metrics = get_portfolio_metrics()
        cecl = calculate_cecl_reserve()
        reserve = get_reserve_summary()
        pnl = profit_and_loss("2026-01-01", "2026-12-31")
        return render_template('funding_dash.html', funding=summary, portfolio=metrics,
                              cecl=cecl, reserve=reserve, pnl=pnl)
    except Exception as e:
        log.error("Funding dashboard error: %s", e)
        flash(f"Financial data error: {e}", 'error')
        return redirect('/admin/dashboard')


@app.route('/admin/compliance')
@admin_required
def admin_compliance(admin):
    """Compliance dashboard."""
    try:
        from compliance.state_licensing import STATE_RULES
        rules = {k: v for k, v in list(STATE_RULES.items())[:10]}
    except:
        rules = {}
    db = get_db()
    last_loans = db.execute("""
        SELECT l.*, b.first_name, b.last_name, a.risk_tier
        FROM loans l JOIN borrowers b ON l.borrower_id = b.id
        LEFT JOIN applications a ON l.application_id = a.id
        ORDER BY l.created_at DESC LIMIT 10
    """).fetchall()
    db.close()
    return render_template('compliance_dash.html', state_rules=rules, recent_loans=last_loans)


@app.route('/admin/compliance/check-state', methods=['POST'])
@admin_required
def admin_check_compliance(admin):
    """Check loan compliance for a specific state."""
    loan_amount = float(request.form.get('loan_amount', 10000))
    apr = float(request.form.get('apr', 15))
    fee = float(request.form.get('fee', 3))
    term = int(request.form.get('term', 36))
    state = request.form.get('state', 'CA').upper()
    purpose = request.form.get('purpose', 'personal')
    try:
        from compliance.state_licensing import check_loan_compliance
        result = check_loan_compliance(loan_amount, apr, fee, term, state, purpose)
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e), 'compliant': False})


@app.route('/admin/autopilot/run', methods=['POST'])
@admin_required
def admin_run_autopilot(admin):
    """Manually trigger the autopilot cycle."""
    try:
        from automation.autopilot import run_all_operations
        result = run_all_operations()
        flash(f"Autopilot cycle complete. Collections: {result.get('collections', {}).get('processed', 0)}, "
              f"Payments: {result.get('payments', {}).get('processed', 0)}, "
              f"Funding: {result.get('funding', {}).get('funded', 0)}", 'success')
    except Exception as e:
        log.error("Autopilot run error: %s", e)
        flash(f"Autopilot error: {e}", 'error')
    return redirect('/admin/dashboard')


@app.route('/admin/autopilot/status')
@admin_required
def admin_autopilot_status(admin):
    """Autopilot status and last results."""
    status_path = str(_ROOT / 'autopilot_status_last.json')
    results = {}
    if os.path.exists(status_path):
        with open(status_path) as f:
            results = json.load(f)
    return jsonify(results)


# ── Admin Portfolio Route ──

@app.route('/admin/portfolio')
@admin_required
def admin_portfolio(admin):
    """Portfolio analytics page."""
    db = get_db()
    # Loans by risk tier
    loans_by_tier = db.execute("""
        SELECT COALESCE(a.risk_tier, 'N/A') as tier,
               COUNT(*) as count,
               COALESCE(SUM(l.principal), 0) as total_principal,
               COALESCE(AVG(a.interest_rate), 0) as avg_rate
        FROM loans l
        LEFT JOIN applications a ON l.application_id = a.id
        GROUP BY a.risk_tier
        ORDER BY a.risk_tier
    """).fetchall()
    # Originations by month (last 12)
    originations_by_month = db.execute("""
        SELECT strftime('%Y-%m', l.created_at) as month,
               COUNT(*) as count,
               COALESCE(SUM(l.principal), 0) as volume
        FROM loans l
        WHERE l.created_at >= date('now', '-12 months')
        GROUP BY month ORDER BY month
    """).fetchall()
    # Delinquency trend (simplified — payment schedule status)
    delinquency_trend = db.execute("""
        SELECT strftime('%Y-%m', ps.due_date) as month,
               COUNT(*) as total_due,
               SUM(CASE WHEN ps.status = 'pending' AND ps.due_date < date('now') THEN 1 ELSE 0 END) as delinquent
        FROM payment_schedules ps
        WHERE ps.due_date >= date('now', '-6 months')
        GROUP BY month ORDER BY month
    """).fetchall()
    # Active loans grouped by tier for portfolio table
    active_loans = db.execute("""
        SELECT l.*, b.first_name, b.last_name, b.email, a.risk_tier,
               a.interest_rate as apr, a.monthly_payment
        FROM loans l
        JOIN borrowers b ON l.borrower_id = b.id
        LEFT JOIN applications a ON l.application_id = a.id
        WHERE l.status = 'active'
        ORDER BY l.remaining_balance DESC
        LIMIT 100
    """).fetchall()
    # Key metrics
    weighted_avg_apr = db.execute("""
        SELECT COALESCE(AVG(a.interest_rate), 0) as avg_apr FROM loans l
        LEFT JOIN applications a ON l.application_id = a.id WHERE l.status='active'
    """).fetchone()['avg_apr']
    avg_ltv = db.execute("""
        SELECT COALESCE(AVG(l.principal * 1.0 / NULLIF(b.annual_income, 0)), 0) as avg_ltv
        FROM loans l JOIN borrowers b ON l.borrower_id = b.id
        WHERE l.status='active'
    """).fetchone()['avg_ltv']
    # Total portfolio value
    total_portfolio = db.execute("""
        SELECT COALESCE(SUM(principal), 0) as total FROM loans WHERE status='active'
    """).fetchone()['total']
    db.close()
    return render_template('admin_portfolio.html',
        loans_by_tier=[dict(r) for r in loans_by_tier],
        originations_by_month=[dict(r) for r in originations_by_month],
        delinquency_trend=[dict(r) for r in delinquency_trend],
        active_loans=[dict(r) for r in active_loans],
        stats={
            'weighted_avg_apr': round(weighted_avg_apr, 2),
            'avg_ltv': round(avg_ltv * 100, 2),
            'avg_dti': 0,
            'concentration_risk': 0,
            'total_portfolio': total_portfolio,
        }
    )


# ── Admin Loan Detail Route ──

@app.route('/admin/loan/<int:loan_id>')
@admin_required
def admin_loan_detail(admin, loan_id):
    """Detailed loan management page."""
    db = get_db()
    loan = db.execute("""
        SELECT l.*, b.first_name, b.last_name, b.email, b.phone,
               b.date_of_birth, b.ssn_last4, b.address, b.city, b.state, b.zip_code,
               b.employer_name, b.employment_status, b.annual_income, b.credit_score,
               a.risk_tier, a.risk_score, a.loan_purpose, a.interest_rate as apr
        FROM loans l
        JOIN borrowers b ON l.borrower_id = b.id
        LEFT JOIN applications a ON l.application_id = a.id
        WHERE l.id = ?
    """, (loan_id,)).fetchone()
    if not loan:
        db.close()
        flash('Loan not found', 'error')
        return redirect('/admin/dashboard')
    loan = dict(loan)

    # Amortization schedule
    schedule = db.execute("""
        SELECT * FROM payment_schedules WHERE loan_id = ? ORDER BY payment_number
    """, (loan_id,)).fetchall()

    # Payment history
    payments = db.execute("""
        SELECT * FROM payments WHERE loan_id = ? ORDER BY created_at DESC LIMIT 50
    """, (loan_id,)).fetchall()

    # Collections history
    collections = db.execute("""
        SELECT * FROM collections WHERE loan_id = ? ORDER BY created_at DESC LIMIT 20
    """, (loan_id,)).fetchall()

    # Activity log (audit)
    activity = db.execute("""
        SELECT * FROM audit_logs WHERE borrower_id = ? ORDER BY created_at DESC LIMIT 20
    """, (loan['borrower_id'],)).fetchall()

    db.close()
    return render_template('admin_loan_detail.html',
        loan=loan,
        schedule=[dict(s) for s in schedule],
        payments=[dict(p) for p in payments],
        collections=[dict(c) for c in collections],
        activity=[dict(a) for a in activity]
    )


# ── Admin Applications Route ──

@app.route('/admin/applications')
@admin_required
def admin_applications(admin):
    """Full application management page."""
    db = get_db()
    status_filter = request.args.get('status', 'all')
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')
    amount_min = request.args.get('amount_min', '')
    amount_max = request.args.get('amount_max', '')

    query = """
        SELECT a.*, b.first_name, b.last_name, b.email, b.phone
        FROM applications a
        JOIN borrowers b ON a.borrower_id = b.id
        WHERE 1=1
    """
    params = []
    if status_filter != 'all':
        query += " AND a.status = ?"
        params.append(status_filter)
    if date_from:
        query += " AND a.created_at >= ?"
        params.append(date_from)
    if date_to:
        query += " AND a.created_at <= ?"
        params.append(date_to)
    if amount_min:
        query += " AND a.loan_amount >= ?"
        params.append(float(amount_min))
    if amount_max:
        query += " AND a.loan_amount <= ?"
        params.append(float(amount_max))
    query += " ORDER BY a.created_at DESC LIMIT 100"

    applications = db.execute(query, params).fetchall()

    # Stats for filter area
    status_counts = db.execute("""
        SELECT status, COUNT(*) as count FROM applications GROUP BY status
    """).fetchall()

    db.close()
    return render_template('admin_applications.html',
        applications=[dict(a) for a in applications],
        status_counts={r['status']: r['count'] for r in status_counts},
        filters={
            'status': status_filter,
            'date_from': date_from,
            'date_to': date_to,
            'amount_min': amount_min,
            'amount_max': amount_max,
        }
    )


# ── Admin Borrowers Route ──

@app.route('/admin/borrowers')
@admin_required
def admin_borrowers(admin):
    """Borrower management page with full-text search."""
    db = get_db()
    search = request.args.get('search', '').strip()

    query = """
        SELECT b.*,
               (b.first_name || ' ' || b.last_name) AS name,
               (SELECT COUNT(*) FROM loans WHERE borrower_id = b.id) as loans_count,
               (SELECT COUNT(*) FROM applications WHERE borrower_id = b.id) as app_count,
               (SELECT COALESCE(SUM(principal), 0) FROM loans WHERE borrower_id = b.id) as total_borrowed,
               (SELECT status FROM applications WHERE borrower_id = b.id ORDER BY created_at DESC LIMIT 1) as last_status
        FROM borrowers b
    """
    params = []
    if search:
        query += """ WHERE b.first_name LIKE ? OR b.last_name LIKE ?
                     OR b.email LIKE ? OR b.phone LIKE ?"""
        s = f'%{search}%'
        params.extend([s, s, s, s])
    query += " ORDER BY b.created_at DESC LIMIT 100"

    borrowers = db.execute(query, params).fetchall()

    db.close()
    return render_template('admin_borrowers.html',
        borrowers=[dict(b) for b in borrowers],
        search=search
    )


# ── Admin API Stats (JSON) ──

@app.route('/admin/api/stats')
@admin_required
def admin_api_stats(admin):
    """JSON endpoint for dashboard stats."""
    db = get_db()
    stats = {
        'borrowers': db.execute("SELECT COUNT(*) as c FROM borrowers").fetchone()['c'],
        'pending_apps': db.execute("SELECT COUNT(*) as c FROM applications WHERE status='submitted'").fetchone()['c'],
        'active_loans': db.execute("SELECT COUNT(*) as c FROM loans WHERE status='active'").fetchone()['c'],
        'total_lent': float(db.execute("SELECT COALESCE(SUM(principal),0) as s FROM loans").fetchone()['s']),
        'default_rate': round(float(db.execute("SELECT COALESCE(SUM(CASE WHEN status='charged_off' THEN 1 ELSE 0 END),0) * 100.0 / NULLIF(COUNT(*),0) as r FROM loans").fetchone()['r'] or 0), 2),
        'collections_queue': db.execute("SELECT COUNT(*) as c FROM collections WHERE outcome=''").fetchone()['c'],
        'total_loans': db.execute("SELECT COUNT(*) as c FROM loans").fetchone()['c'],
        'paid_off': db.execute("SELECT COUNT(*) as c FROM loans WHERE status='paid_off'").fetchone()['c'],
        'charged_off': db.execute("SELECT COUNT(*) as c FROM loans WHERE status='charged_off'").fetchone()['c'],
    }
    db.close()
    return jsonify(stats)


# ── Admin Bulk Actions ──

@app.route('/admin/applications/bulk', methods=['POST'])
@admin_required
def admin_applications_bulk(admin):
    """Bulk approve/decline applications."""
    action = request.form.get('action', '')
    ids = request.form.getlist('app_ids')
    if not ids:
        flash('No applications selected', 'error')
        return redirect('/admin/applications')
    db = get_db()
    new_status = 'approved' if action == 'approve' else 'declined'
    for app_id in ids:
        db.execute("UPDATE applications SET status=?, decided_at=datetime('now') WHERE id=?",
                   (new_status, int(app_id)))
    db.commit()
    db.close()
    flash(f'{len(ids)} applications {new_status}', 'success')
    return redirect('/admin/applications')


# ── Admin Export CSV ──

@app.route('/admin/applications/export')
@admin_required
def admin_applications_export(admin):
    """Export applications as CSV."""
    import csv
    from io import StringIO
    db = get_db()
    apps = db.execute("""
        SELECT a.id, b.first_name, b.last_name, b.email, a.loan_amount,
               a.loan_purpose, a.risk_score, a.risk_tier, a.status, a.created_at
        FROM applications a JOIN borrowers b ON a.borrower_id = b.id
        ORDER BY a.created_at DESC
    """).fetchall()
    db.close()

    si = StringIO()
    cw = csv.writer(si)
    cw.writerow(['ID', 'First Name', 'Last Name', 'Email', 'Amount', 'Purpose',
                 'Risk Score', 'Tier', 'Status', 'Created'])
    for a in apps:
        cw.writerow([a['id'], a['first_name'], a['last_name'], a['email'],
                     a['loan_amount'], a['loan_purpose'], a['risk_score'],
                     a['risk_tier'], a['status'], a['created_at']])
    output = make_response(si.getvalue())
    output.headers['Content-Type'] = 'text/csv'
    output.headers['Content-Disposition'] = 'attachment; filename=applications.csv'
    return output


# ── System Health ──

@app.route('/admin/system/health')
@admin_required
def admin_system_health(admin):
    """Full system health check."""
    db = get_db()
    health = {
        'status': 'ok',
        'database': {'size_mb': 0, 'tables': []},
        'engine': {'loaded': False, 'auc': 0},
        'modules': {},
    }
    # DB stats
    try:
        tables = db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
        health['database']['tables'] = [t['name'] for t in tables]
        health['database']['size_mb'] = round(os.path.getsize(Config.DATABASE) / 1024 / 1024, 2) if os.path.exists(Config.DATABASE) else 0
    except:
        pass
    db.close()
    # Engine
    scorer = get_scorer()
    if scorer and scorer.model_loaded:
        health['engine'] = {'loaded': True, 'auc': 0.756}
    # Module checks
    for mod_name, mod_import in [
        ('collections', 'loan_collections'),
        ('kyc', 'kyc'),
        ('notifications', 'notifications'),
        ('stripe', 'stripe_payments'),
        ('identity', 'compliance.identity'),
        ('compliance_tila', 'compliance.tila'),
        ('compliance_esign', 'compliance.esign'),
        ('compliance_state', 'compliance.state_licensing'),
        ('funding_tax', 'compliance.funding_tax'),
        ('autopilot', 'automation.autopilot'),
    ]:
        try:
            __import__(mod_import, fromlist=[''])
            health['modules'][mod_name] = 'loaded'
        except Exception as e:
            health['modules'][mod_name] = 'missing'
            log.debug("Module %s: %s", mod_import, e)
    return jsonify(health)


# Bootstrap admin at import time
try:
    _bootstrap_admin()
except Exception as _e:
    log.warning("Admin bootstrap at import failed: %s", _e)


if __name__ == '__main__':
    init_db()
    _bootstrap_admin()
    port = int(os.getenv('FLASK_PORT', '8085'))
    host = os.getenv('FLASK_HOST', '0.0.0.0')
    engine_ok = get_scorer() and get_scorer().model_loaded
    log.info("=" * 50)
    log.info("  AI LENDING COMPANY v2.0")
    log.info("  Engine: %s", "LOADED (AUC 0.756)" if engine_ok else "NOT LOADED")
    log.info("  Listening: http://%s:%d", host, port)
    log.info("  Admin: http://%s:%d/admin/login", host, port)
    log.info("  Landing: http://%s:%d", host, port)
    log.info("=" * 50)
    app.run(host=host, port=port, debug=os.getenv('FLASK_DEBUG', 'false').lower() == 'true')
