# PalmFi v2 — Build Checklist

> **Version:** v2.0 | **Built:** May 2026 | **Partner Bank Requirements:** Integrated

---

## ✅ Done (Built, Tested, Integrated)

| # | Module | File | Lines | What It Does |
|---|--------|------|-------|-------------|
| 1 | **XGBoost Scorer** | `underwriting/xgb_scorer.py` | 571 | Primary bureau model — AUC 0.678 on LC data, beats old 0.666 ensemble. 12 features, SHAP explainer, FICO gap penalty (<660). |
| 2 | **Reconsideration Engine** | `underwriting/reconsideration_engine.py` | 319 | Two-stage orchestration: 3 zones (auto-approve ≤50, consider 51-60, decline >60). Blends bureau + cash flow (50/50 or 40/60). |
| 3 | **LLM Doc Extractor** | `underwriting/llm_doc_extractor.py` | 634 | DeepSeek API document intelligence for self-employed. 4 mock profiles (photographer, rideshare, dev, contractor). Stub ready for real API key. |
| 4 | **Gating Rules** | `underwriting/gating_rules.py` | 1,545 | 10 hard cuts (age, SSN fraud, bankruptcy, OFAC, death master, state, amount, term). 7 suppressions (velocity, address instability, income discrepancy, inquiry spike, high-risk ZIP, timing, new account). 3 soft overrides. |
| 5 | **Manual Review Assistant** | `underwriting/manual_review_assistant.py` | 1,843 | LLM-powered underwriter copilot. Structured output: risk factors, strengths, red flags, recommendation, fraud probability, borrower questions. DeepSeek stub ready. |
| 6 | **SHAP Adverse Action** | `compliance/shap_adverse_action.py` | 1,134 | ECOA/Reg B-compliant reason codes. Maps SHAP values → top 4 adverse reasons. Full HTML adverse action notice (creditor info, score disclosure, ECOA/FCRA notices). |
| 7 | **BISG Fair Lending Analyzer** | `compliance/bisg_analyzer.py` | 1,719 | Bayesian Improved Surname Geocoding. 65+ surname table, census tract, 4/5th rule, proxy feature analysis. Generates regulator-grade HTML quarterly report with attestation. |
| 8 | **V2 Application Pipeline** | `platform/credit_application.py` (new functions) | 680 | `process_application_two_stage()` + `_run_stage2()` + `reconsider_application()`. Hard cuts before scoring, suppression flags, manual review routing. |
| 9 | **Flask Routes** | `platform/app.py` (v2 additions) | ~200 added | `/second-look`, `/second-look/connect`, `/manual-review`, `/admin/manual-review`, `/admin/manual-review/<id>/decide` |
| 10 | **Second Look Template** | `platform/templates/second_look.html` | 170 | Borrower Plaid connection page with 4 mock bank profiles. Zone-based messaging (consideration vs decline). |
| 11 | **Manual Review Template** | `platform/templates/manual_review.html` | 94 | Borrower-facing "Under Review" page with suppression explanation and timeline. |
| 12 | **Admin Review Queue** | `platform/templates/admin_manual_review.html` | 155 | Admin queue with LLM assistant summary cards, risk/strength factors, red flags, rationale, approve/decline buttons. |

---

## 🔄 Partially Done (Structure Built, Needs Wiring)

| # | Component | Status | What's Missing |
|---|-----------|--------|---------------|
| 1 | **DeepSeek REAL mode (LLM Extractor)** | ⚠️ Stub ready | Set `DEEPSEEK_API_KEY` env var to activate. Currently returns mock data. |
| 2 | **DeepSeek REAL mode (Review Assistant)** | ⚠️ Stub ready | Set `DEEPSEEK_API_KEY` env var to activate. Uses `openai` SDK with `https://api.deepseek.com/v1`, model `deepseek-chat`. |
| 3 | **Plaid REAL mode** | ⚠️ Mock only | Set `PLAID_CLIENT_ID` + `PLAID_SECRET` env vars. Currently generates mock transactions. |
| 4 | **Bureau REAL mode** | ⚠️ Mock only | Set `STIPULA_API_KEY` env var to pull real credit reports. Currently deterministic mock from SSN hash. |
| 5 | **Stripe LIVE mode** | ⚠️ Mock only | Set `STRIPE_SECRET_KEY` env var for real payment processing. |

---

## 📋 To Do (Next Phase)

| # | Priority | Item | Effort | Details |
|---|----------|------|--------|---------|
| 1 | 🔴 **High** | **Deploy to Render/Fly.io** | 1 day | Flask + SQLite + XGBoost. Pick Render ($7/mo) or Fly.io ($5/mo). Cloudflare for DNS. |
| 2 | 🔴 **High** | **E2E test suite for v2 routes** | 4-6 hrs | Update `test_e2e.py`: test `/second-look` flow, manual review queue, hard cut scenarios, reconsideration with mock Plaid. |
| 3 | 🟡 **Medium** | **Real API keys** | 1 day | Sign up for DeepSeek, Plaid dev sandbox, Stipula sandbox. Wire into `.env`. |
| 4 | 🟡 **Medium** | **Admin dashboard integration** | 4 hrs | Add manual review count badge to admin nav. Add "Pending Reviews" card to admin dashboard with count + quick link. |
| 5 | 🟡 **Medium** | **Argyle/Pinwheel payroll integration** | 2-3 days | Employment verification: mock-first pattern like Plaid. Employer tenure, income verification from payroll data. |
| 6 | 🟡 **Medium** | **Rent/utility reporting** | 1-2 days | Experian RentBureau or Esusu API. Add rent payment history as underwriting feature. |
| 7 | 🟢 **Low** | **BISG quarterly cron** | 2 hrs | Schedule `/admin/run-bisg` or cron job to auto-generate quarterly fair lending report. |
| 8 | 🟢 **Low** | **Model retraining pipeline** | 1 day | Script to retrain XGBoost with new loan performance data. Champion/challenger comparison. PSI drift monitoring. |
| 9 | 🟢 **Low** | **Performance monitoring** | 2 days | Approval rate dashboard, default rate tracking, score distribution monitoring, response time alerting. |
| 10 | 🟢 **Low** | **Collections automation** | 2-3 days | Autopilot for dunning, late fee assessment, escalation at 60 days. Built on existing `automation/autopilot.py`. |

---

## 🏗️ Architecture Flow (Current)

```
                    ┌─────────────────────────────┐
                    │  Applicant submits app       │
                    │  (SSN + DOB + financial info)│
                    └─────────────┬───────────────┘
                                  │
                                  ▼
                    ┌─────────────────────────────┐
                    │  Identity Verification      │
                    └─────────────┬───────────────┘
                          FAIL    │    PASS
                            ┌─────┘
                            ▼
                      ┌─────────────┐
                      │ "Identity   │
                      │  mismatch"  │
                      └─────────────┘
                                  │
                                  ▼
                    ┌─────────────────────────────┐
                    │  Bureau Pull                 │
                    │  → FICO, DTI, utilization    │
                    └─────────────┬───────────────┘
                                  │
                                  ▼
                    ┌─────────────────────────────┐
                    │  HARD CUTS ⛔                │
                    │  age, SSN fraud, bankruptcy  │
                    │  OFAC, death, state, amount  │
                    │  term, existing loan,        │
                    │  previous charge-off         │
                    └─────────────┬───────────────┘
                         BLOCKED  │    PASS
                           ┌──────┘
                           ▼
                     ┌──────────────┐
                     │ DECLINED     │
                     │ (hard cut)   │
                     └──────────────┘
                                  │
                                  ▼
                    ┌─────────────────────────────┐
                    │  SUPPRESSIONS ⚠️             │
                    │  velocity, address, income   │
                    │  inquiries, ZIP, timing,     │
                    │  new account                 │
                    └─────────────┬───────────────┘
                       FLAGGED    │    PASS
                        (manual   │
                         review)  │
                                  ▼
                    ┌─────────────────────────────┐
                    │  XGBoost Primary Score       │
                    │  (bureau features only)      │
                    │  + FICO gap penalty (<660)   │
                    └─────────────┬───────────────┘
                                  │
                    ┌─────────────┼─────────────┐
                    │             │             │
                    ▼             ▼             ▼
             ┌──────────┐  ┌──────────┐  ┌──────────┐
             │ Auto-    │  │ Consider-│  │ Decline  │
             │ Approve  │  │ ation    │  │ Zone     │
             │ ≤ 50     │  │ 51-60    │  │ > 60     │
             └────┬─────┘  └────┬─────┘  └────┬─────┘
                  │             │             │
                  │        ┌────┴─────────────┘
                  │        │
                  │        ▼
                  │  ┌─────────────────────────────┐
                  │  │  SECOND LOOK                │
                  │  │  → Connect bank via Plaid   │
                  │  │  → Cash flow analysis       │
                  │  │  → LLM doc boost (if SE)    │
                  │  │  → Reconsideration score    │
                  │  └─────────────┬───────────────┘
                  │                │
                  │        ┌───────┼───────┐
                  │        │       │       │
                  ▼        ▼       ▼       ▼
           ┌────────┐ ┌────────┐ ┌────────┐ ┌──────────────┐
           │Approved│ │Approved│ │STILL   │ │Final Decline │
           │(bureau)│ │(recon) │ │BORDER  │ │→ SHAP ECOA   │
           │w/ opt  │ │w/ adj  │ │LINE    │ │→ Adverse     │
           │CF link │ │terms   │ │        │ │  Action      │
           └────────┘ └────────┘ └───┬────┘ │  Notice      │
                                     │      └──────────────┘
                                     ▼
                            ┌──────────────────────┐
                            │ MANUAL REVIEW QUEUE  │
                            │ → LLM Assistant      │
                            │ → Summarizes case    │
                            │ → Suggests decision  │
                            │ → Human decides      │
                            └──────────────────────┘
```

**Three Decision Zones (calibrated from LC test set):**
- **Auto-Approve:** ≤ 50 (60.2% of population)
- **Consideration:** 51-60 (20.9%)
- **Decline:** > 60 (18.9%)
- **Reconsideration threshold:** ≤ 60

**Blend Weights:**
- Consideration zone: 50% bureau + 50% cash flow
- Decline zone: 40% bureau + 60% cash flow

---

## 📦 File Inventory

```
~/ai-lending-company/
├── underwriting/
│   ├── xgb_scorer.py              (571 lines)  ✅ XGBoost primary scorer
│   ├── reconsideration_engine.py  (319 lines)  ✅ Two-stage decision flow
│   ├── llm_doc_extractor.py       (634 lines)  ✅ DeepSeek doc extraction (mock)
│   ├── gating_rules.py            (1,545 lines) ✅ Hard cuts + suppressions
│   ├── manual_review_assistant.py (1,843 lines) ✅ LLM reviewer assistant (mock)
│   ├── model_xgb.json              (48K)       ✅ Trained XGBoost model
│   ├── model_weights_xgb.json      (2K)        ✅ Model metadata + SHAP baseline
│   └── ARCHITECTURE_V2.md          (this file) ✅ Build checklist
├── compliance/
│   ├── shap_adverse_action.py     (1,134 lines) ✅ SHAP ECOA reason codes
│   └── bisg_analyzer.py           (1,719 lines) ✅ BISG fair lending
├── platform/
│   ├── credit_application.py      (680 lines)  ✅ V2 two-stage pipeline
│   ├── app.py                     (>1,700 ln)  ✅ V2 routes integrated
│   └── templates/
│       ├── second_look.html        (170 lines)  ✅ Plaid second-chance page
│       ├── manual_review.html      (94 lines)   ✅ Borrower under-review page
│       └── admin_manual_review.html (155 lines) ✅ Admin review queue
```

**Totals:** 12 new/updated files | ~10,000 lines core code | ~50 lines templates

---

## 🚀 Quick Start

```bash
# Run the app
cd ~/ai-lending-company
python3 platform/app.py           # → http://localhost:8085

# Test core modules
python3 -c "
from underwriting.xgb_scorer import XGBoostScorer
s = XGBoostScorer(); s.load()
r = s.score_application({'credit_score':700,'annual_income':65000,'loan_amount':4000,
  'age':35,'employment_length':5,'dti_ratio':0.28,'utilization':0.3,
  'num_derogatory':0,'num_credit_lines':8,'home_ownership':'mortgage',
  'loan_purpose':'debt_consolidation'})
print(f\"Score: {r['risk_score']} | Approved: {r['approved']} | Rate: {r['interest_rate']}%\")
"

# Test gating rules
python3 -c "
from underwriting.gating_rules import GatingRules
g = GatingRules()
r = g.evaluate({'date_of_birth':'1990-01-01','state':'VA','loan_amount':3000,
  'term_months':12,'ssn':'123-45-6789','annual_income':50000})
print(f\"Blocked: {r['hard_cut_blocked']} | Suppressed: {r['suppression_flagged']}\")
print(f\"Summary: {r['gating_summary']}\")
"

# Test LLM reviewer
python3 -c "
from underwriting.manual_review_assistant import ManualReviewAssistant
m = ManualReviewAssistant()
r = m.review({'app_data':{'credit_score':640},'model_result':{'risk_score':55},
  'zones':{'original_zone':'consideration'},'gating_results':{'suppression_flagged':False}})
print(f\"Decision: {r['recommendation']['decision']} | Conf: {r['recommendation']['confidence']}\")
"

# Test SHAP adverse action
python3 -c "
from compliance.shap_adverse_action import ShapAdverseAction
s = ShapAdverseAction(['credit_score','dti_ratio','utilization','num_derogatory',
  'num_credit_lines','age','log_income','employment_length','log_loan_amount',
  'home_rent','home_mortgage','home_own'])
r = s.generate({'base_value':0.0,'values':[{'feature':'credit_score','shap_value':0.25}]},
  {'credit_score':620,'dti_ratio':0.40}, 65, False)
print(f\"Reasons: {len(r)}\")
for reason in r: print(f\"  {reason['code']}: {reason['reason']}\")
"

# Test BISG analyzer
python3 -c "
from compliance.bisg_analyzer import BISGAnalyzer
b = BISGAnalyzer()
p = b.surname_to_probs('Gonzalez')
print(f'Gonzalez BISG probs: {p}')
"
```
