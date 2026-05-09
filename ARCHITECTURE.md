# AI-Native Personal Lending Company — Architecture

## Company Overview
Fully automated, zero-human personal lending platform.
- **Borrower facing:** Submit application → AI scores → Instant decision → Fund → Auto-collect
- **Admin facing:** Dashboard to monitor portfolio, risk, collections, compliance
- **AI core:** Everything from marketing to underwriting to collections is AI-driven

## Tech Stack
- **Backend:** Python Flask (proven from PM system) + SQLite (dev) / PostgreSQL (prod)
- **Frontend:** Server-rendered HTML with Tailwind CSS (mobile-first, no JS build tools)
- **AI/ML:** Pure Python underwriting engine (ensemble: logistic regression + decision tree + random forest)
- **Payments:** Stripe API integration (sandbox first)
- **KYC/AML:** Automated document verification + identity checks
- **Deployment:** Docker compose, one-command deploy
- **Notifications:** Email (SendGrid) + SMS (Twilio) for automated borrower communication

## Modules (build order)

### Module 1: Credit Underwriting Engine (~/ai-lending-company/underwriting/)
- `model.py` — Pure Python ensemble model (logistic regression, decision tree, random forest)
- `feature_engineering.py` — Feature extraction from borrower data
- `scoring.py` — Risk scoring + pricing + decision logic
- `data_generator.py` — Synthetic training data generator
- `train.py` — Train and save model weights
- `backtest.py` — Historical profit simulation and validation

### Module 2: Core Platform (~/ai-lending-company/platform/)
- `app.py` — Flask application entry point
- `models.py` — SQLAlchemy models (Borrower, Application, Loan, Payment, etc.)
- `routes/` — Flask blueprints for each domain
  - `auth.py` — Login/register for borrowers + admin
  - `apply.py` — Loan application flow
  - `dashboard.py` — Borrower dashboard
  - `admin.py` — Admin dashboard
  - `payments.py` — Payment processing
  - `api.py` — REST API for external integrations
- `templates/` — Jinja2 HTML templates (mobile-responsive, Tailwind CSS)
- `static/` — CSS/JS assets

### Module 3: Automated Systems (~/ai-lending-company/automation/)
- `collections.py` — Automated collection workflows (SMS/email reminders, escalation)
- `kyc.py` — KYC/AML verification logic
- `compliance.py` — Regulatory reporting, audit trails
- `notifications.py` — Email/SMS notification engine
- `marketing.py` — Automated marketing campaigns, referral tracking

### Module 4: Admin Dashboard (~/ai-lending-company/admin/)
- `portfolio.py` — Loan portfolio performance analytics
- `risk_monitor.py` — Real-time risk monitoring, stress testing
- `origination.py` — Loan origination workflow management
- `collections_dash.py` — Collections performance dashboard

### Module 5: Deployment
- `Dockerfile`
- `docker-compose.yml`
- `deploy.sh`
- `requirements.txt`
- `.env.example`

## Data Model (Core Entities)
- **Borrower**: Personal info, KYC status, credit history reference
- **Application**: Loan request, risk score, decision, pricing
- **Loan**: Funded loan, balance, interest rate, term, status
- **Payment**: Payment transactions, schedule, status
- **Collection**: Collection actions, communications, outcomes
- **AuditLog**: All AI decisions, manual overrides, compliance records

## Lending Flow
1. **Acquisition** → Landing page → Apply button
2. **Application** → Collect borrower data (income, employment, ID, bank account)
3. **KYC/AML** → Verify identity, check sanctions/pep lists
4. **Underwriting** → AI scores risk → Determines approval + terms
5. **Disclosure** → Present loan terms → Borrower e-signs
6. **Funding** → Disburse to bank account (Stripe Connect / ACH)
7. **Servicing** → Auto-collect monthly payments → SMS/email reminders
8. **Collections** → Automated escalation if delinquent → AI negotiation
9. **Reporting** → Portfolio analytics → Regulatory filings → Investor reports

## Pricing Model
- Risk-based interest rates (5%-35% APR depending on AI score)
- Origination fee: 1%-5% of loan amount
- Late fee: $25 after 5 days, $35 after 15 days
- Prepayment: No penalty

## AI Automation Rules
- Underwriting: 100% AI, no human touch
- KYC review: 100% AI, manual review only if confidence < 90%
- Collections: Tiered automation (SMS → Email → Phone → Legal referral)
- Marketing: AI-managed campaigns, A/B tested automatically
- Compliance reporting: Auto-generated
