# PalmFi Lending LLC
# Compliance Business Plan & License Application Narrative
# For: Texas OCCC Regulated Lender License (Chapter 342, Texas Finance Code)

---

## 1. Executive Summary

**PalmFi Lending LLC** ("PalmFi") is a Delaware limited liability company applying for a Texas Regulated Lender License under Chapter 342 of the Texas Finance Code. PalmFi operates an AI-native consumer lending platform that makes fully automated personal loans of $500–$50,000 to Texas residents.

**Core proposition:** PalmFi uses a machine learning underwriting ensemble (AUC 0.756) to evaluate borrowers holistically — beyond FICO scores — enabling fair, data-driven credit decisions for mainstream and thin-file borrowers alike. The platform is fully automated: application → scoring → approval/decline → disbursement → collections requires zero human touch.

**Headquarters:** [Your Address]
**Registered Agent:** [Registered Agent Name, Address]
**EIN:** [XX-XXXXXXX]
**Principal:** [Your Name], [Your Title]

---

## 2. Company Overview

### 2.1 Business Model
PalmFi originates unsecured personal loans through a direct-to-consumer web platform at palm.ngrok.app (to be migrated to palmfi.com upon launch). Loans are funded from the Company's own capital (seed stage) and ultimately from a mix of equity, debt facilities, and revenue reinvestment.

### 2.2 Loan Products

| Product | Amount | APR Range | Term | Structure |
|---------|--------|-----------|------|----------|
| Standard Personal Loan | $500–$50,000 | 10%–29% | 12–60 months | Fixed-rate, simple interest |
| Income-Share Hybrid* | $500–$15,000 | Equivalent 8%–22% | 6–60 months | % of income, capped |

*Income-share loans are an alternative payment option where the borrower pays a percentage of verified monthly income instead of a fixed payment, capped at 150% of the standard amortization.

### 2.3 Target Market
- Texas residents aged 18+ with valid SSN/ITIN
- Credit score range: 580–720 (including thin-file borrowers)
- Employment income: $1,500+/month minimum
- Primary use cases: Debt consolidation, home improvement, medical expenses, auto repair, education

---

## 3. Management Team

**Principal:** [Your Name], Founder & CEO
- Full-stack development, ML engineering, fintech platform architecture
- Built the complete PalmFi platform: underwriting engine, web application, payment systems, compliance framework
- [Additional relevant experience]

*Additional key personnel will be added as the Company scales. During the initial license period, compliance functions will be supported by [attorney/counsel name] of [law firm].*

---

## 4. Underwriting Methodology

### 4.1 Machine Learning Scoring
PalmFi uses a three-model ensemble:
- **Decision Tree** — interpretable baseline
- **Logistic Regression** — probability calibration
- **Random Forest** — high-dimensional feature interaction

**Ensemble AUC: 0.756** — strong risk discrimination.

### 4.2 Features Analyzed

| Category | Features |
|----------|----------|
| Income & Employment | Annual income, employment length, income source, pay frequency |
| Credit History | Credit score range, number of credit lines, derogatory marks |
| Debt Capacity | DTI ratio, monthly housing payment, existing debt obligations |
| Behavior | Credit card utilization rate, home ownership status |
| Loan-Specific | Loan amount, loan purpose, term requested |

### 4.3 Cash Flow Underwriting (For Thin-File Borrowers)
When bank account data is provided, PalmFi analyzes:
- Average monthly deposits and income volatility
- Overdraft/NSF frequency (last 90 days)
- Expense categorization and recurring bills
- Minimum daily balance trend

Cash flow analysis contributes up to 30% weight in the final risk score (50% for thin-file borrowers).

### 4.4 Fair Lending Compliance
All features are selected to be:
- **Not proxies for prohibited basis** (race, color, religion, national origin, sex, marital status, age, receipt of public assistance)
- **Adverse action reasoning** generated for every declined application, per ECOA/Reg B
- **Model fairness tested** on simulated demographic distributions

---

## 5. Compliance Program

### 5.1 TILA / Regulation Z
- All loan contracts include: finance charge, APR, amount financed, total of payments, payment schedule
- Right of rescission (if applicable)
- Periodic statements provided to borrowers with active loans

### 5.2 Truth in Lending & Plain Language
- Contracts written in clear, plain English per TAC Chapter 90
- Prominent disclosure of rates, fees, and repayment terms
- No confusing legal jargon in borrower-facing documents

### 5.3 GLBA Privacy & Data Security
- Written information security program maintained
- Borrower data encrypted at rest (AES-256) and in transit (TLS 1.3)
- Limited internal access on a need-to-know basis
- Annual privacy notice delivered to all borrowers
- Opt-out rights provided for information sharing

### 5.4 BSA/AML Program
- Due to the nature of direct-to-consumer lending, PalmFi is not a bank and does not accept deposits. However, PalmFi will maintain:
  - Identity verification (KYC) for all borrowers
  - Suspicious activity monitoring on payment patterns
  - OFAC screening at origination

### 5.5 Fair Lending / ECOA
- All credit decisions made by algorithmic model — no human bias
- Model outcomes monitored for adverse impact
- Credit denial notifications include specific reasons and ECOA notice
- Spousal signature never required
- Public assistance income treated same as employment income

### 5.6 UDAAP Compliance
- All marketing materials accurately represent loan terms
- No misleading APR comparisons or fee disclosures
- Clear, simple fee schedules
- Prepayment penalty: None (as required by TFC §342.252)

---

## 6. Collections Policy

### 6.1 Graduated Collections Workflow

| Stage | Days Past Due | Action |
|-------|--------------|--------|
| Stage 0 | 0-10 | Reminder email/SMS |
| Stage 1 | 11-30 | Soft phone call, payment portal link |
| Stage 2 | 31-60 | Escalated phone call, email, late fee assessed |
| Stage 3 | 61-90 | Supervisor call, payment plan offered |
| Stage 4 | 91-120 | Final notice, referral to collections partner |
| Stage 5 | 120+ | Charge-off, credit reporting, potential legal action |

### 6.2 Collection Practices Compliance
- No calls before 8am or after 9pm (borrower's local time)
- No third-party disclosure of debt
- No harassment or false representations
- Debt validation notice provided within 5 days of first contact
- All communications comply with Texas Debt Collection Act (TFC Ch. 392) and FDCPA

### 6.3 Hardship Accommodations
Borrowers experiencing temporary financial difficulty may request:
- Payment deferral (up to 2 months)
- Modified payment plan
- Interest rate freeze during forbearance period

---

## 7. Consumer Protection

### 7.1 Complaint Management
- **Dedicated email:** complaints@palmfi.com
- **Response standard:** Initial acknowledgment within 2 business days; resolution within 15 business days
- **Recordkeeping:** All complaints logged in CRM with resolution status
- **Annual reporting:** Complaint summary provided to OCCC upon request
- **Escalation:** Borrowers directed to Texas OCCC after internal resolution attempt

### 7.2 Dispute Resolution
Borrowers may dispute any charge or payment by sending written notice to PalmFi. PalmFi will investigate and respond within 30 days. If the dispute involves a billing error, provisions of TILA Section 161 apply.

### 7.3 Credit Reporting
PalmFi will report to at least one major credit bureau (to be determined based on cost and integration feasibility). Reporting includes:
- Monthly payment history (on-time, late, charge-off)
- Loan opening date and current balance
- Loan closure (paid in full or charged off)

---

## 8. Recordkeeping

PalmFi maintains all loan records for the following periods:

| Record Type | Retention Period |
|-------------|-----------------|
| Loan application & decisions | 5 years after final payment/charge-off |
| Payment history | 5 years after final payment |
| Collections records | 3 years after account closure |
| Complaint records | 3 years |
| Compliance training records | 3 years |
| Audit logs | 2 years |

Records stored in encrypted database with daily automated backups. Physical backup retained off-site.

---

## 9. Business Continuity

- **Hosting:** Cloud-based infrastructure with automatic failover
- **Data backup:** Daily encrypted off-site backups, tested quarterly
- **Uptime target:** 99.5% for borrower-facing portal
- **Incident response:** Security incident response plan with 24-hour notification to affected parties and regulators
- **Key person risk:** Platform designed to operate with minimal human intervention; underwriting and collections run autonomously

---

## 10. Financial Projections

| Metric | Year 1 | Year 2 |
|--------|--------|--------|
| Loans originated | 50–100 | 500–1,000 |
| Average loan size | $3,500 | $5,000 |
| Total originations | $175,000–$350,000 | $2.5M–$5M |
| Gross revenue (APR) | $35,000–$80,000 | $450,000–$1M |
| Net charge-off rate (projected) | 5–8% | 5–8% |
| Operating expenses | $50,000–$80,000 | $100,000–$200,000 |
| Capital requirement | $200,000–$350,000 | $2M–$4M (debt facility) |

Detailed financial statements available upon request.

---

## 11. Attachments

- [X] Certificate of Formation (Delaware)
- [X] Certificate of Foreign Qualification (Texas) — *to be filed*
- [X] EIN Confirmation Letter
- [X] Principal Background Disclosure Form
- [X] Proposed Loan Contract
- [X] Financial Statements (Balance Sheet, P&L)
- [X] Surety Bond (to be obtained)
- [X] Privacy Policy
- [X] Terms of Service

---

**Document Date:** [Date]
**Prepared By:** [Your Name]
**For:** Texas Office of Consumer Credit Commissioner
**License Type:** Regulated Lender (Chapter 342)
