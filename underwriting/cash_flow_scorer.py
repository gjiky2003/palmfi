#!/usr/bin/env python3
"""
Cash Flow Underwriting Scorer
==============================
Standalone scorer for thin-file / no-bureau applicants.
Uses bank transaction data to compute risk scores without credit bureau data.

Two modes:
1. PRIMARY scorer: For applicants with NO credit score — decides purely on cash flow
2. BLEND scorer: Adjusts existing credit score — already in scorer.py

Usage:
    from cash_flow_scorer import CashFlowScorer
    cfs = CashFlowScorer()
    result = cfs.score(transactions)  # transactions = list of bank txns
    # Returns: {'risk_score': 35, 'approved': True, 'cash_flow_score': 65, ...}
"""

from __future__ import annotations

import json
import math
import os
from datetime import datetime, timedelta
from typing import Any

from cash_flow import CashFlowAnalyzer, generate_demo_transactions


class CashFlowScorer:
    """Score loan applicants using bank transaction data only.

    Uses the CashFlowAnalyzer to extract metrics, then applies a rule-based
    scoring model calibrated to match the LendingClub model's risk distribution.

    Key design decisions:
    - No AI/ML needed — cash flow underwriting is inherently rule-based
    - Uses the 7-factor framework from the FDIC's Small Dollar Lending guidelines
    - Transparent and explainable (ECOA/Reg B compliant)
    """

    def __init__(self):
        self.analyzer = CashFlowAnalyzer()
        self.name = "cash_flow_scorer"

    def score(self, transactions: list[dict]) -> dict[str, Any]:
        """Score an applicant using bank transaction data.

        Args:
            transactions: List of bank transactions (Plaid-like format)
                [{'date': '2025-01-15', 'amount': 2500.0, 'name': 'PAYROLL', ...}]

        Returns:
            Dict with risk_score, approved, cash_flow_metrics, and explanation
        """
        if not transactions or len(transactions) < 5:
            return self._empty_result("Insufficient transaction history (need ≥5 transactions)")

        # Step 1: Extract cash flow metrics
        cf_metrics = self.analyzer.analyze(transactions)
        if cf_metrics['total_transactions'] < 5:
            return self._empty_result("Insufficient valid transactions after parsing")

        # Step 2: Compute risk score from cash flow metrics
        risk_result = self._compute_risk(cf_metrics)

        # Step 3: Build explanation
        explanation = self._build_explanation(cf_metrics, risk_result)

        return {
            'risk_score': risk_result['risk_score'],
            'risk_tier': risk_result['risk_tier'],
            'approved': risk_result['approved'],
            'cash_flow_score': cf_metrics['cash_flow_score'],
            'cash_flow_metrics': cf_metrics,
            'max_loan_amount': risk_result['max_loan'],
            'recommended_term_months': risk_result.get('term', 36),
            'explanation': explanation,
            'scoring_method': 'cash_flow_only',
            'signal_strength': risk_result.get('signal_strength', 'moderate'),
        }

    def _compute_risk(self, cf: dict) -> dict:
        """Map cash flow metrics to risk score (0-100, higher = riskier)."""
        cf_score = cf['cash_flow_score']  # 0-100, higher = healthier

        # Base: invert cash flow score
        risk_score = 100 - cf_score

        # ── Additional risk modifiers ──

        # NSF events — strong signal
        if cf['nsf_count'] >= 3:
            risk_score += 20
        elif cf['nsf_count'] >= 1:
            risk_score += 10

        # Overdraft frequency
        if cf['overdraft_frequency'] > 3:
            risk_score += 15
        elif cf['overdraft_frequency'] > 1:
            risk_score += 8

        # Negative savings rate
        if cf['savings_rate'] < 0:
            risk_score += 15
        elif cf['savings_rate'] < 0.05:
            risk_score += 5

        # High housing cost ratio
        if cf['housing_ratio'] > 0.5:
            risk_score += 10

        # No paycheck confidence (irregular income)
        if cf['paycheck_confidence'] < 0.1:
            risk_score += 5

        # Low discretionary income
        if cf['discretionary_income'] <= 0:
            risk_score += 10
        elif cf['discretionary_income'] < 500:
            risk_score += 5

        # High income volatility
        if cf['income_volatility'] > 0.5:
            risk_score += 5

        # Clamp
        risk_score = max(0, min(100, risk_score))

        # Determine risk tier
        if risk_score <= 30:
            tier = 'A'
            max_loan = 40000
            signal = 'strong'
        elif risk_score <= 50:
            tier = 'B'
            max_loan = 25000
            signal = 'strong'
        elif risk_score <= 65:
            tier = 'C'
            max_loan = 15000
            signal = 'moderate'
        elif risk_score <= 75:
            tier = 'D'
            max_loan = 10000
            signal = 'weak'
        else:
            tier = 'E'
            max_loan = 5000
            signal = 'weak'

        # Approval: same threshold as main model
        approved = risk_score <= 75

        return {
            'risk_score': risk_score,
            'risk_tier': tier,
            'approved': approved,
            'max_loan': max_loan,
            'signal_strength': signal,
            'term': 36,
        }

    def _build_explanation(self, cf: dict, risk: dict) -> dict:
        """Build human-readable explanation of the cash flow decision."""
        factors = []

        # Income
        income = cf['cash_flow_income']
        factors.append({
            'factor': 'monthly_income',
            'impact': 'positive' if income >= 3000 else 'neutral' if income >= 2000 else 'negative',
            'value': income,
            'description': f'Monthly income: ${income:,.0f}',
        })

        # Savings rate
        sr = cf['savings_rate'] * 100
        factors.append({
            'factor': 'savings_rate',
            'impact': 'positive' if sr >= 10 else 'neutral' if sr >= 0 else 'negative',
            'value': sr,
            'description': f'Savings rate: {sr:.0f}%',
        })

        # Overdrafts
        od = cf['overdraft_frequency']
        factors.append({
            'factor': 'overdraft_frequency',
            'impact': 'negative' if od > 1 else 'neutral' if od > 0 else 'positive',
            'value': od,
            'description': f'Overdrafts per month: {od:.1f}',
        })

        # NSF
        nsf = cf['nsf_count']
        if nsf > 0:
            factors.append({
                'factor': 'nsf_events',
                'impact': 'negative',
                'value': nsf,
                'description': f'NSF events: {nsf}',
            })

        # Paycheck consistency
        pc = cf['paycheck_confidence']
        factors.append({
            'factor': 'income_consistency',
            'impact': 'positive' if pc >= 0.5 else 'neutral' if pc >= 0.2 else 'negative',
            'value': pc,
            'description': f'Paycheck confidence: {pc:.0%}',
        })

        # Discretionary income
        di = cf['discretionary_income']
        factors.append({
            'factor': 'discretionary_income',
            'impact': 'positive' if di >= 1000 else 'neutral' if di >= 200 else 'negative',
            'value': di,
            'description': f'Discretionary income: ${di:,.0f}/mo',
        })

        # Housing ratio
        hr = cf['housing_ratio'] * 100
        factors.append({
            'factor': 'housing_ratio',
            'impact': 'positive' if hr < 28 else 'neutral' if hr < 36 else 'negative',
            'value': hr,
            'description': f'Housing cost ratio: {hr:.0f}% of income',
        })

        # Sort: negative first
        impact_order = {'negative': 0, 'neutral': 1, 'positive': 2}
        factors.sort(key=lambda f: impact_order.get(f['impact'], 1))

        # Summary
        neg_count = sum(1 for f in factors if f['impact'] == 'negative')
        if risk['approved'] and neg_count <= 1:
            summary = 'Strong cash flow profile'
        elif risk['approved']:
            summary = 'Adequate cash flow with some risk factors'
        else:
            summary = 'Insufficient cash flow — multiple risk signals detected'

        return {'top_factors': factors, 'summary': summary}

    def _empty_result(self, reason: str) -> dict:
        return {
            'risk_score': 100,
            'risk_tier': 'E',
            'approved': False,
            'cash_flow_score': 0,
            'cash_flow_metrics': self.analyzer._empty_metrics(),
            'max_loan_amount': 0,
            'explanation': {'summary': reason, 'top_factors': []},
            'scoring_method': 'cash_flow_only',
            'error': reason,
        }

    def generate_demo_applicants(self) -> list[dict]:
        """Generate demo applicants with known profiles for testing."""
        profiles = ['good', 'average', 'thin', 'gig_worker', 'risky']
        results = []
        for prof in profiles:
            txns = generate_demo_transactions(prof)
            result = self.score(txns)
            result['_profile'] = prof
            results.append(result)
        return results


# ---------------------------------------------------------------------------
# Integration: combined scoring with automatic fallback
# ---------------------------------------------------------------------------

class CombinedScorer:
    """Scores applicants using credit data if available, falls back to cash flow.

    Tier 1: Full credit data available → use main model (LendingClub-trained)
    Tier 2: Partial credit data → use main model + cash flow blend
    Tier 3: No credit data → use cash flow only
    """

    def __init__(self):
        self.cash_flow_scorer = CashFlowScorer()
        self.main_model = None  # Lazy-loaded

    def _load_main_model(self):
        """Load the main LendingClub-trained model."""
        from scorer import LoanScorer
        self.main_model = LoanScorer()
        try:
            self.main_model.load()
        except FileNotFoundError:
            self.main_model = None

    def score(self, transactions: list[dict] | None = None,
              app_data: dict | None = None) -> dict:
        """Score with automatic fallback.

        Args:
            transactions: Bank transactions (for cash flow analysis)
            app_data: Traditional credit application data (for main model)

        Returns:
            Scored result with appropriate method noted
        """
        has_credit_data = app_data and all(
            k in app_data for k in ['credit_score', 'annual_income', 'dti_ratio']
        )
        has_cash_flow = transactions and len(transactions) >= 5

        if has_credit_data:
            # Tier 1 or 2: Main model ± cash flow blend
            if self.main_model is None:
                self._load_main_model()

            if self.main_model and self.main_model.model_loaded:
                # Compute cash flow metrics if available
                if has_cash_flow:
                    cf = self.cash_flow_scorer.analyzer.analyze(transactions)
                    app_data['cash_flow_metrics'] = cf

                result = self.main_model.score_application(app_data)
                result['scoring_method'] = (
                    'credit_cash_flow_blend' if has_cash_flow else 'credit_only'
                )
                return result
            else:
                # Model not loaded — fall through
                pass

        if has_cash_flow:
            # Tier 3: Cash flow only
            result = self.cash_flow_scorer.score(transactions)
            return result

        # No data at all
        return {
            'risk_score': 100, 'approved': False,
            'explanation': {'summary': 'Insufficient data to score application'},
            'scoring_method': 'none',
        }


# ---------------------------------------------------------------------------
# Quick test
# ---------------------------------------------------------------------------
if __name__ == '__main__':
    print("=" * 60)
    print("  CASH FLOW SCORER — DEMO")
    print("=" * 60)

    cfs = CashFlowScorer()
    results = cfs.generate_demo_applicants()

    for r in results:
        profile = r.pop('_profile')
        print(f"\n  Profile: {profile}")
        print(f"  Risk Score: {r['risk_score']} | Approved: {r['approved']}")
        print(f"  Cash Flow Score: {r['cash_flow_score']}")
        print(f"  Cash Flow Income: ${r['cash_flow_metrics']['cash_flow_income']:.0f}/mo")
        print(f"  Explanation: {r['explanation']['summary']}")
        cf = r['cash_flow_metrics']
        print(f"  Details: savings={cf['savings_rate']:.1%} "
              f"overdrafts={cf['overdraft_frequency']:.1f}/mo "
              f"paycheck_conf={cf['paycheck_confidence']:.0%} "
              f"discretionary=${cf['discretionary_income']:.0f}")

    print("\n" + "=" * 60)
    print("  DONE — Cash Flow Scorer Ready")
    print("=" * 60)
