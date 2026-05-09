#!/usr/bin/env python3
"""Risk-based pricing engine for personal loans."""

import math


class PricingEngine:
    """Risk-based pricing with tiered APR, fee, and loan limits."""

    TIER_RATES = {
        'A': {'min_apr': 5.99, 'max_apr': 9.99, 'max_loan': 50000, 'origination_pct': 1.0, 'label': 'Excellent'},
        'B': {'min_apr': 10.99, 'max_apr': 15.99, 'max_loan': 35000, 'origination_pct': 2.0, 'label': 'Good'},
        'C': {'min_apr': 16.99, 'max_apr': 21.99, 'max_loan': 20000, 'origination_pct': 3.0, 'label': 'Fair'},
        'D': {'min_apr': 22.99, 'max_apr': 28.99, 'max_loan': 10000, 'origination_pct': 4.0, 'label': 'Below Avg'},
        'E': {'min_apr': 29.99, 'max_apr': 35.99, 'max_loan': 5000, 'origination_pct': 5.0, 'label': 'High Risk'},
    }

    # Risk score thresholds for tiers (higher score = higher risk = worse tier)
    TIER_THRESHOLDS = [
        (0, 'A'),
        (20, 'B'),
        (40, 'C'),
        (60, 'D'),
        (80, 'E'),
    ]

    # Term options in months
    TERM_OPTIONS = [12, 24, 36, 48, 60]

    @staticmethod
    def get_risk_tier(risk_score):
        """Map risk score (0-100, higher=riskier) to letter tier."""
        for threshold, tier in sorted(PricingEngine.TIER_THRESHOLDS, key=lambda x: -x[0]):
            if risk_score >= threshold:
                return tier
        return 'E'

    @staticmethod
    def calculate_rate(risk_tier, loan_amount, term, dti_ratio):
        """Calculate APR within tier range based on loan specifics.
        
        Lower rate for: lower LTV (loan/income proxy), shorter term, lower dti
        """
        tier_config = PricingEngine.TIER_RATES.get(risk_tier, PricingEngine.TIER_RATES['E'])
        base_rate = tier_config['min_apr']
        max_rate = tier_config['max_apr']
        rate_range = max_rate - base_rate
        
        # DTI adjustment: higher dti -> higher rate within tier
        dti_factor = min(1.0, dti_ratio / 0.5)
        
        # Term adjustment: longer term -> slightly higher rate
        term_factor = min(1.0, (term - 12) / 48) * 0.3
        
        # Amount adjustment: larger loans get slight discount
        amount_factor = min(0.5, loan_amount / 100000) * 0.2
        
        rate_adjustment = dti_factor * 0.6 + term_factor - amount_factor
        rate_adjustment = max(0.0, min(1.0, rate_adjustment))
        
        apr = base_rate + rate_adjustment * rate_range
        return round(apr, 2)

    @staticmethod
    def calculate_monthly_payment(principal, apr, term_months):
        """Calculate monthly payment using amortization formula."""
        if apr == 0:
            return round(principal / term_months, 2)
        
        monthly_rate = (apr / 100.0) / 12.0
        payment = principal * (monthly_rate * (1 + monthly_rate) ** term_months) / \
                  ((1 + monthly_rate) ** term_months - 1)
        return round(payment, 2)

    @staticmethod
    def calculate_origination_fee(principal, risk_tier):
        """Calculate origination fee."""
        tier_config = PricingEngine.TIER_RATES.get(risk_tier, PricingEngine.TIER_RATES['E'])
        fee = principal * (tier_config['origination_pct'] / 100.0)
        return round(fee, 2)

    @staticmethod
    def calculate_amortization_schedule(principal, apr, term_months):
        """Generate full amortization schedule."""
        monthly_rate = (apr / 100.0) / 12.0
        monthly_payment = PricingEngine.calculate_monthly_payment(principal, apr, term_months)
        
        schedule = []
        remaining = principal
        
        for period in range(1, term_months + 1):
            interest_cents = round(remaining * monthly_rate, 2)
            principal_cents = round(monthly_payment - interest_cents, 2)
            
            if period == term_months:
                # Final payment adjustment for rounding
                principal_cents = remaining
                monthly_payment = round(principal_cents + interest_cents, 2)
            
            remaining = round(remaining - principal_cents, 2)
            if remaining < 0:
                remaining = 0.0
            
            schedule.append({
                'payment_number': period,
                'due_date': None,  # To be filled in by application
                'amount': monthly_payment,
                'principal': principal_cents,
                'interest': interest_cents,
                'remaining_balance': remaining,
                'status': 'pending',
            })
        
        return schedule

    @staticmethod
    def calculate_total_cost(principal, apr, term_months, origination_fee):
        """Calculate total cost of the loan."""
        monthly_payment = PricingEngine.calculate_monthly_payment(principal, apr, term_months)
        total_payments = monthly_payment * term_months
        total_interest = total_payments - principal
        total_cost = total_payments + origination_fee
        
        return {
            'monthly_payment': monthly_payment,
            'total_interest': round(total_interest, 2),
            'total_principal': principal,
            'total_payments': round(total_payments, 2),
            'origination_fee': origination_fee,
            'total_cost': round(total_cost, 2),
            'apr': apr,
            'term_months': term_months,
        }

    @staticmethod
    def get_available_terms():
        """Return list of available loan terms."""
        return PricingEngine.TERM_OPTIONS

    @staticmethod
    def get_risk_label(risk_tier):
        """Get human-readable risk label."""
        return PricingEngine.TIER_RATES.get(risk_tier, {}).get('label', 'Unknown')
