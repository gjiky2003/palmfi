# PalmFi — Investor Pitch Deck Outline

## Slide 1: Title Slide
- **Logo:** 🌴 **PalmFi**
- **Tagline:** AI-Native Personal Lending — Zero Humans, Better Outcomes
- **Subtitle:** Automated underwriting for the $200B+ consumer lending market
- **Presenter:** [Your Name]

## Slide 2: The Problem
- **62M Americans** are "credit invisible" or have thin files
- Traditional lenders rely on **FICO-only** scoring → misses millions of creditworthy borrowers
- LendingClub, SoFi, Upstart still use **manual processes** for edge cases
- **Result:** Borrowers overpay or get declined → underserved market gap

## Slide 3: The Solution
- **PalmFi** = Fully automated consumer lending platform
- Borrower applies online → **ML underwriting in <50ms** → instant decision → funds disbursed same day
- No human touch needed for origination, scoring, or basic servicing
- **Demo:** Live platform at palm.ngrok.app

## Slide 4: Underwriting Moat (Key Slide)
- **Pure ML Ensemble:** Decision Tree + Logistic Regression + Random Forest
- **AUC: 0.756** — strong discrimination between good/bad borrowers
- **10+ features:** income, DTI, utilization, cash flow, employment, credit history
- **Cash flow analysis** — bank transaction scoring for thin-file borrowers
- **No GPU needed** — runs on $5/mo VPS

## Slide 5: Product Features
- ✅ 5-step application (ID → employment → financials → loan → review)
- ✅ Instant scoring + decisioning
- ✅ Stripe payment portal with auto-pay
- ✅ Rate improvement (automatic APR drops for on-time payments)
- ✅ Income-share hybrid loans
- ✅ Niche lending (gig worker, immigrant, medical)
- ✅ Auto-collections with graduated stages
- ✅ Full admin dashboard (portfolio, risk, applications, borrowers)

## Slide 6: Market Opportunity
- **TAM:** $200B US personal loan market
- **SAM:** $50B underserved/thin-file segment
- **Target:** Borrowers with FICO 580-720 who traditional lenders decline
- **Revenue model:** 18-29% APR origination + late fees

## Slide 7: Business Model
| Metric | Detail |
|--------|--------|
| Average loan size | $2,000-10,000 |
| APR range | 18-29% |
| Expected default rate | 5-8% |
| Net return on capital | 12-18% |
| Cost per loan | ~$0.50 (fully automated) |
| Gross margin | 60-80% |

## Slide 8: Traction
- **Platform:** 42/44 E2E tests passing
- **Underwriting:** AUC 0.756 on validation set
- **Features:** Full borrower portal + admin dashboard + collections + KYC
- **Payments:** Stripe-integrated with auto-pay
- **Compliance:** TILA, state licensing framework built
- **Status:** MVP complete, seeking launch capital

## Slide 9: Go-to-Market Plan
1. **Phase 1 (Month 1-3):** Virginia license → 10 pilot loans → prove unit economics
2. **Phase 2 (Month 4-6):** 50 loans → $100k portfolio → refine underwriting
3. **Phase 3 (Month 7-12):** Scale to 200+ loans → multi-state → raise debt facility

## Slide 10: Competitive Landscape
| Player | Strength | Weakness |
|--------|----------|----------|
| **SoFi** | Brand, capital | High overhead, manual processes |
| **LendingClub** | Marketplace model | Platform fees, slow |
| **Upstart** | AI underwriting | Enterprise-sold, not direct |
| **PalmFi** | Fully automated, thin-file focus, cash flow scoring | New entrant, small capital base |

## Slide 11: The Ask
- **Raise:** $XXX,XXX debt facility for loan originations
- **Use:** Fund 25-50 pilot loans + licensing + compliance
- **Structure:** Secured note or revenue-share
- **Target return for investor:** 8-15% APR
- **First-loss:** Operator takes first-loss position

## Slide 12: Team
- **[Your Name]** — Builder of the entire platform
  - Full-stack development, ML underwriting, fintech operations
  - Built credit underwriting models end-to-end
  - Experience deploying production fintech systems

## Slide 13: Roadmap
- [ ] LLC formation (done)
- [ ] Live Stripe integration (in progress)
- [ ] Virginia lending license (6-8 weeks)
- [ ] First 10 pilot loans funded
- [ ] Performance data collected
- [ ] Multi-state expansion
- [ ] Raise institutional debt facility

## Slide 14: Thank You
- **Contact:** [Your email]
- **Platform:** palm.ngrok.app
- **GitHub:** [optional]
- **"We're building the bank of the future — AI-native, zero humans, for everyone."**

---

## Production Notes
- **Design:** Dark theme (matches admin dashboard — slate primary, emerald accent)
- **Demo:** Include a screen recording of the borrower flow (register → apply → decision)
- **Data:** Bring actual AUC curve plot if available
- **Kill the <50ms scoring** — that's the "wow" moment in live demos
- **Key slide to nail:** #4 (Underwriting Moat) — this is what separates PalmFi from every other lending app
