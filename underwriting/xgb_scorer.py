#!/usr/bin/env python3
"""XGBoost production scorer for credit underwriting.

Loads the XGBoost model (model_xgb.json) + metadata (model_weights_xgb.json)
and provides score_application() with the same output schema as the existing
LoanScorer. Also supports SHAP-based explanations via get_shap_values().

Usage:
    scorer = XGBoostScorer()
    scorer.load()
    result = scorer.score_application(app_data)
    shap_values = scorer.get_shap_values(app_data)
"""
from __future__ import annotations

import json
import math
import os
import sys
from typing import Any

import numpy as np

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from pricing import PricingEngine


class XGBoostScorer:
    """Production XGBoost scoring wrapper.

    Loads model_xgb.json + model_weights_xgb.json; transforms raw
    app_data dict into the 12-feature vector expected by the model;
    and returns the same output schema as LoanScorer.
    """

    def __init__(self, model_dir: str | None = None):
        self.pricing = PricingEngine()
        self.model_dir = model_dir or BASE_DIR
        self.model_loaded = False

        # XGBoost model + metadata
        self.model = None
        self.explainer = None
        self.feature_names: list[str] = []
        self.home_ownership_map: dict[str, int] = {}
        self.metrics: dict[str, float] = {}
        self.default_rate: float = 0.206
        self.shap_baseline: float = 0.0

        # Threshold (same as LoanScorer)
        self.threshold = 75  # risk_score <= threshold = approved

    def load(self, model_path: str | None = None,
             meta_path: str | None = None) -> XGBoostScorer:
        """Load XGBoost model and metadata.

        Args:
            model_path: Path to model_xgb.json (default: model_dir/model_xgb.json)
            meta_path: Path to model_weights_xgb.json (default: model_dir/model_weights_xgb.json)

        Returns:
            self for chaining.
        """
        import xgboost as xgb

        if model_path is None:
            model_path = os.path.join(self.model_dir, 'model_xgb.json')
        if meta_path is None:
            meta_path = os.path.join(self.model_dir, 'model_weights_xgb.json')

        if not os.path.exists(model_path):
            raise FileNotFoundError(
                f"XGBoost model not found at {model_path}. "
                "Run train_xgb_model.py first."
            )
        if not os.path.exists(meta_path):
            raise FileNotFoundError(
                f"Metadata not found at {meta_path}. "
                "Run train_xgb_model.py first."
            )

        # Load metadata
        with open(meta_path) as f:
            meta: dict = json.load(f)

        self.feature_names = meta.get('feature_names', [])
        self.home_ownership_map = meta.get('home_ownership_map', {})
        self.metrics = meta.get('metrics', {})
        self.default_rate = meta.get('default_rate', 0.206)
        self.shap_baseline = meta.get('shap_baseline', 0.0)

        # Load XGBoost model
        self.model = xgb.Booster()
        self.model.load_model(model_path)

        # Attempt to load SHAP TreeExplainer
        self._init_shap_explainer()

        self.model_loaded = True

        print(f"XGBoost model loaded from {model_path}")
        print(f"  Features: {len(self.feature_names)}")
        if self.metrics:
            print(f"  Val AUC:  {self.metrics.get('val_auc', 'N/A')}")
            print(f"  Test AUC: {self.metrics.get('test_auc', 'N/A')}")
        if self.explainer is not None:
            print("  SHAP explainer: ready")
        else:
            print("  SHAP explainer: not available")

        return self

    def _init_shap_explainer(self) -> None:
        """Initialise SHAP TreeExplainer from the loaded model.

        Gracefully handles missing shap/pandas dependencies.
        """
        if self.model is None:
            return
        try:
            import shap  # type: ignore[import-untyped]
            self.explainer = shap.TreeExplainer(self.model)
        except Exception:
            self.explainer = None

    # ═══════════════════════════════════════════════════════════════
    #  Public scoring interface
    # ═══════════════════════════════════════════════════════════════

    def score_application(self, app_data: dict) -> dict:
        """Score a single loan application and return full decision.

        Args:
            app_data: Dict with borrower features. Required fields:
                - credit_score, dti_ratio, utilization
                - num_derogatory, num_credit_lines
                - age, annual_income, employment_length, loan_amount
                - home_ownership
                - term_months (optional, default 36)

        Returns:
            Dict with risk_score, risk_tier, approved, interest_rate,
            monthly_payment, max_loan_amount, explanation,
            probability_of_default, and other pricing fields.
        """
        if not self.model_loaded:
            raise RuntimeError(
                "Model not loaded. Call .load() first."
            )

        # ── Validate required fields ──
        required = [
            'credit_score', 'dti_ratio', 'utilization',
            'num_derogatory', 'num_credit_lines',
            'age', 'annual_income', 'employment_length',
            'loan_amount', 'home_ownership',
        ]
        for field in required:
            if field not in app_data:
                raise ValueError(f"Missing required field: {field}")

        # ── Transform to feature vector ──
        feature_vector = self._build_feature_vector(app_data)

        # ── Predict ──
        prob_default = self._predict(feature_vector)

        # ── Risk score (0-100) ──
        risk_score = int(round(prob_default * 100))
        risk_score = max(0, min(100, risk_score))

        # ── FICO Gap Penalty ──
        # Model was trained on LendingClub data (FICO 660-845).
        # Scores below 660 are out-of-distribution and the model
        # underestimates risk. Apply a penalty:
        #   +0.3 risk points for each FICO point below 660
        fico = app_data.get('credit_score', 700)
        if fico < 660:
            penalty = int(round((660 - fico) * 0.3))
            risk_score = max(0, min(100, risk_score + penalty))

        # ── Cash Flow Blend (same logic as LoanScorer) ──
        cash_flow_adjusted = False
        cash_flow_data = app_data.get('cash_flow_metrics')
        if cash_flow_data and isinstance(cash_flow_data, dict):
            cf_score = cash_flow_data.get('cash_flow_score', 50)
            cf_risk = max(0, min(100, 100 - cf_score))
            blend_weight = 0.30
            if app_data.get('credit_score', 700) < 620:
                blend_weight = 0.50
            blended_risk = int(round(
                risk_score * (1 - blend_weight) + cf_risk * blend_weight
            ))
            if blended_risk != risk_score:
                risk_score = blended_risk
                cash_flow_adjusted = True

        # ── Build result ──
        return self._build_result(
            app_data, risk_score, prob_default, cash_flow_adjusted
        )

    def score_batch(self, applications: list[dict]) -> list[dict]:
        """Score multiple applications."""
        return [self.score_application(app) for app in applications]

    # ═══════════════════════════════════════════════════════════════
    #  Feature transformation
    # ═══════════════════════════════════════════════════════════════

    def _build_feature_vector(self, app_data: dict) -> np.ndarray:
        """Transform raw app_data dict into the 12-feature model vector.

        Feature order (must match training):
            credit_score, dti_ratio, utilization, num_derogatory,
            num_credit_lines, age, log_income, employment_length,
            log_loan_amount, home_rent, home_mortgage, home_own

        Returns:
            1D numpy array of shape (12,).
        """
        # Numeric base features
        credit_score = float(app_data['credit_score'])
        dti_ratio = float(app_data['dti_ratio'])
        utilization = float(app_data['utilization'])
        num_derogatory = float(app_data['num_derogatory'])
        num_credit_lines = float(app_data['num_credit_lines'])
        age = float(app_data['age'])
        employment_length = float(app_data['employment_length'])

        # Derived log features (matching training logic)
        annual_income = float(app_data['annual_income'])
        loan_amount = float(app_data['loan_amount'])
        log_income = np.log10(max(1000.0, annual_income))
        log_loan_amount = np.log10(max(100.0, loan_amount))

        # One-hot home ownership
        home_ownership = str(app_data['home_ownership'])
        home_idx = self.home_ownership_map.get(home_ownership, 2)
        home_oh = [0.0, 0.0, 0.0]
        home_oh[home_idx] = 1.0

        # Assemble in training order
        base = [
            credit_score,
            dti_ratio,
            utilization,
            num_derogatory,
            num_credit_lines,
            age,
            log_income,
            employment_length,
            log_loan_amount,
        ]
        # CAT_FEATURES = ['home_rent', 'home_mortgage', 'home_own']
        # home_oh[0]=home_rent, home_oh[1]=home_mortgage, home_oh[2]=home_own
        features = base + home_oh

        return np.array(features, dtype=np.float64)

    # ═══════════════════════════════════════════════════════════════
    #  Prediction
    # ═══════════════════════════════════════════════════════════════

    def _predict(self, feature_vector: np.ndarray) -> float:
        """Run XGBoost prediction on a single feature vector.

        Args:
            feature_vector: 1D numpy array of shape (12,).

        Returns:
            Probability of default (float 0-1).
        """
        import xgboost as xgb

        # Reshape to (1, n_features) for single-row DMatrix
        dmat = xgb.DMatrix(feature_vector.reshape(1, -1))
        prob = float(self.model.predict(dmat)[0])
        return prob

    # ═══════════════════════════════════════════════════════════════
    #  SHAP values
    # ═══════════════════════════════════════════════════════════════

    def get_shap_values(self, app_data: dict) -> dict[str, Any]:
        """Compute SHAP values for a single application.

        Args:
            app_data: Raw application dict (same as score_application).

        Returns:
            Dict with:
                - 'base_value': float (expected model output — log-odds)
                - 'values': list of dicts with 'feature', 'value', 'shap_value'
                - 'prediction': float (probability of default)

        Raises:
            RuntimeError: If SHAP explainer is not available.
        """
        if self.explainer is None:
            raise RuntimeError(
                "SHAP explainer not available. "
                "Ensure shap and pandas are installed."
            )

        feature_vector = self._build_feature_vector(app_data)
        # SHAP expects 2D input
        shap_values = self.explainer.shap_values(feature_vector.reshape(1, -1))

        # shap_values shape: (1, n_features) for binary logistic
        sv = shap_values[0]  # shape (12,)
        base_value = float(
            self.explainer.expected_value
            if not isinstance(self.explainer.expected_value, (list, np.ndarray))
            else self.explainer.expected_value[0]
        )

        # Prediction
        prob = self._predict(feature_vector)

        values = []
        for i, fname in enumerate(self.feature_names):
            values.append({
                'feature': fname,
                'value': float(feature_vector[i]),
                'shap_value': float(sv[i]),
            })

        # Sort by absolute SHAP value descending
        values.sort(key=lambda x: abs(x['shap_value']), reverse=True)

        return {
            'base_value': base_value,
            'values': values,
            'prediction': prob,
        }

    # ═══════════════════════════════════════════════════════════════
    #  Result builder (mirrors LoanScorer._build_result)
    # ═══════════════════════════════════════════════════════════════

    def _build_result(self, app_data: dict, risk_score: int,
                      prob_default: float,
                      cash_flow_adjusted: bool = False) -> dict:
        """Build the final scored result dict with pricing."""
        # Risk tier
        risk_tier = self.pricing.get_risk_tier(risk_score)
        tier_config = self.pricing.TIER_RATES.get(
            risk_tier, self.pricing.TIER_RATES['E']
        )

        # Approval
        approved = risk_score <= self.threshold
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
        recommended_term = self._get_recommended_term(
            app_data['loan_amount'], risk_score
        )

        # Explanation
        explanation = self._build_explanation(
            app_data, risk_score, prob_default
        )

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

    # ═══════════════════════════════════════════════════════════════
    #  Explanation builder
    # ═══════════════════════════════════════════════════════════════

    @staticmethod
    def _build_explanation(app_data: dict, risk_score: int,
                           prob_default: float) -> dict:
        """Build human-readable explanation with factor descriptions.

        Mirrors LoanScorer._build_explanation using the same logic
        and factor descriptions.
        """
        factors = []

        # ── Credit score ──
        cs = app_data['credit_score']
        if cs >= 740:
            cs_desc, cs_impact = 'Very good credit score', 'positive'
        elif cs >= 670:
            cs_desc, cs_impact = 'Good credit score', 'positive'
        elif cs >= 580:
            cs_desc, cs_impact = 'Fair credit score', 'neutral'
        else:
            cs_desc, cs_impact = 'Below average credit score', 'negative'
        factors.append({
            'factor': 'credit_score', 'impact': cs_impact,
            'value': cs, 'description': cs_desc,
        })

        # ── DTI ratio ──
        dti = app_data['dti_ratio']
        if dti < 0.2:
            dti_desc, dti_impact = 'Low debt-to-income ratio', 'positive'
        elif dti < 0.36:
            dti_desc, dti_impact = 'Manageable debt-to-income ratio', 'positive'
        elif dti < 0.43:
            dti_desc, dti_impact = 'Moderate debt-to-income ratio', 'neutral'
        else:
            dti_desc, dti_impact = 'High debt-to-income ratio', 'negative'
        factors.append({
            'factor': 'dti_ratio', 'impact': dti_impact,
            'value': dti, 'description': dti_desc,
        })

        # ── Utilization ──
        util = app_data['utilization']
        if util < 0.3:
            util_desc, util_impact = 'Low credit utilization', 'positive'
        elif util < 0.6:
            util_desc, util_impact = 'Moderate credit utilization', 'neutral'
        else:
            util_desc, util_impact = 'High credit utilization', 'negative'
        factors.append({
            'factor': 'utilization', 'impact': util_impact,
            'value': util, 'description': util_desc,
        })

        # ── Derogatory marks ──
        derog = app_data['num_derogatory']
        if derog == 0:
            derog_desc, derog_impact = 'No derogatory marks', 'positive'
        elif derog <= 2:
            derog_desc, derog_impact = 'Few derogatory marks', 'neutral'
        else:
            derog_desc, derog_impact = 'Multiple derogatory marks', 'negative'
        factors.append({
            'factor': 'num_derogatory', 'impact': derog_impact,
            'value': derog, 'description': derog_desc,
        })

        # ── Home ownership ──
        home = app_data['home_ownership']
        home_impact = 'positive' if home in ('own', 'mortgage') else 'neutral'
        factors.append({
            'factor': 'home_ownership', 'impact': home_impact,
            'value': home, 'description': f'Home: {home}',
        })

        # ── Loan-to-income ──
        income = app_data['annual_income']
        loan = app_data['loan_amount']
        lti = loan / max(1.0, income)
        lti_impact = (
            'positive' if lti < 0.2
            else 'neutral' if lti < 0.4
            else 'negative'
        )
        factors.append({
            'factor': 'loan_to_income', 'impact': lti_impact,
            'value': round(lti, 3),
            'description': f'Loan is {lti * 100:.0f}% of income',
        })

        # Sort: negative first, then neutral, then positive
        impact_order = {'negative': 0, 'neutral': 1, 'positive': 2}
        factors.sort(key=lambda f: impact_order.get(f['impact'], 1))

        # ── Summary ──
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

    # ═══════════════════════════════════════════════════════════════
    #  Helpers
    # ═══════════════════════════════════════════════════════════════

    @staticmethod
    def _get_recommended_term(loan_amount: float, risk_score: int) -> int:
        """Recommend a loan term based on amount and risk."""
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
    scorer = XGBoostScorer()
    model_path = os.path.join(BASE_DIR, 'model_xgb.json')
    if os.path.exists(model_path):
        scorer.load()
    else:
        print("No XGBoost model found. Run train_xgb_model.py first.")
        sys.exit(1)

    app = {
        'credit_score': 720,
        'dti_ratio': 0.25,
        'utilization': 0.30,
        'num_derogatory': 0,
        'num_credit_lines': 8,
        'age': 35,
        'annual_income': 85000,
        'employment_length': 5,
        'loan_amount': 10000,
        'home_ownership': 'mortgage',
    }

    result = scorer.score_application(app)
    print(f"\n  Risk Score: {result['risk_score']}")
    print(f"  Approved: {result['approved']}")
    print(f"  Interest Rate: {result['interest_rate']:.2f}%")
    print(f"  Tier: {result['risk_tier']} ({result['risk_label']})")
    print(f"  Monthly Payment: ${result['monthly_payment']:.2f}")
    print(f"  Prob Default: {result['probability_of_default']:.4f}")
    print(f"  Explanation: {result['explanation']['summary']}")

    # Test SHAP if available
    try:
        shap_result = scorer.get_shap_values(app)
        print(f"\n  SHAP base value: {shap_result['base_value']:.4f}")
        print(f"  Top SHAP feature: {shap_result['values'][0]['feature']} "
              f"({shap_result['values'][0]['shap_value']:.4f})")
    except RuntimeError as e:
        print(f"\n  SHAP: {e}")
