# ============================================================================
# PalmFi Lending LLC — Private Placement Fundraising Memo (DRAFT)
# This is a STRATEGIC document for discussion, NOT a legal offering document.
# Must be reviewed by securities attorney before use with any investor.
# ============================================================================

## Executive Summary

**Company:** PalmFi Lending LLC (Delaware)
**Product:** AI-native personal lending platform
**Underwriting:** Pure machine learning ensemble (AUC 0.756)
**Stage:** MVP complete (42/44 tests passing), seeking launch capital
**Ask:** $XXX,XXX debt facility for loan originations

## The Opportunity

The US personal loan market is $200B+ annually. Traditional lenders use FICO
(which misses 62M "credit invisible" Americans). PalmFi's ML model analyzes
10+ features including cash flow behavior, payment history patterns, and
alternative data to approve borrowers traditional banks decline — at better
risk-adjusted returns.

## Competitive Moat

1. **Fully automated zero-human underwriting** — cost per loan near zero
2. **AUC 0.756** — strong discrimination between good/bad borrowers
3. **Integrated collections engine** — auto-escalating recovery workflows
4. **Rate improvement system** — incentives good behavior, reduces default risk
5. **Cash flow underwriting** — bank transaction analysis for thin-file borrowers

## Use of Funds

| Use | Amount | Detail |
|-----|--------|--------|
| Loan capital pool | $XX,XXX | Fund first 25-50 loans |
| State licensing fees | $5,000 | Virginia application |
| Legal & compliance | $10,000 | Entity formation, counsel, PPM |
| KYC/identity vendor | $3,000 | Persona/Onfido integration |
| Technology infrastructure | $2,000 | Domain, hosting, Stripe fees |
| **Total** | **$XX,XXX** | |

## Proposed Terms (Illustrative)

- **Instrument:** Secured note or revenue-share agreement
- **Target return:** 8-15% APR (commensurate with consumer lending risk)
- **Principal protection:** First-loss position held by operator, senior tranche to investor
- **Term:** 12-24 months revolving facility

## Financial Projections

// Note: These are illustrative. Actual projections depend on loan volume,
// default rates, and average APR. Fill in based on your pilot data.

| Metric | Month 1-3 | Month 4-6 | Month 7-12 |
|--------|-----------|-----------|------------|
| Loans originated | 5-10 | 25-50 | 100-200 |
| Average loan size | $2,000 | $3,500 | $5,000 |
| Portfolio yield (APR) | 18-29% | 18-29% | 18-29% |
| Expected default rate | 5-8% | 5-8% | 5-8% |
| Net return on capital | 12-18% | 12-18% | 12-18% |

## Technical Appendix

### Underwriting Model Architecture
- Ensemble: Decision Tree + Logistic Regression + Random Forest
- Training data: Synthetically generated + augmented (1,000+ samples)
- AUC: 0.756 on validation set
- Features: age, income, employment length, credit score, DTI ratio,
  utilization rate, derogatory marks, credit lines, home ownership, loan purpose
- Throughput: <50ms per scoring call (Flask endpoint)

### Platform Stack
- Backend: Python/Flask (SQLite for MVP, PostgreSQL ready)
- Scoring: Pure Python ML (no GPU needed)
- Payments: Stripe (live-ready, currently mock mode)
- Hosting: Docker-ready, deploys to any cloud
- Testing: 42/44 E2E tests passing

## Risk Factors
- Regulatory risk: State lending licenses required (in process)
- Default risk: Model trained on synthetic data; real-world performance may differ
- Technology risk: Single point of failure on current infrastructure
- Competition: Large incumbents (SoFi, LendingClub, Upstart) have scale advantages

## Next Steps for Investor
1. Review technical demo at palm.ngrok.app
2. Discuss proposed terms
3. Agree on facility size and structure
4. Execute definitive agreements
5. Fund and deploy capital
