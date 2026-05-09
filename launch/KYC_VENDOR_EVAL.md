# PalmFi — KYC Vendor Evaluation

## Evaluation Criteria
- **Pricing** — cost per verification (lower is better at scale)
- **API quality** — documentation, integration effort, error handling
- **Coverage** — supported document types, countries, biometric options
- **Compliance** — meets OCCC/CISI requirements for identity verification
- **Integration complexity** — lines of code to add to PalmFi

## Vendor Comparison

| Feature | Stripe Identity | Persona | Onfido |
|---------|---------------|---------|--------|
| **Cost per verification** | $1.50–$3.00 | $1.50–$5.00 | $1.50–$4.00 |
| **Monthly minimum** | None | $500/mo (Pro plan) | None (pay as you go) |
| **Document verification** | ✅ Passport, DL, ID card | ✅ 300+ types | ✅ 250+ types |
| **Selfie/liveness check** | ✅ | ✅ | ✅ |
| **Video verification** | ❌ | ✅ | ✅ |
| **Watchlist screening** | Included (PEP/sanctions) | Optional add-on | Included |
| **AML compliance** | ✅ | ✅ | ✅ |
| **API style** | RESTful, simple | GraphQL | RESTful |
| **Stripe integration** | 🔥 Native (same dashboard) | Separate account | Separate account |
| **SDK** | Web, iOS, Android | Web, iOS, Android | Web, iOS, Android |
| **Goes live** | Same day as Stripe account | ~1-2 days | ~1-2 days |

## Recommendation

**Start with Stripe Identity** for these reasons:
1. **Zero additional onboarding** — you already use Stripe, it's under the same account
2. **No monthly minimum** — perfect for the pilot phase (5-10 borrowers)
3. **Same webhook infrastructure** — `stripe/webhook` handles everything
4. **Pay per verification** — ~$1.50 for document + selfie check
5. **Watchlist screening included** — OFAC/PEP check at no extra cost

Upgrade to **Persona** at scale if:
- You need video verification for high-risk borrowers
- You're processing 1,000+ verifications/month and want volume discounts
- Stripe Identity's document coverage is insufficient

## Integration Timeline
- **Stripe Identity:** 1-2 days of dev work
- **Persona/Onfido:** 3-5 days

## Cost Projection (Pilot Phase)

| Volume | Stripe Identity | Onfido | Persona |
|--------|----------------|--------|---------|
| 10 borrowers | $15–$30 | $15–$40 | $15–$50 |
| 50 borrowers | $75–$150 | $75–$200 | $75–$250 |
| 500 borrowers | $750–$1,500 | $750–$2,000 | $1,250–$2,500* |

*Persona Pro plan minimum $500/mo makes it more expensive at low volume

## Action
1. When your Stripe account is live with LLC documentation → enable Stripe Identity from Dashboard
2. Set webhook endpoint to `/stripe/webhook` (already built)
3. Configure verification requirements: document + selfie + watchlist
4. Start with 1-2 manual test verifications before turning on for borrowers
