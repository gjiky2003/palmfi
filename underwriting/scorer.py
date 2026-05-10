#!/usr/bin/env python3
"""Production scoring engine for credit underwriting.

PRIMARY INTERFACE for the underwriting system.
Supports:
- Main model (trained on LendingClub data) with credit bureau features
- Cash flow blending (transactions data adjusts credit score)
- Cash flow ONLY (thin-file / no bureau applicants)
"""
from __future__ import annotations

import json
import math
import os
import sys
from copy import deepcopy
from typing import Any

import numpy as np

# ── Lazy imports for cash flow scorer (avoids circular deps) ──
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)


def _import_cash_flow():
    from cash_flow_scorer import CashFlowScorer
    return CashFlowScorer()


def _import_old_models():
    from feature_engineer import CreditFeatureEngineer
    from ensemble_model import CreditEnsemble
    return CreditFeatureEngineer, CreditEnsemble


def _import_new_models():
    from train_main_model import RealDataFeatureEngineer
    from logistic_regression import LogisticRegression
    from decision_tree import DecisionTree
    return RealDataFeatureEngineer, LogisticRegression, DecisionTree


from pricing import PricingEngine


class LoanScorer:
    """Production loan scoring and pricing engine.

    Auto-detects model format (old: CreditEnsemble, new: LogReg+Tree).
    Falls back to cash flow scoring when no credit data available.
    """

    def __init__(self, model_dir: str | None = None):
        self.pricing = PricingEngine()
        self.model_loaded = False
        self.model_dir = model_dir or BASE_DIR
        self.model_format = None  # 'new' or 'old'

        # New format components
        self.engineer = None
        self.logistic = None
        self.tree = None
        self.ensemble_weights = {'logistic': 0.70, 'tree': 0.30}
        self.feature_names = None
        self.default_rate = 0.206

        # Old format components
        self._old_engineer = None
        self._old_model = None

        # Threshold
        self.threshold = 75  # risk_score <= threshold = approved

    def load(self, path: str | None = None):
        """Load model weights from JSON.

        Supports both new format (LogReg+Tree+RealDataEngineer)
        and old format (CreditEnsemble+CreditFeatureEngineer).
        """
        if path is None:
            path = os.path.join(self.model_dir, 'model_weights.json')

        if not os.path.exists(path):
            raise FileNotFoundError(
                f"Model not found at {path}. Run train_main_model.py first."
            )

        with open(path) as f:
            model_dict = json.load(f)

        # Detect format
        if 'logistic' in model_dict and 'tree' in model_dict:
            self._load_new_format(model_dict)
            self.model_format = 'new'
        elif 'ensemble' in model_dict:
            self._load_old_format(model_dict)
            self.model_format = 'old'
        else:
            raise ValueError(f"Unknown model format in {path}")

        self.model_loaded = True
        metrics = model_dict.get('metrics', {})
        print(f"Model loaded from {path}")
        print(f"  Format: {self.model_format}")
        if metrics:
            print(f"  Val AUC:  {metrics.get('val_auc', 'N/A')}")
            print(f"  Test AUC: {metrics.get('test_auc', 'N/A')}")
        return self

    def _load_new_format(self, d: dict):
        """Load new format: RealDataFeatureEngineer + LogReg + DecisionTree."""
        RealDataFE, LogisticRegression, DecisionTree = _import_new_models()

        self.engineer = RealDataFE.from_dict(d['engineer'])
        self.logistic = LogisticRegression.from_dict(d['logistic'])
        self.tree = DecisionTree.from_dict(d['tree'])
        self.ensemble_weights = d.get('ensemble_weights', {'logistic': 0.70, 'tree': 0.30})
        self.feature_names = d.get('feature_names', [])
        self.default_rate = d.get('default_rate', 0.206)

    def _load_old_format(self, d: dict):
        """Load old format: CreditFeatureEngineer + CreditEnsemble."""
        CreditFE, CreditEnsemble = _import_old_models()
        self._old_engineer = CreditFE.from_dict(d['engineer'])
        self._old_model = CreditEnsemble.from_dict(d['ensemble'])

    # ═══════════════════════════════════════════════════════════════
    #  Public scoring interface
    # ═══════════════════════════════════════════════════════════════

    def score_application(self, app_data: dict) -> dict:
        """Score a single loan application and return full decision.

        Args:
            app_data: Dict with borrower features. Required fields:
                - age, annual_income, employment_length, credit_score
                - dti_ratio, utilization, num_derogatory, num_credit_lines
                - home_ownership, loan_amount, loan_purpose
                - term_months (optional, default 36)
                - cash_flow_metrics (optional, from CashFlowAnalyzer)

        Returns:
            Dict with risk_score, tier, approval, pricing, explanation
        """
        if not self.model_loaded:
            raise RuntimeError("Model not loaded. Call .load() first.")

        if self.model_format == 'new':
            return self._score_new(app_data)
        else:
            return self._score_old(app_data)

    def score_batch(self, applications: list) -> list:
        """Score multiple applications."""
        return [self.score_application(app) for app in applications]

    # ═══════════════════════════════════════════════════════════════
    #  New format scoring (LendingClub-trained model)
    # ═══════════════════════════════════════════════════════════════

    def _score_new(self, app_data: dict) -> dict:
        """Score using the new LendingClub-trained model."""
        # Validate
        required = ['age', 'annual_income', 'employment_length', 'credit_score',
                    'dti_ratio', 'utilization', 'num_derogatory', 'num_credit_lines',
                    'home_ownership', 'loan_amount', 'loan_purpose']
        for field in required:
            if field not in app_data:
                raise ValueError(f"Missing required field: {field}")

        # Transform features
        X = self.engineer.transform([self._to_realdata_row(app_data)])

        # Ensemble prediction: logistic + tree
        log_prob = self.logistic.predict_proba(X)[0]
        tree_prob = self.tree.predict_proba(X)[0]
        prob_default = (self.ensemble_weights['logistic'] * log_prob + 
                        self.ensemble_weights['tree'] * tree_prob)

        risk_score = int(round(prob_default * 100))
        risk_score = max(0, min(100, risk_score))

        # ── Cash Flow Blend ──
        cash_flow_data = app_data.get('cash_flow_metrics')
        cash_flow_adjusted = False
        if cash_flow_data and isinstance(cash_flow_data, dict):
            cf_score = cash_flow_data.get('cash_flow_score', 50)
            cf_risk = max(0, min(100, 100 - cf_score))
            blend_weight = 0.30
            if app_data.get('credit_score', 700) < 620:
                blend_weight = 0.50  # thin-file: cash flow matters more
            blended_risk = int(round(risk_score * (1 - blend_weight) + cf_risk * blend_weight))
            if blended_risk != risk_score:
                risk_score = blended_risk
                cash_flow_adjusted = True

        # Risk tier & pricing
        return self._build_result(app_data, risk_score, prob_default, cash_flow_adjusted)

    def _to_realdata_row(self, app_data: dict) -> dict:
        """Convert app_data dict to RealDataFeatureEngineer format."""
        return {
            'age': app_data['age'],
            'annual_income': app_data['annual_income'],
            'employment_length': app_data['employment_length'],
            'credit_score': app_data['credit_score'],
            'dti_ratio': app_data['dti_ratio'],
            'utilization': app_data['utilization'],
            'num_derogatory': app_data['num_derogatory'],
            'num_credit_lines': app_data['num_credit_lines'],
            'loan_amount': app_data['loan_amount'],
            'home_ownership': app_data['home_ownership'],
            'loan_purpose': app_data['loan_purpose'],
        }

    # ═══════════════════════════════════════════════════════════════
    #  Old format scoring (backward compatibility)
    # ═══════════════════════════════════════════════════════════════

    def _score_old(self, app_data: dict) -> dict:
        """Score using the old CreditEnsemble model."""
        required = ['age', 'annual_income', 'employment_length', 'credit_score',
                    'dti_ratio', 'utilization', 'num_derogatory', 'num_credit_lines',
                    'home_ownership', 'loan_amount', 'loan_purpose']
        for field in required:
            if field not in app_data:
                raise ValueError(f"Missing required field: {field}")

        feature_dict = {k: app_data[k] for k in required}
        X = self._old_engineer.transform([feature_dict])
        prob_default = float(self._old_model.predict_proba(X)[0])
        risk_score = int(round(prob_default * 100))
        risk_score = max(0, min(100, risk_score))

        cash_flow_adjusted = False
        cf_data = app_data.get('cash_flow_metrics')
        if cf_data and isinstance(cf_data, dict):
            cf_score = cf_data.get('cash_flow_score', 50)
            cf_risk = max(0, min(100, 100 - cf_score))
            blend_weight = 0.30
            if app_data.get('credit_score', 700) < 620:
                blend_weight = 0.50
            blended = int(round(risk_score * (1 - blend_weight) + cf_risk * blend_weight))
            if blended != risk_score:
                risk_score = blended
                cash_flow_adjusted = True

        return self._build_result(app_data, risk_score, prob_default, cash_flow_adjusted)

    # ═══════════════════════════════════════════════════════════════
    #  Shared result builder
    # ═══════════════════════════════════════════════════════════════

    def _build_result(self, app_data: dict, risk_score: int,
                      prob_default: float, cash_flow_adjusted: bool) -> dict:
        """Build the final scored result dict with pricing."""
        # Risk tier
        risk_tier = self.pricing.get_risk_tier(risk_score)
        tier_config = self.pricing.TIER_RATES.get(risk_tier, self.pricing.TIER_RATES['E'])

        # Approval
        approved = risk_score <= 75
        max_allowed = tier_config['max_loan']
        if app_data['loan_amount'] > max_allowed:
            approved = False

        # Term
        term = app_data.get('term_months', 36)

        # Pricing
        interest_rate = self.pricing.calculate_rate(
            risk_tier, app_data['loan_amount'], term, app_data['dti_ratio']
        )
        monthly_payment = self.pricing.calculate_monthly_payment(
            app_data['loan_amount'], interest_rate, term
        )
        origination_fee = self.pricing.calculate_origination_fee(
            app_data['loan_amount'], risk_tier
        )
        total_cost_info = self.pricing.calculate_total_cost(
            app_data['loan_amount'], interest_rate, term, origination_fee
        )
        recommended_term = self._get_recommended_term(app_data['loan_amount'], risk_score)

        # Explanation
        explanation = self._build_explanation(app_data, risk_score, prob_default)

        return {
            'risk_score': risk_score,
            'risk_tier': risk_tier,
            'risk_label': self.pricing.get_risk_label(risk_tier),
            'approved': approved,
            'interest_rate': interest_rate,
            'max_loan_amount': max_allowed,
            'recommended_term_months': recommended_term,
            'monthly_payment': monthly_payment,
            'origination_fee': origination_fee,
            'total_cost': total_cost_info,
            'probability_of_default': round(prob_default, 4),
            'explanation': explanation,
            'cash_flow_adjusted': cash_flow_adjusted,
        }

    def _build_explanation(self, app_data: dict, risk_score: int, prob_default: float) -> dict:
        """Build human-readable explanation."""
        factors = []

        # Credit score
        cs = app_data['credit_score']
        if cs >= 740:
            cs_desc, cs_impact = 'Very good credit score', 'positive'
        elif cs >= 670:
            cs_desc, cs_impact = 'Good credit score', 'positive'
        elif cs >= 580:
            cs_desc, cs_impact = 'Fair credit score', 'neutral'
        else:
            cs_desc, cs_impact = 'Below average credit score', 'negative'
        factors.append({'factor': 'credit_score', 'impact': cs_impact,
                        'value': cs, 'description': cs_desc})

        # DTI
        dti = app_data['dti_ratio']
        if dti < 0.2:
            dti_desc, dti_impact = 'Low debt-to-income ratio', 'positive'
        elif dti < 0.36:
            dti_desc, dti_impact = 'Manageable debt-to-income ratio', 'positive'
        elif dti < 0.43:
            dti_desc, dti_impact = 'Moderate debt-to-income ratio', 'neutral'
        else:
            dti_desc, dti_impact = 'High debt-to-income ratio', 'negative'
        factors.append({'factor': 'dti_ratio', 'impact': dti_impact,
                        'value': dti, 'description': dti_desc})

        # Utilization
        util = app_data['utilization']
        if util < 0.3:
            util_desc, util_impact = 'Low credit utilization', 'positive'
        elif util < 0.6:
            util_desc, util_impact = 'Moderate credit utilization', 'neutral'
        else:
            util_desc, util_impact = 'High credit utilization', 'negative'
        factors.append({'factor': 'utilization', 'impact': util_impact,
                        'value': util, 'description': util_desc})

        # Derogatory marks
        derog = app_data['num_derogatory']
        if derog == 0:
            derog_desc, derog_impact = 'No derogatory marks', 'positive'
        elif derog <= 2:
            derog_desc, derog_impact = 'Few derogatory marks', 'neutral'
        else:
            derog_desc, derog_impact = 'Multiple derogatory marks', 'negative'
        factors.append({'factor': 'num_derogatory', 'impact': derog_impact,
                        'value': derog, 'description': derog_desc})

        # Home ownership
        home = app_data['home_ownership']
        home_impact = 'positive' if home in ('own', 'mortgage') else 'neutral'
        factors.append({'factor': 'home_ownership', 'impact': home_impact,
                        'value': home, f'description': f'Home: {home}'})

        # Loan-to-income
        income = app_data['annual_income']
        loan = app_data['loan_amount']
        lti = loan / max(1, income)
        lti_impact = 'positive' if lti < 0.2 else 'neutral' if lti < 0.4 else 'negative'
        factors.append({'factor': 'loan_to_income', 'impact': lti_impact,
                        'value': round(lti, 3),
                        'description': f'Loan is {lti*100:.0f}% of income'})

        # Sort: negative first
        impact_order = {'negative': 0, 'neutral': 1, 'positive': 2}
        factors.sort(key=lambda f: impact_order.get(f['impact'], 1))

        # Summary
        neg_count = sum(1 for f in factors if f['impact'] == 'negative')
        pos_count = sum(1 for f in factors if f['impact'] == 'positive')
        if neg_count == 0 and pos_count >= 4:
            summary = 'Strong credit profile with excellent financial health'
        elif neg_count == 0:
            summary = 'Good credit profile with manageable risk factors'
        elif neg_count <= 2 and risk_score < 50:
            summary = 'Moderate credit profile with some areas for improvement'
        elif risk_score < 60:
            summary = 'Fair credit profile with notable risk factors'
        else:
            summary = 'High-risk credit profile with several concerning factors'

        return {'top_factors': factors, 'summary': summary}

    @staticmethod
    def _get_recommended_term(loan_amount: float, risk_score: int) -> int:
        if risk_score > 70 or loan_amount < 5000:
            return 24
        elif risk_score > 50 or loan_amount < 15000:
            return 36
        elif loan_amount > 30000:
            return 48
        return 36


# ═══════════════════════════════════════════════════════════════
#  Quick test
# ═══════════════════════════════════════════════════════════════
if __name__ == '__main__':
    scorer = LoanScorer()
    model_path = os.path.join(BASE_DIR, 'model_weights.json')
    if os.path.exists(model_path):
        scorer.load()
    else:
        print("No model found. Run train_main_model.py first.")

    if scorer.model_loaded:
        app = {
            'age': 35, 'annual_income': 85000, 'employment_length': 5,
            'credit_score': 720, 'dti_ratio': 0.25, 'utilization': 0.3,
            'num_derogatory': 0, 'num_credit_lines': 8,
            'home_ownership': 'mortgage', 'loan_amount': 10000,
            'loan_purpose': 'debt_consolidation',
        }
        result = scorer.score_application(app)
        print(f"\n  Risk Score: {result['risk_score']}")
        print(f"  Approved: {result['approved']}")
        print(f"  Interest Rate: {result['interest_rate']:.2%}")
        print(f"  Tier: {result['risk_tier']} ({result['risk_label']})")
        print(f"  Monthly Payment: ${result['monthly_payment']:.2f}")
        print(f"  Explanation: {result['explanation']['summary']}")
