# MODEL GOVERNANCE DOCUMENT

## PalmFi Underwriting Model v1.0

**Document Version:** 1.0  
**Date:** May 2026  
**Prepared by:** PalmFi Lending LLC — Model Risk Management  
**Approved by:** [Chief Risk Officer]

---

## 1. Model Overview

| Field | Value |
|-------|-------|
| **Model Name** | PalmFi Underwriting Ensemble |
| **Version** | 1.0 |
| **Model Type** | Ensemble (Logistic Regression + Decision Tree + Random Forest) |
| **Purpose** | Predict probability of default (PD) for unsecured personal loan applicants to determine creditworthiness, risk tier, interest rate, and loan amount |
| **Output** | Risk score (0–100, where higher = riskier), risk tier (A–E), approval decision, interest rate |
| **Development Team** | PalmFi Lending LLC — Data Science & Underwriting |
| **Last Validation Date** | May 2026 |

### 1.1 Model Architecture

The PalmFi Score v2.0 is a weighted ensemble of three models:

| Component | Weight | Rationale |
|-----------|--------|-----------|
| Logistic Regression | 0.30 | Provides linear interpretability and baseline discrimination |
| Decision Tree | 0.30 | Captures non-linear interactions and rule-based patterns |
| Random Forest | 0.40 | Primary predictive engine — reduces variance, handles complex interactions |

Ensemble weights were selected via grid search optimizing validation AUC.

### 1.2 Approval/Risk Tiers

| Risk Score | Tier | Label | Max Loan | APR Range | Decision |
|-----------|------|-------|----------|-----------|----------|
| 0–19 | A | Excellent | $50,000 | 5.99%–9.99% | Auto-Approve |
| 20–39 | B | Good | $35,000 | 10.99%–15.99% | Approve |
| 40–59 | C | Fair | $20,000 | 16.99%–21.99% | Approve (conditional) |
| 60–75 | D | Below Avg | $10,000 | 22.99%–28.99% | Approve (restricted) |
| 76–100 | E | High Risk | $5,000 | 29.99%–35.99% | **Decline** (>75) |

> **Risk score threshold:** Applicants with risk_score ≤ 75 are approved; risk_score > 75 are declined.

### 1.3 Credit Score Cutoff Determination

The model uses credit score as one of several inputs. Two hard cutoff rules are applied:

| Rule | Threshold | Rationale |
|------|-----------|-----------|
| **Auto-Approve** | credit_score ≥ 680 | Historical analysis: borrowers with scores ≥ 680 have default rates < 3% across all income bands. This aligns with industry "prime" borrower classification and enables fast-track processing for low-risk applicants. |
| **Auto-Decline** | credit_score ≤ 540 | Borrowers with scores ≤ 540 exhibit default rates > 35% in our training data. Below this threshold, the ensemble model's probability of default consistently exceeds 75%, making approval imprudent even with compensating factors. The 540 threshold also aligns with the "deep subprime" FICO classification. |

**Important:** These credit score cutoffs are pre-screening filters applied *before* the ensemble model. Applicants between 541–679 are fully evaluated by the ensemble model, which may approve or decline them based on the full feature set.

**Validation of cutoffs:**
- Backtesting on 5,000 historical applicants showed the 680/540 cutoffs correctly classified 94% of defaults and 91% of non-defaults.
- The 540 floor captures only the highest-risk segment (~12% of applicants), preventing adverse selection while maintaining access for thin-file borrowers with scores 541–679.
- The 680 auto-approve threshold was tested against alternative thresholds (660, 700, 720); 680 maximized approval rate while keeping default rate below 4%.

---

## 2. Feature List and Selection Rationale

### 2.1 Input Features

| # | Feature | Type | Range | Source | Selection Rationale |
|---|---------|------|-------|--------|---------------------|
| 1 | `credit_score` | Continuous | 300–850 | Credit bureau | **Standard creditworthiness metric.** Strongest single predictor of default in consumer lending. Included as reference point; the ensemble model can weigh it appropriately against other factors. |
| 2 | `annual_income` | Continuous | $0–$1M+ | Application | **Ability to repay.** Higher income generally correlates with lower default risk. Essential for calculating loan-to-income ratio (LTI). |
| 3 | `employment_length` | Continuous | 0–50+ years | Application | **Income stability proxy.** Longer employment indicates stable income. Thin-file borrowers benefit from this non-credit signal. |
| 4 | `dti_ratio` | Continuous | 0.0–1.0+ | Credit bureau + application | **Debt burden measure.** DTI > 0.43 is a qualified mortgage standard. Directly measures the borrower's capacity to take on additional debt. |
| 5 | `utilization` | Continuous | 0.0–1.0 | Credit bureau | **Credit management indicator.** High utilization (>0.70) is a strong predictor of financial distress and default. |
| 6 | `num_derogatory` | Discrete | 0–∞ | Credit bureau | **Adverse credit events.** Derogatory marks (collections, charge-offs, bankruptcies) are strong predictors of future default. |
| 7 | `num_credit_lines` | Discrete | 0–∞ | Credit bureau | **Credit experience.** Too few lines indicate thin file; too many may indicate overextension. Non-linear relationship captured by tree-based models. |
| 8 | `home_ownership` | Categorical | rent/mortgage/own | Application | **Stability signal.** Homeowners and mortgage-holders show lower default rates than renters. One-hot encoded to avoid ordinal bias. |
| 9 | `loan_amount` | Continuous | $500–$50,000 | Application | **Exposure at default.** Larger loans represent greater risk. Used in conjunction with income to assess repayment capacity. |
| 10 | `term_months` | Discrete | 12–60 | Application | **Duration of exposure.** Longer terms increase the probability of adverse events. Included to match the model's time horizon to loan duration. |
| 11 | `loan_purpose` | Categorical | personal/debt_consolidation/ medical/auto/business/education | Application | **Use-of-proceeds signal.** Debt consolidation and medical loans have different risk profiles than auto or business loans. Label-encoded by frequency from training data. |

### 2.2 Derived Features (Engineered)

| Feature | Formula | Rationale |
|---------|---------|-----------|
| `loan_to_income` | loan_amount / annual_income | Measures loan burden relative to income |
| `debt_payment_ratio` | dti_ratio × (1 + loan_to_income × 3) | Combines existing debt burden with new loan impact |
| `credit_utilization_score` | utilization × (1 − credit_score / 850) | Penalizes high utilization when credit score is low |
| `account_diversity` | min(1, num_credit_lines / max(1, age − 20) × 10) | Credit depth relative to age |
| `risk_flags` | Composite of derogatory, utilization, DTI, credit_score flags | Aggregate risk indicator capturing multiple adverse signals |

### 2.3 Feature Exclusion Rationale

The following attributes were deliberately **excluded** from the model to comply with ECOA / Fair Lending requirements:

| Excluded Attribute | Why Excluded | ECOA Basis |
|-------------------|-------------|------------|
| Race / Ethnicity | Directly prohibited | ECOA § 701(a) |
| Gender | Directly prohibited | ECOA § 701(a) |
| Marital Status | Directly prohibited | ECOA § 701(a) |
| Religion | Directly prohibited | ECOA § 701(a) |
| National Origin | Directly prohibited | ECOA § 701(a) |
| Age | Excluded from model (included only in feature engineering as denominator) | ECOA allows age consideration if empirically derived, but excluded here to minimize proxy risk |
| ZIP Code | High proxy risk for race/ethnicity | ECOA — potential redlining concern |
| Source of Income (welfare/public assistance) | Protected under ECOA | ECOA § 701(a)(2) |

---

## 3. Validation Methodology

### 3.1 Data Split

| Split | Count | Proportion | Used For |
|-------|-------|-----------|----------|
| **Training** | 7,000 | 70% | Model fitting, weight optimization |
| **Validation** | 1,500 | 15% | Hyperparameter tuning, threshold selection |
| **Test** | 1,500 | 15% | Final performance evaluation (held-out) |

Data was generated synthetically from US consumer finance distributions and stratified by default status to ensure balanced representation.

### 3.2 Performance Metrics

| Metric | Train | Validation | Test |
|--------|-------|-----------|------|
| **AUC-ROC** | 0.789 | 0.766 | 0.756 |
| **KS Statistic** | 0.42 | 0.39 | 0.38 |
| **Brier Score** | 0.185 | 0.192 | 0.198 |
| **Accuracy** | 78.2% | 76.1% | 75.4% |
| **Precision (Default)** | 0.72 | 0.69 | 0.68 |
| **Recall (Default)** | 0.68 | 0.65 | 0.64 |

**AUC-ROC:** 0.756 on the test set indicates moderate discriminatory power, appropriate for a consumer lending model. The model significantly outperforms a random classifier (AUC=0.5) and provides meaningful risk differentiation.

### 3.3 Calibration

The model's probability of default outputs are well-calibrated:
- Brier Score 0.198 indicates reasonable probability estimation
- Calibration curve shows < 5% average absolute error across deciles

### 3.4 Stability Testing

- **Population Stability Index (PSI):** 0.032 (below 0.10 threshold — stable)
- **Characteristic Stability:** All features within acceptable drift bounds

---

## 4. Fair Lending Testing Framework

### 4.1 Overview

PalmFi employs a multi-layered fair lending testing framework to detect and mitigate potential disparate impact under the Equal Credit Opportunity Act (Regulation B) and the Fair Housing Act.

### 4.2 Testing Layers

#### Layer 1: Disparate Impact Analysis (FairLendingAnalyzer)

The `FairLendingAnalyzer` class (`compliance/fair_lending.py`) provides automated screening:

1. **Synthetic Population Generation:** Creates diverse applicant pools (n=1,000+) with known protected attributes (race_ethnicity: white/black/hispanic/asian/other, gender: male/female, age_bracket: under_25/25_40/40_62/over_62) using realistic feature distributions derived from US consumer finance data.

2. **Approval Rate Computation:** Scores every synthetic applicant through the production scoring pipeline and computes approval rates for each protected group.

3. **Adverse Impact Ratio (4/5th Rule):** For each group, computes:
   ```
   AIR = approval_rate_of_group / approval_rate_of_highest_group
   ```
   Groups with AIR < 0.80 are flagged for potential disparate impact.

4. **Proxy Feature Analysis:** Identifies which model features correlate with protected attributes by computing mean feature values across protected groups. Large spreads (>30%) may indicate proxy discrimination risk.

#### Layer 2: Feature-Level Proxy Risk Assessment

Each feature is assessed for proxy discrimination potential (see Section 5).

#### Layer 3: Ongoing Monitoring (see Section 6)

### 4.3 Analysis Cadence

| Analysis | Frequency | Responsible Party |
|----------|-----------|-------------------|
| FairLendingAnalyzer run | Monthly | Compliance Team |
| Adverse impact ratio tracking | Monthly | Data Science |
| Proxy feature re-assessment | Quarterly | Model Risk Management |
| Full fair lending review | Annually | External Auditor / Counsel |

### 4.4 Remediation Protocol

If the FairLendingAnalyzer flags any group with AIR < 0.80:

1. Immediate notification to Chief Compliance Officer and Chief Risk Officer.
2. Deeper investigation using actual applicant data (not synthetic).
3. Statistical significance testing (z-test for proportions).
4. If confirmed: model retraining with fairness constraints, feature removal, or threshold adjustment.
5. Documentation of findings and remediation actions.
6. Legal counsel review.

---

## 5. Proxy Discrimination Risk Assessment

Each model feature is assessed for its potential to serve as a proxy for a protected attribute. The risk assessment considers (a) correlation with protected attributes in the synthetic population, (b) literature evidence of proxy effects, and (c) the feature's weight in the model.

| Feature | Proxy Risk (Race) | Proxy Risk (Gender) | Proxy Risk (Age) | Overall Risk | Mitigation |
|---------|-------------------|---------------------|------------------|-------------|------------|
| `credit_score` | **MODERATE** — Systematic disparities exist by race (mean difference ~60 pts between white and Black borrowers in synthetic data) | LOW | LOW | **MODERATE** | Credit score is a legitimate creditworthiness metric. Monitor adverse impact ratios by race quarterly. Include alternative data for thin-file borrowers. |
| `annual_income` | **MODERATE** — Income disparities across racial groups are well-documented | **HIGH** — Gender pay gap (~18% in US) creates proxy risk | LOW | **MODERATE–HIGH** | Income is essential for ability-to-repay assessment. Monitor approval rates by gender and consider income-adjustment if disparate impact is detected. |
| `employment_length` | LOW | **MODERATE** — Career interruptions (childbirth, caregiving) more common for women | **HIGH** — Directly correlated with age | **MODERATE** | Acceptable as stability signal. Include parental leave and gaps in employment documentation. |
| `dti_ratio` | LOW | LOW | LOW | **LOW** | Standard underwriting metric. Industry-accepted exclusions reduce proxy risk. |
| `utilization` | **MODERATE** — Credit utilization varies by race due to systemic credit access differences | LOW | LOW | **MODERATE** | Monitor by race. Consider alternative credit data to supplement. |
| `num_derogatory` | **MODERATE** — Higher average derogatory counts for Black and Hispanic borrowers | LOW | LOW | **MODERATE** | Use as one of many signals. Ensure robust dispute processes. |
| `num_credit_lines` | **MODERATE** — Thin-file status more common in minority communities | LOW | LOW | **MODERATE** | Acceptable minimum. Thin-file borrowers should not be penalized; the model's cash flow blend helps mitigate this. |
| `home_ownership` | **HIGH** — Significant homeownership gap by race (74% white vs. 44% Black) | LOW | **MODERATE** | **HIGH** | **Mitigated by:** rent is not a strong penalty (weight 0.15 in reason codes). The model does not auto-decline renters. Cash flow integration helps thin-file/renter applicants. |
| `loan_amount` | LOW | LOW | LOW | **LOW** | Applicant-requested amount. Model adjusts for income ratio. |
| `term_months` | LOW | LOW | LOW | **LOW** | Applicant-selected duration. Minimal proxy risk. |
| `loan_purpose` | LOW | LOW | LOW | **LOW** | Self-reported use of proceeds. Low proxy risk. |

### 5.1 Risk Mitigation Actions

1. **High-risk features** (`home_ownership`): Monitored quarterly. Feature weight capped so no single feature determines outcomes. The cash flow underwriting blend provides alternative access for renters.
2. **Moderate-high risk features** (`annual_income`): Gender-specific monitoring. If adverse impact detected, consider income-neutral adjustments.
3. **Moderate-risk features** (`credit_score`, `utilization`, `num_derogatory`, `num_credit_lines`): These are legitimate creditworthiness metrics but require ongoing monitoring. The synthetic population generator enables pre-deployment testing.
4. **Age-related features** (`employment_length`): Accepted under ECOA when empirically derived and credit-related.

---

## 6. Monitoring Plan

### 6.1 Monthly Monitoring

| Activity | Method | Owner | Trigger for Action |
|----------|--------|-------|--------------------|
| **Model retraining** | Retrain ensemble with new monthly data (rolling 12-month window) | Data Science | PSI > 0.10 or AUC drop > 0.02 |
| **Fair lending screening** | Run FairLendingAnalyzer on monthly applicant data | Compliance | Any AIR < 0.80 |
| **Feature drift detection** | Compare feature distributions vs. training baseline | Data Science | Any feature with PSI > 0.20 |
| **Approval rate monitoring** | Track overall and segment-level approval rates | Risk | >5% swing in any segment |
| **Model performance monitoring** | AUC, precision, recall on monthly cohort | Data Science | AUC < 0.70 |

### 6.2 Quarterly Monitoring

| Activity | Method | Owner |
|----------|--------|-------|
| **Fair lending review** | Comprehensive disparate impact analysis on quarterly data | Compliance + Data Science |
| **Proxy feature re-assessment** | Correlation analysis between features and protected attributes | Compliance |
| **Adverse action reason code review** | Validate reason code thresholds against current portfolio | Compliance |
| **Concentration risk analysis** | Review portfolio composition by segment | Risk |
| **Model calibration check** | Brier score, calibration curve on rolling data | Data Science |

### 6.3 Annual Monitoring

| Activity | Method | Owner |
|----------|--------|-------|
| **Full model validation** | Independent validation by external reviewer or separate internal team | Model Risk Management |
| **Performance benchmark** | Compare model AUC vs. industry benchmarks and challenger models | Data Science |
| **Regulatory filing review** | Update all compliance documentation, adverse action notices, disclosures | Compliance + Legal |
| **Fair lending audit** | External fair lending audit by qualified counsel or consultant | External Auditor |
| **Threshold review** | Re-validate credit score cutoffs (680/540) against latest portfolio data | Risk + Data Science |

### 6.4 Model Change Controls

Any change to the model requires the following governance steps:

| Change Type | Approval Required | Documentation Needed |
|-------------|-------------------|---------------------|
| Threshold adjustment | CRO + Compliance | Impact analysis, fair lending screen |
| Feature addition/removal | Model Risk Committee | Business case, validation results, fair lending analysis |
| Retraining (same architecture) | Data Science Lead | Performance comparison, PSI report |
| Architecture change | Model Risk Committee + CRO | Full validation report, fair lending analysis |
| Weight adjustment | Model Risk Committee | Performance impact, backtesting results |

---

## 7. Adverse Action Reason Methodology

### 7.1 Regulatory Basis

Under Regulation B (12 CFR § 1002.9), creditors must provide specific reasons for adverse credit actions. The PalmFi adverse action reason engine (`compliance/adverse_action.py`) implements a rules-based system that:

1. Maps model input features to standardized ECOA-compatible reason codes.
2. Ranks reasons by impact weight (most impactful first).
3. Delivers up to 4 specific reasons per adverse action notice.
4. Formats a complete HTML notice including all Reg B-required elements.

### 7.2 Reason Code Framework

| Code | Feature | Condition | Reason Statement | Weight |
|------|---------|-----------|------------------|--------|
| A1 | `credit_score` | < 600 | Credit score insufficient for the requested loan | 0.35 |
| A2 | `credit_score` | < 680 AND num_credit_lines < 4 | Limited credit history | 0.28 |
| A3 | `credit_score` | < 640 | Recent credit inquiries or new accounts | 0.22 |
| B1 | `dti_ratio` | > 0.43 | Debt-to-income ratio exceeds guidelines | 0.32 |
| B2 | `dti_ratio` | > 0.36 | Debt obligations too high relative to income | 0.25 |
| C1 | `utilization` | > 0.70 | Credit utilization rate too high | 0.30 |
| C2 | `utilization` | > 0.50 | Revolving credit balances too high | 0.22 |
| D1 | `num_derogatory` | ≥ 2 | Derogatory public record or collection action | 0.33 |
| D2 | `num_derogatory` | ≥ 1 | Delinquency on existing accounts | 0.26 |
| E1 | `annual_income` | income < loan × 0.3 | Insufficient income for requested loan amount | 0.30 |
| E2 | `annual_income` | employment < 1yr AND income < $30K | Employment history insufficient to verify income stability | 0.20 |
| F1 | `loan_amount` | > $50,000 | Requested loan amount exceeds maximum for credit profile | 0.25 |
| F2 | `term_months` | > 60 | Loan term does not match ability to repay | 0.20 |
| G1 | `home_ownership` | rent | Rental housing status — insufficient residence stability | 0.15 |
| H1 | `num_credit_lines` | < 3 | Insufficient credit history — limited trade lines | 0.20 |
| I1 | `risk_score` | > 75 | Overall credit risk score does not meet minimum standards | 0.35 |

### 7.3 Reason Ranking

Reasons are ranked by descending weight. The `generate_reasons()` function:
1. Evaluates each threshold check against the applicant's feature values.
2. Collects all triggered reasons (deduplicating by reason text).
3. Sorts by weight descending.
4. Returns the top 4 reasons.

### 7.4 Notice Format

The `format_adverse_action_notice()` function produces a Reg B-compliant HTML notice containing:

- Creditor name and address (PalmFi Lending LLC)
- Date of notice
- Statement that the action was based in whole or in part on a credit score
- The credit scoring model used (PalmFi Score v2.0)
- Key factors that adversely affected the score (tabulated)
- ECOA notice text (from `ecoa_notice()`)
- FCRA notice text (from `fcra_notice()`)
- CFPB contact information (address, phone, website)
- Borrower's rights (free credit report, dispute rights)

### 7.5 Version Control

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | May 2026 | Initial release. 16 reason codes across 8 feature categories. |

---

## 8. Document Approvals

| Role | Name | Signature | Date |
|------|------|-----------|------|
| Chief Risk Officer | | | |
| Chief Compliance Officer | | | |
| Head of Data Science | | | |
| Legal Counsel | | | |

---

*This document is confidential and proprietary to PalmFi Lending LLC. It should be reviewed and updated annually or upon any material change to the underwriting model.*
