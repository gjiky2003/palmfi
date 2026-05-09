#!/usr/bin/env python3
"""Income-Share Hybrid Loan Engine.

Combines fixed loan payments with income-share flexibility.
Borrowers can switch between:
  - Standard mode: fixed monthly payment (traditional loan)
  - Income-share mode: pay a % of income (flexible, capped)

When income is low, the payment is lower; when income recovers,
the borrower pays more to catch up. Never more than 150% of standard.

This makes loans viable for gig workers, freelancers, and
borrowers with variable income.
"""

import json
import os
import math
from datetime import datetime, timedelta


class IncomeShareEngine:
    """Manages income-share hybrid loan features."""

    # Default income share percentages by risk tier
    TIER_SHARE_PCT = {
        'A': 5.0,   # Excellent: 5% of monthly income
        'B': 7.0,   # Good: 7%
        'C': 10.0,  # Fair: 10%
        'D': 12.0,  # Below avg: 12%
        'E': 15.0,  # High risk: 15%
    }

    # Safety limits
    MAX_PAYMENT_MULTIPLIER = 1.5   # Never pay >150% of standard payment
    MIN_INCOME_FLOOR = 500         # Assume minimum $500/mo income
    MAX_MISSED_PAYMENTS = 3        # Before reverting to standard

    # Catch-up period after income-share use
    CATCH_UP_MONTHS = 12           # Spread deficit over 12 months

    def __init__(self, db_path=None):
        if db_path is None:
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            db_path = os.path.join(project_root, 'platform', 'lending.db')
        self.db_path = db_path

    def get_conn(self):
        import sqlite3
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def calculate_income_share_payment(self, monthly_income, loan_id):
        """Calculate the income-share payment for a given monthly income.

        Args:
            monthly_income: Borrower's self-reported monthly income
            loan_id: The loan ID

        Returns:
            Dict with income_share_payment, standard_payment, savings, tier_pct
        """
        conn = self.get_conn()

        loan = conn.execute(
            "SELECT l.*, a.risk_tier FROM loans l "
            "LEFT JOIN applications a ON l.application_id = a.id "
            "WHERE l.id=?", (loan_id,)
        ).fetchone()

        if not loan:
            conn.close()
            return None

        loan = dict(loan)

        # Floor income
        effective_income = max(self.MIN_INCOME_FLOOR, monthly_income)

        # Get share percentage based on risk tier
        tier = loan.get('risk_tier', 'C')
        share_pct = self.TIER_SHARE_PCT.get(tier, 10.0)

        # Calculate income-share payment
        is_payment = round(effective_income * (share_pct / 100.0), 2)

        # Standard payment for comparison
        standard_payment = float(loan['monthly_payment'])

        # Apply cap: never more than MAX_MULTIPLIER * standard
        capped_payment = min(is_payment, standard_payment * self.MAX_PAYMENT_MULTIPLIER)

        # Calculate deficit/surplus vs standard
        deficit = round(standard_payment - capped_payment, 2)

        conn.close()

        return {
            'loan_id': loan_id,
            'monthly_income': effective_income,
            'share_pct': share_pct,
            'risk_tier': tier,
            'income_share_payment': capped_payment,
            'standard_payment': standard_payment,
            'savings_this_month': round(max(0, deficit), 2),
            'extra_cost_this_month': round(max(0, -deficit), 2),
            'payment_mode': 'income_share' if deficit > 0 else 'standard_plus',
            'is_below_standard': deficit > 0,
        }

    def calculate_catch_up_plan(self, deficit_total, remaining_term):
        """Calculate a catch-up plan for accrued deficit.

        Args:
            deficit_total: Total amount underpaid during income-share period
            remaining_term: Months remaining on loan

        Returns:
            Dict with catch_up_options
        """
        if deficit_total <= 0:
            return {'needed': False, 'message': 'No deficit to catch up'}

        # Option 1: Spread over remaining term
        spread_months = min(self.CATCH_UP_MONTHS, remaining_term)
        monthly_catchup = round(deficit_total / spread_months, 2) if spread_months > 0 else deficit_total

        # Option 2: Extend term by N months
        extension_months = min(int(deficit_total / 50) + 1, 6)  # ~$50/mo extra payment
        extended_monthly = round(deficit_total / (remaining_term + extension_months), 2) if remaining_term > 0 else deficit_total

        return {
            'needed': True,
            'deficit_total': round(deficit_total, 2),
            'remaining_term': remaining_term,
            'spread_option': {
                'description': f'Spread over {spread_months} months',
                'extra_per_month': monthly_catchup,
                'total_months': spread_months,
                'new_payment': 'See standard + extra',
            },
            'extend_option': {
                'description': f'Extend term by {extension_months} months',
                'extra_per_month': extended_monthly,
                'term_extension': extension_months,
            },
        }

    def simulate_income_share_scenario(self, loan_amount, interest_rate, term_months,
                                       monthly_incomes, risk_tier='C'):
        """Simulate what a loan would look like under income-share.

        Args:
            loan_amount: Principal
            interest_rate: APR
            term_months: Loan term
            monthly_incomes: List of monthly incomes for each month
            risk_tier: Risk tier for share percentage

        Returns:
            Dict with full simulation results
        """
        from pricing import PricingEngine

        engine = PricingEngine()
        share_pct = self.TIER_SHARE_PCT.get(risk_tier, 10.0)
        standard_payment = engine.calculate_monthly_payment(loan_amount, interest_rate, term_months)

        results = []
        total_standard = 0
        total_is_paid = 0
        total_deficit = 0

        for month, income in enumerate(monthly_incomes, 1):
            effective_income = max(self.MIN_INCOME_FLOOR, income)
            is_payment = round(effective_income * (share_pct / 100.0), 2)
            capped = min(is_payment, standard_payment * self.MAX_PAYMENT_MULTIPLIER)
            deficit = round(standard_payment - capped, 2)

            total_standard += standard_payment
            total_is_paid += capped
            total_deficit += max(0, deficit)

            results.append({
                'month': month,
                'income': income,
                'standard_payment': standard_payment,
                'income_share_payment': capped,
                'deficit': round(max(0, deficit), 2),
                'savings': round(max(0, -deficit), 2),
                'payment_mode': 'income_share' if deficit > 0 else 'standard_plus',
            })

        return {
            'loan_amount': loan_amount,
            'interest_rate': interest_rate,
            'term_months': term_months,
            'share_pct': share_pct,
            'risk_tier': risk_tier,
            'standard_payment': standard_payment,
            'total_standard_payments': round(total_standard, 2),
            'total_is_paid': round(total_is_paid, 2),
            'total_deficit': round(total_deficit, 2),
            'total_savings': round(total_standard - total_is_paid, 2),
            'monthly_results': results,
            'catch_up': self.calculate_catch_up_plan(total_deficit, term_months),
        }

    def get_borrower_income_share_status(self, borrower_id):
        """Get income-share eligibility and current status for a borrower."""
        conn = self.get_conn()
        loan = conn.execute(
            "SELECT l.*, a.risk_tier FROM loans l "
            "LEFT JOIN applications a ON l.application_id = a.id "
            "WHERE l.borrower_id=? AND l.status='active' "
            "ORDER BY l.id DESC LIMIT 1",
            (borrower_id,)
        ).fetchone()
        conn.close()

        if not loan:
            return None

        loan = dict(loan)
        tier = loan.get('risk_tier', 'C')
        share_pct = self.TIER_SHARE_PCT.get(tier, 10.0)
        standard_payment = float(loan['monthly_payment'])

        return {
            'has_active_loan': True,
            'loan_id': loan['id'],
            'risk_tier': tier,
            'share_pct': share_pct,
            'standard_payment': standard_payment,
            'income_share_min_payment': round(max(self.MIN_INCOME_FLOOR * (share_pct / 100.0), 25), 2),
            'eligible': True,
        }


# Quick test
if __name__ == '__main__':
    ise = IncomeShareEngine()
    print("Income-Share Engine loaded.")

    # Simulate a gig worker with variable income
    incomes = [2500, 3200, 1800, 4000, 2100, 3500, 2800, 1500, 3800, 3000, 2200, 4100]
    sim = ise.simulate_income_share_scenario(
        loan_amount=10000,
        interest_rate=12.99,
        term_months=24,
        monthly_incomes=incomes,
        risk_tier='C'
    )
    print(f"\nSimulation: $10,000 @ 12.99% over 24 months")
    print(f"  Standard payment: ${sim['standard_payment']}/mo")
    print(f"  Total under income-share: ${sim['total_is_paid']}")
    print(f"  Total saved: ${sim['total_savings']}")
    print(f"  Total deficit to catch up: ${sim['total_deficit']}")
    print(f"  Catch-up: {sim['catch_up']}")
