# PalmFi — First 10 Pilot Loans Operations Guide

## Overview

This guide walks you through making your first 10 real loans. The goal is NOT to
make a profit — it's to **prove loss curves** so investors have data to lend against.

## Phase D1: Self-Funding (Recommended First)

### Budget

| Item | Cost |
|------|------|
| Loan capital pool | $15,000–$35,000 |
| Licensing (Texas) | $5,000–$8,000 |
| Legal (attorney) | $3,000–$5,000 |
| Stripe Identity KYC | ~$30 (10 borrowers × $3) |
| Domain + hosting | ~$200/yr |
| **Total** | **$23,000–$48,000** |

Time: 6-10 weeks from starting Phase A.

### Finding Pilot Borrowers

**Approach 1: Friends & Family (Easiest)**
- 3-5 people who know and trust you
- Explain it's a real loan with real terms
- Ideal: people who'd actually use a personal loan

**Approach 2: Your Network**
- Post on LinkedIn/Twitter (professionally)
- "Launching a new AI-powered lending platform in Texas — looking for 5 early borrowers. Better rates, instant decisions."
- Offer a special founder's rate (lower APR) for the first cohort

**Approach 3: Targeted (If licensed)**
- Only do this once your license is approved
- Small Facebook/Google ads targeting Texas, credit score 580-720
- Budget: $200-500 for pilot

### The Pilot Loan Process

```
Day 1:   Borrower registers at palm.ngrok.app
Day 1:   Borrower fills application (5 steps)
Day 1:   PalmFi scores, approves/declines in <50ms
Day 1:   Borrower completes KYC (Stripe Identity)
Day 1-2: Loan offer presented, borrower accepts
Day 2:   You manually fund via Mercury → borrower's bank
Day 2:   Log disbursement in admin > approve application
Day 30:  First payment due
Day 31:  Collection cycle starts if missed
```

### What to Track

For every pilot loan, log:

| Metric | Example |
|--------|---------|
| Borrower credit score | 650 |
| Loan amount | $2,500 |
| APR | 22% |
| Term | 24 months |
| Monthly payment | $130 |
| Original risk tier | C |
| Predicted default probability | 7.2% |
| Actual outcome (collecting over time) | TBD |

### Portfolio Management

After 10 loans, you'll have data like:

```
Total originated:  $25,000
Average APR:      24%
Projected revenue: $6,000 (over loan life)
Projected losses:  $1,250–$2,000 (5–8% default rate)
Net return:        $4,000–$4,750
Return on capital: 16–19%
```

This is exactly what investors want to see.

---

## Phase D2: Debt Facility (Scale)

Once you have 10 loans of performance data:

### Who to Approach

| Type | Example | Amount | Rate |
|------|---------|--------|------|
| Private credit funds | Atalaya, Victory Park | $250k–$2M | 8-12% |
| Family offices | Local wealthy families | $100k–$500k | 6-10% |
| Angel investors | Fintech-focused angels | $50k–$250k | Convertible note |
| Revenue-based financing | Pipe, Clearco | $50k–$500k | Revenue share |

### What Investors Need

1. **Proof of concept** — 10 loans showing you can originate, service, collect
2. **Loss curves** — Actual default rates vs. predicted (AUC 0.756 validation)
3. **Unit economics** — Cost per loan ($0.50), revenue per loan, margin
4. **Compliance status** — Texas license or partnership in place
5. **Growth plan** — How you'll deploy their capital profitably

### Pitch Materials Ready

Create a data room with:
- [ ] Pitch deck (generated at launch/PalmFi_Pitch_Deck.pptx)
- [ ] Loan portfolio summary (spreadsheet of pilot loans)
- [ ] Underwriting model validation (AUC curve + feature importance)
- [ ] Compliance license / partnership agreement
- [ ] Financial projections (P&L, balance sheet, cash flow)

### Recommended Facility Structure

```
Facility size:     $100,000–$250,000
Interest rate:     8-12% (paid to investor)
Term:              12 months revolving
Draw period:       6 months
First loss:        10% held by PalmFi
Origination limit: $2,500 average per loan
```

This structure protects the investor (first-loss tranche from you) while
giving you enough capital to scale to 100+ loans.

---

## Key Milestones

```
Month 1:  Phase A complete (LLC, EIN, Mercury, Stripe)
Month 2:  Phase B submitted (License application + attorney engaged)
Month 3:  Phase C complete (Domain live, KYC configured)
Month 4:  Phase D1 — First 5 pilot loans funded
Month 5:  Phase D1 — First payments collected, loss data starts
Month 6:  Phase D2 — Approach investors with 10-loan portfolio data
Month 7-9: Raise debt facility, scale to 100+ loans
Month 12: 1,000+ loan run rate, Series A fundraising
```

## Immediate Next Step

Transfer **$15,000–$25,000** from your personal account to Mercury (PalmFi LLC).
This is the loan capital. You don't need to fund all 10 loans at once — fund
1-2 at a time as borrowers come in.
