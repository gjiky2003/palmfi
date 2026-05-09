Build a complete AI-native consumer lending platform from scratch. This is a cash-intensive build — do NOT cut corners, produce a production-quality system with proper security, error handling, and polish. Use pure Python throughout with no paid APIs or external AI services.

## What to Build

### 1. Underwriting Engine

Train an ML model to score loan applications. Use Python-only ML (scikit-learn or pure Python implementations). The model must take these features and output a risk score, risk tier (A-E), interest rate (10-29% APR), monthly payment, and approval decision:
- age, annual_income, employment_length (years), credit_score, dti_ratio, utilization_rate (0-1), num_derogatory, num_credit_lines, home_ownership (rent/mortgage/own), loan_amount, loan_purpose

Train on synthetic data — generate 1000+ realistic borrower profiles with known good/bad outcomes. Target AUC >= 0.70. Use an ensemble (Decision Tree + Logistic Regression + Random Forest). Save model weights to a file. Include a scorer.py that loads weights and scores in <50ms.

### 2. Flask Web Application

Full Flask app with these features:

**Borrower Flow:**
- Landing page with branding
- Registration (email, password, basic info)
- 5-step loan application form (identity, employment/financials, loan details, document upload, review)
- Instant scoring and decision display
- Borrower dashboard showing active loans, payment history, next payment
- Loan detail page with amortization schedule
- KYC document upload (government ID, proof of address, selfie, bank statement)
- Stripe payment portal (create payment intent, complete payment, auto-pay toggle, saved cards)
- Bank connection page for cash flow underwriting (5 bank profiles to choose from)
- Rate improvement dashboard (shows APR reduction progress for on-time payments)
- Income-share loan management page
- Niche lending pages (gig worker, immigrant, medical borrower flows)

**Admin Portal:**
- Login page (separate from borrower auth)
- Dashboard with live stats (pending apps, active loans, portfolio value, risk distribution)
- Portfolio page with SVG charts (donut for risk tier breakdown, bar for monthly originations, line for delinquency trend)
- Loan detail page (borrower info, terms, amortization schedule, payment history, collections history, actions)
- Applications page (filter by status/date/amount, expandable rows, bulk approve/decline, CSV export)
- Borrowers page (search by name/email/phone, expandable profile, loan summary)
- Collections dashboard (overdue loans, collection stages, run cycle button)
- KYC admin (pending document review, verify/reject)
- Funding dashboard (P&L, CECL reserves, capital pools, portfolio metrics)
- Compliance dashboard
- Settings page (manage Stripe keys, email provider, KYC provider, domain URL — saves to settings.json)

**API Endpoints:**
- GET /api/health — health check
- POST /api/score-application — score a loan (requires auth)
- GET /api/rate-improvement/<loan_id> — rate status (requires admin)
- POST /api/create-payment-intent — create Stripe payment
- POST /stripe/webhook — Stripe webhook handler (signature-verified)

**Auth:** JWT-based. `login_required` decorator for borrower routes, `admin_required` for admin routes. 24-hour token expiry. Admin stored in separate table.

### 3. Automation Modules

**Stripe Payments:**
- create_payment_intent(), confirm_payment(), process_webhook()
- get_payment_methods(), save_payment_method()
- setup_auto_pay(), cancel_auto_pay(), get_auto_pay_status()
- Every function returns mock data when Stripe is unconfigured but always records in DB

**Collections:**
- 6-stage graduated workflow (0-5, 0=reminder through 5=charge-off)
- run_collections_cycle() — checks all overdue loans, advances stages, sends notices
- get_collection_stats() — total overdue, stage counts, charge-offs

**KYC (Know Your Customer):**
- Document upload, validation (file type, size, dimensions)
- auto_verify_kyc() — checks documents + credit score >= 600 + income > 0 + employment status
- Stripe Identity integration option (VerificationSession.create via Stripe API)
- handle_stripe_identity_completed() webhook handler

**Notifications:**
- send_email() via SendGrid with print/log fallback
- send_sms() via Twilio with print/log fallback
- notify_borrower() — looks up contact info from DB, sends via requested channel
- send_payment_reminder() — email + SMS with styled template
- send_collection_notice() — escalating urgency per stage (6 stages of templates)
- All read sendgrid/twilio keys from settings.json with Config/env fallback

**Autopilot:**
- Daily cron: run collections cycle, process payments, allocate funding, create reserves, auto-verify KYC, check fraud
- Status logged to autopilot_status_last.json

### 4. Database

SQLite with tables: borrowers, applications, loans, payments, payment_schedules, collections, audit_logs, kyc_documents, auto_pay, payment_methods, niche_borrowers, admin_users. Use parameterized queries everywhere (no string formatting). Foreign keys enabled.

Borrowers table has: kyc_status, cash_flow_data (JSON), cash_flow_score, stripe_customer_id.
Applications table has: risk_score, risk_tier, interest_rate, monthly_payment, status (draft/submitted/approved/declined), decision_explanation (JSON).
Loans table has: principal, interest_rate, remaining_balance, status, next_payment_date.
Payments table has: amount_cents, payment_type (scheduled/manual), status, stripe_payment_intent.

### 5. Security (Mandatory — Non-Negotiable)

These are not optional:
- **No debug mode in production** — `debug=os.getenv('FLASK_DEBUG', 'false').lower() == 'true'`
- **No hardcoded secrets** — SECRET_KEY, JWT_SECRET must come from env vars. Config class raises ValueError if missing
- **Password hashing via bcrypt** (not SHA-256). Support legacy SHA-256 hashes for migration
- **Secure file uploads** — use `werkzeug.utils.secure_filename()`, validate MIME type server-side, extension whitelist (pdf/jpg/jpeg/png)
- **Authenticated APIs** — scoring API needs `@login_required`, rate improvement needs `@admin_required`
- **Stripe webhook signature verification** — mandatory when webhook secret is configured; no silent try/except bypass
- **No hardcoded admin password** — generate random 128-bit password if ADMIN_PASSWORD env var not set, log it on startup
- Use parameterized SQL queries everywhere (no f-strings in SQL)
- Add `MAX_CONTENT_LENGTH` to Flask config
- Set session cookie flags: HttpOnly=True, SameSite='Lax'

### 6. Testing

E2E test suite using curl against the running server: register borrower, login, submit application, check score, upload KYC, make payment, admin login, run collections, check health API. Target 40+ tests passing.

### 7. Docs & Output

Create a `launch/` directory with:
- Interactive HTML checklist (clickable items with counters) covering all tasks across 4 phases
- LLC operating agreement template
- Compliance business plan for Texas OCCC license application (11 sections: executive summary, company overview, management, underwriting methodology, compliance program — TILA/GLBA/BSA/AML/ECOA/UDAAP, collections policy, consumer protection, recordkeeping, business continuity, financial projections)
- Plain-language loan contract compliant with Texas Finance Code Chapter 342 + TAC Chapter 90 (10 sections with TILA table, payment schedule, prepayment terms, default/collections, borrower rights, signatures)
- 14-slide investor pitch deck .pptx (dark theme, emerald-600 accent)
- Private placement memo draft
- Surety bond procurement guide
- KYC vendor evaluation (Stripe Identity vs Persona vs Onfido comparison)
- Lender partnership outreach list + cold email template
- 10-chapter compliance manual outline
- Full domain/HTTPS setup guide (Nginx, Let's Encrypt, Cloudflare Tunnel)
- Pilot loans operations guide (budget, process, borrower sourcing, what to track)
- Pilot portfolio tracker CSV (10-loan template)
- Security audit report documenting all findings

### 8. Email Templates

6 branded HTML templates in launch/email_templates/: welcome.html, approved.html, payment_reminder.html, payment_received.html, collection_notice.html, rate_improvement.html. Dark theme (#0f172a background, #059669 accent), inline styles (email-safe), Jinja2 template variables for borrower name, amounts, dates.

## Design System

Dark theme throughout: primary #1a365d, accent #059669 (emerald), background slate-900. Clean, modern, professional. Tailwind CSS via CDN. Font Awesome icons.

## Directory Structure

```
project-root/
├── app.py                 # Main Flask app
├── config.py              # Env-based configuration, no secret defaults
├── models.py              # DB schema and helpers
├── requirements.txt
├── .env.example
├── Dockerfile
├── docker-compose.yml
├── startup.sh
├── test_e2e.py
├── launch/                # Business docs (22 files)
│   ├── README.html        # Interactive checklist
│   ├── *.md, .pptx, .csv   # All business documents
│   └── email_templates/   # 6 HTML templates
├── automation/
│   ├── autopilot.py
│   ├── kyc.py              # KYC verification + Stripe Identity
│   ├── loan_collections.py
│   ├── notifications.py    # SendGrid + Twilio with settings-aware config
│   ├── stripe_payments.py
│   └── settings.py         # Settings panel module
├── platform/
│   ├── app.py
│   ├── config.py
│   ├── models.py
│   ├── templates/          # 30+ Jinja2 templates
│   ├── static/
│   └── routes/
│       └── extended.py     # KYC, Payments, Collections, Settings routes
├── underwriting/
│   ├── scorer.py           # Model load + score
│   ├── train.py            # Model training
│   ├── ensemble_model.py
│   ├── decision_tree.py
│   ├── logistic_regression.py
│   ├── random_forest.py
│   ├── feature_engineer.py
│   ├── pricing.py
│   ├── cash_flow.py
│   ├── income_share.py
│   ├── rate_improvement.py
│   ├── niche_underwriting.py
│   ├── backtest.py
│   └── data_generator.py
└── compliance/
    ├── tila.py
    ├── disclosures.py
    ├── esign.py
    ├── identity.py
    ├── state_licensing.py
    └── funding_tax.py
```

## Key Patterns to Follow

- **Route organization:** app.py has core routes. Extended routes (KYC, payments, collections, settings) live in routes/extended.py and register via a `register_routes()` callback pattern to avoid circular imports
- **All automation modules support fallback** — if Stripe/SendGrid/Twilio keys are missing, they log to console and return mock data
- **DB path resolution** — each automation module tries to import platform.models first, then falls back to direct sqlite3 path
- **Settings-driven config** — notifications, KYC, Stripe read from `launch/settings.json` (managed via admin settings panel) with fallback to Config/env vars
- **Bcrypt password hashing** with legacy SHA-256 support for existing database migration

## Deliverable

A fully working platform at palm.ngrok.app (or similar tunnel URL) with:
- `bash startup.sh` starts everything
- `python3 test_e2e.py` runs against the running server and passes 40+ tests
- Admin accessible at /admin/login
- Borrower can register, apply, get scored, upload KYC, and make payments end-to-end
- All 22 launch documents generated and ready for business use
