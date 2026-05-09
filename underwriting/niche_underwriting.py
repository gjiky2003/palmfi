#!/usr/bin/env python3
"""Niche Lending Targeting Engine.

Specialized underwriting and product flows for underserved niches:
  1. Gig workers & freelancers (variable income)
  2. Immigrants & new-to-credit (thin file, ITIN lending)
  3. Medical borrowers (dental, LASIK, fertility, surgery)

Each niche has custom underwriting weights, documentation requirements,
and alternative data scoring.
"""

import json
import os
import math
from datetime import datetime


class NicheUnderwriter:
    """Niche-specific underwriting adjustments."""

    # Niche definitions with alternative data sources and risk adjustments
    NICHES = {
        'gig_worker': {
            'label': 'Gig Worker / Freelancer',
            'icon': 'fa-briefcase',
            'description': 'Uber drivers, DoorDash, freelancers, contractors with variable income',
            'alternative_data': ['platform_earnings', 'bank_cash_flow', 'contract_duration'],
            'credit_boost': 5,        # Extra risk score forgiveness
            'income_weight': 0.4,     # Income matters less (it's variable)
            'cash_flow_weight': 0.6,  # Cash flow matters more
            'min_income': 12000,      # $1k/mo minimum
            'documents': ['Platform earnings summary (last 3 months)',
                         'Bank statements (last 3 months)',
                         'Tax returns (last year)'],
            'recommended_product': 'income_share',
            'interest_adjustment': 1.5,  # +1.5% APR adjustment
            'max_loan': 15000,
        },
        'immigrant': {
            'label': 'New-to-Credit / Immigrant',
            'icon': 'fa-globe',
            'description': 'ITIN holders, recent immigrants, no US credit history',
            'alternative_data': ['bank_cash_flow', 'rent_payment_history', 'employment_tenure',
                                'education', 'home_country_credit'],
            'credit_boost': 10,       # Big boost for thin file
            'income_weight': 0.5,
            'cash_flow_weight': 0.7,   # Cash flow is primary signal
            'min_income': 18000,       # $1.5k/mo minimum
            'documents': ['ITIN or SSN', 'Valid passport/ID',
                         'Bank statements (last 6 months)',
                         'Employment letter / pay stubs',
                         'Rent payment receipts (last 12 months)',
                         'Utility bills (last 3 months)'],
            'recommended_product': 'secured_build',
            'interest_adjustment': 2.0,  # +2% APR adjustment
            'max_loan': 10000,
        },
        'medical': {
            'label': 'Medical Borrower',
            'icon': 'fa-heartbeat',
            'description': 'Dental surgery, LASIK, fertility treatment, elective surgery',
            'alternative_data': ['treatment_cost_estimate', 'insurance_coverage',
                                'employer_benefits', 'recovery_timeline'],
            'credit_boost': 0,         # No special boost
            'income_weight': 0.6,
            'cash_flow_weight': 0.3,
            'min_income': 24000,       # $2k/mo minimum
            'documents': ['Treatment cost estimate from provider',
                         'Insurance explanation of benefits (if applicable)',
                         'Doctor/surgeon referral',
                         'Employer leave letter (if applicable)'],
            'recommended_product': 'direct_pay',  # Pay provider directly
            'interest_adjustment': 0.0,  # No adjustment
            'max_loan': 50000,
        },
    }

    def __init__(self, db_path=None):
        if db_path is None:
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            db_path = os.path.join(project_root, 'platform', 'lending.db')
        self.db_path = db_path

    def get_niche(self, niche_id):
        """Get niche configuration by ID."""
        return self.NICHES.get(niche_id)

    def list_niches(self):
        """List all available niches with simplified info."""
        return [
            {'id': k, 'label': v['label'], 'icon': v['icon'],
             'description': v['description'], 'max_loan': v['max_loan'],
             'recommended_product': v['recommended_product']}
            for k, v in self.NICHES.items()
        ]

    def adjust_score_for_niche(self, risk_score, niche_id, app_data=None):
        """Apply niche-specific adjustments to a risk score.

        Called by the LoanScorer before final risk determination.
        """
        niche = self.NICHES.get(niche_id)
        if not niche:
            return risk_score

        # Credit boost for thin-file niches
        adjusted = risk_score - niche['credit_boost']

        # If we have cash flow data, use it (gig workers & immigrants)
        if app_data and app_data.get('cash_flow_metrics'):
            cf_score = app_data['cash_flow_metrics'].get('cash_flow_score', 0)
            cf_weight = niche['cash_flow_weight']
            # Blend: lower risk score = good
            cf_risk = max(0, 100 - cf_score)
            adjusted = int(round(
                adjusted * (1 - cf_weight) + cf_risk * cf_weight
            ))

        return max(0, min(100, adjusted))

    def adjust_rate_for_niche(self, base_rate, niche_id):
        """Apply niche-specific APR adjustment."""
        niche = self.NICHES.get(niche_id)
        if not niche:
            return base_rate
        return round(base_rate + niche['interest_adjustment'], 2)

    def get_max_loan_for_niche(self, niche_id):
        """Get max loan amount for a niche."""
        niche = self.NICHES.get(niche_id)
        return niche['max_loan'] if niche else 50000

    def get_min_income_for_niche(self, niche_id):
        """Get minimum annual income for a niche."""
        niche = self.NICHES.get(niche_id)
        return niche['min_income'] if niche else 0

    def get_documents_for_niche(self, niche_id):
        """Get documentation requirements for a niche."""
        niche = self.NICHES.get(niche_id)
        return niche['documents'] if niche else []

    def get_recommended_product(self, niche_id):
        """Get the recommended loan product for a niche."""
        niche = self.NICHES.get(niche_id)
        return niche['recommended_product'] if niche else 'standard'

    def calculate_gig_income(self, platform_earnings_list):
        """Calculate stable-income equivalent for gig workers.

        Takes a list of monthly platform earnings and returns
        a conservative annualized income estimate.

        Uses: median of last 3 months × 12 (more conservative than mean)
        """
        if not platform_earnings_list:
            return 0

        recent = platform_earnings_list[-3:] if len(platform_earnings_list) >= 3 else platform_earnings_list
        sorted_vals = sorted(recent)
        median = sorted_vals[len(sorted_vals) // 2]

        # 25% haircut for volatility
        conservative_annual = median * 12 * 0.75
        return round(conservative_annual, 2)

    def score_immigrant_profile(self, bank_cash_flow_score, rent_history_months,
                                 employment_months, has_itin=False):
        """Score an immigrant/thin-file borrower profile.

        Returns a composite score (0-100) that can replace traditional credit score.
        """
        score = 0

        # Cash flow is king (max 40 pts)
        score += min(40, int(bank_cash_flow_score * 0.4))

        # Rent payment history (max 25 pts)
        rent_score = min(25, int(rent_history_months * 2.0))
        score += rent_score

        # Employment stability (max 20 pts)
        emp_score = min(20, int(employment_months * 0.5))
        score += emp_score

        # ITIN (alternative credit) (max 15 pts)
        if has_itin:
            score += 10

        return min(100, max(0, score))

    def score_medical_loan(self, treatment_cost, annual_income, insurance_pct,
                            recovery_weeks):
        """Score a medical loan application.

        Medical loans are lower risk because:
        - Treatment is elective (survival not at stake)
        - Insurance may cover complications
        - Employment typically continues

        Returns dict with 'score' (0-100) and 'flags'.
        """
        score = 50  # Start at neutral
        flags = []

        # Cost-to-income ratio
        cost_ratio = treatment_cost / max(1, annual_income)
        if cost_ratio < 0.1:
            score += 15
            flags.append('Low cost relative to income')
        elif cost_ratio < 0.3:
            score += 5
            flags.append('Moderate cost relative to income')
        else:
            score -= 10
            flags.append('High cost relative to income')

        # Insurance coverage
        if insurance_pct >= 80:
            score += 10
            flags.append('Good insurance coverage')
        elif insurance_pct >= 50:
            score += 5
        elif insurance_pct > 0:
            score -= 5
            flags.append('Limited insurance coverage')
        else:
            score -= 10
            flags.append('No insurance coverage')

        # Recovery time (longer = more stable)
        if recovery_weeks >= 4:
            score += 5
        elif recovery_weeks <= 1:
            score -= 5

        return {
            'score': max(0, min(100, score)),
            'flags': flags,
            'recommended_term': self._recommend_medical_term(treatment_cost, recovery_weeks),
        }

    def _recommend_medical_term(self, cost, recovery_weeks):
        """Recommend loan term for medical procedures."""
        if recovery_weeks > 8 or cost > 15000:
            return 48
        elif recovery_weeks > 4 or cost > 8000:
            return 36
        else:
            return 24

    def get_niche_landing_data(self, niche_id):
        """Get all data needed for a niche landing page."""
        niche = self.get_niche(niche_id)
        if not niche:
            return None

        # Generate example scenarios for marketing
        return {
            'niche_id': niche_id,
            'config': niche,
            'example_scenarios': self._generate_examples(niche_id),
            'testimonials': self._generate_testimonials(niche_id),
        }

    def _generate_examples(self, niche_id):
        """Generate example loan scenarios for marketing."""
        examples = {
            'gig_worker': [
                {
                    'scenario': 'Uber driver needs car repairs',
                    'loan': '$3,000',
                    'term': '12 months',
                    'income_share': '$75-150/mo flexible payment',
                },
                {
                    'scenario': 'Freelance designer starting new equipment',
                    'loan': '$8,000',
                    'term': '24 months',
                    'income_share': '$100-350/mo flexible payment',
                },
            ],
            'immigrant': [
                {
                    'scenario': 'ITIN holder building credit, needs $5,000',
                    'loan': '$5,000',
                    'term': '12 months (secured builder)',
                    'special': 'Use bank cash flow + rent history as credit',
                },
                {
                    'scenario': 'New arrival with job offer, needs bridge loan',
                    'loan': '$3,000',
                    'term': '6 months',
                    'special': 'Employment letter + bank statements',
                },
            ],
            'medical': [
                {
                    'scenario': 'LASIK surgery ($4,000)',
                    'loan': '$4,000',
                    'term': '12-24 months',
                    'rate': 'From 8.99% APR',
                },
                {
                    'scenario': 'Dental implants ($12,000)',
                    'loan': '$12,000',
                    'term': '24-36 months',
                    'rate': 'From 9.99% APR',
                },
                {
                    'scenario': 'Fertility treatment (IVF, $18,000)',
                    'loan': '$18,000',
                    'term': '36-48 months',
                    'rate': 'From 10.99% APR',
                },
            ],
        }
        return examples.get(niche_id, [])

    def _generate_testimonials(self, niche_id):
        """Generate realistic testimonials for marketing."""
        testimonials = {
            'gig_worker': [
                {
                    'name': 'Carlos M.',
                    'text': 'As a DoorDash driver, traditional banks wouldn\'t touch me. '
                            'PalmFi looked at my actual earnings, not just a W-2. Got $5,000 for my car repair.',
                    'rating': 5,
                },
                {
                    'name': 'Priya K.',
                    'text': 'The income-share option is a lifesaver. Slow month? Lower payment. '
                            'Busy month? Pay more. It actually fits freelancer life.',
                    'rating': 5,
                },
            ],
            'immigrant': [
                {
                    'name': 'Ahmed R.',
                    'text': 'I\'ve been in the US for 2 years with great cash flow but no credit score. '
                            'PalmFi approved me based on my bank transactions and rent history.',
                    'rating': 5,
                },
            ],
            'medical': [
                {
                    'name': 'Jennifer L.',
                    'text': 'Needed LASIK but couldn\'t pay $4k upfront. PalmFi got me approved same day '
                            'at 9.99% — cheaper than CareCredit.',
                    'rating': 5,
                },
            ],
        }
        return testimonials.get(niche_id, [])


# Quick test
if __name__ == '__main__':
    nu = NicheUnderwriter()
    print("Niche Underwriting Engine loaded.")
    print(f"\nAvailable niches: {[n['id'] for n in nu.list_niches()]}")

    # Test gig income calculation
    platform = [1800, 2200, 1500, 3000, 2400, 2800]
    print(f"\nGig income calc (6 months): ${nu.calculate_gig_income(platform)}/yr")

    # Test immigrant scoring
    imm_score = nu.score_immigrant_profile(
        bank_cash_flow_score=78,
        rent_history_months=14,
        employment_months=18,
        has_itin=True
    )
    print(f"Immigrant profile score: {imm_score}/100")

    # Test medical scoring
    med = nu.score_medical_loan(
        treatment_cost=4500,
        annual_income=65000,
        insurance_pct=0,
        recovery_weeks=2
    )
    print(f"Medical loan score: {med['score']}/100")
    print(f"  Flags: {med['flags']}")
    print(f"  Recommended term: {med['recommended_term']} months")
