#!/usr/bin/env python3
"""Production scoring engine for credit underwriting.
This is the PRIMARY INTERFACE for the underwriting system."""

import json
import os
import numpy as np
from copy import deepcopy

from feature_engineer import CreditFeatureEngineer
from ensemble_model import CreditEnsemble
from pricing import PricingEngine


class LoanScorer:
    """Production loan scoring and pricing engine.
    
    Loads a trained model and scores individual or batch applications.
    """

    def __init__(self, model_dir=None):
        self.engineer = CreditFeatureEngineer()
        self.model = CreditEnsemble()
        self.pricing = PricingEngine()
        self.model_loaded = False
        self.model_dir = model_dir or os.path.dirname(os.path.abspath(__file__))

    def load(self, path=None):
        """Load trained model weights and feature engineering params.
        
        Args:
            path: Path to model_weights.json. If None, looks in model_dir.
        """
        if path is None:
            path = os.path.join(self.model_dir, 'model_weights.json')
        
        if not os.path.exists(path):
            # Try to train if no model found
            raise FileNotFoundError(
                f"Model not found at {path}. Run train.py first to train the model."
            )
        
        with open(path, 'r') as f:
            model_dict = json.load(f)
        
        # Load engineer
        self.engineer = CreditFeatureEngineer.from_dict(model_dict['engineer'])
        
        # Load ensemble model
        self.model = CreditEnsemble.from_dict(model_dict['ensemble'])
        
        self.model_loaded = True
        print(f"Model loaded from {path}")
        if 'metrics' in model_dict:
            print(f"  Train AUC: {model_dict['metrics'].get('train_auc', 'N/A'):.4f}")
            print(f"  Val AUC:   {model_dict['metrics'].get('val_auc', 'N/A'):.4f}")
            print(f"  Test AUC:  {model_dict['metrics'].get('test_auc', 'N/A'):.4f}")
        
        return self

    def score_application(self, app_data: dict) -> dict:
        """Score a single loan application and return full decision.
        
        Args:
            app_data: Dict with borrower features (see docstring)
            
        Returns:
            Dict with risk score, tier, approval decision, pricing, and explanation
        """
        if not self.model_loaded:
            raise RuntimeError("Model not loaded. Call .load() first.")
        
        # Validate required fields
        required = ['age', 'annual_income', 'employment_length', 'credit_score',
                    'dti_ratio', 'utilization', 'num_derogatory', 'num_credit_lines',
                    'home_ownership', 'loan_amount', 'loan_purpose']
        
        for field in required:
            if field not in app_data:
                raise ValueError(f"Missing required field: {field}")
        
        # Transform to feature vector
        feature_dict = {
            'age': app_data['age'],
            'annual_income': app_data['annual_income'],
            'employment_length': app_data['employment_length'],
            'credit_score': app_data['credit_score'],
            'dti_ratio': app_data['dti_ratio'],
            'utilization': app_data['utilization'],
            'num_derogatory': app_data['num_derogatory'],
            'num_credit_lines': app_data['num_credit_lines'],
            'home_ownership': app_data['home_ownership'],
            'loan_amount': app_data['loan_amount'],
            'loan_purpose': app_data['loan_purpose'],
        }
        
        X = self.engineer.transform([feature_dict])
        
        # Get predictions from all models
        prob_default = float(self.model.predict_proba(X)[0])
        risk_score = int(round(prob_default * 100))
        risk_score = max(0, min(100, risk_score))

        # ── Cash Flow Underwriting Blend ──
        # If bank transaction data was provided, blend with cash flow score
        cash_flow_data = app_data.get('cash_flow_metrics')
        cash_flow_adjusted = False
        if cash_flow_data and isinstance(cash_flow_data, dict):
            cf_score = cash_flow_data.get('cash_flow_score', 50)
            # Convert cash flow score to risk: higher CF score = lower risk
            cf_risk = max(0, min(100, 100 - cf_score))
            # Blend: weight traditional model more, cash flow as adjustment
            # Cash flow can help thin-file borrowers (low credit score + good cash flow)
            # or flag risky ones (good credit score + bad cash flow)
            blend_weight = 0.30  # Cash flow is 30% of the decision
            if app_data.get('credit_score', 700) < 620:
                # Thin-file: cash flow matters more
                blend_weight = 0.50
            if cf_score < 30:
                # Terrible cash flow: flag regardless of credit
                blend_weight = 0.60
            blended_risk = int(round(risk_score * (1 - blend_weight) + cf_risk * blend_weight))
            if blended_risk != risk_score:
                risk_score = blended_risk
                cash_flow_adjusted = True

        # Determine risk tier
        risk_tier = self.pricing.get_risk_tier(risk_score)
        
        # Determine approval
        approved = risk_score <= 75  # Approve up to 75% risk
        tier_config = self.pricing.TIER_RATES.get(risk_tier, self.pricing.TIER_RATES['E'])
        
        # Loan amount check
        max_allowed = tier_config['max_loan']
        if app_data['loan_amount'] > max_allowed:
            approved = False
            max_loan_amount = max_allowed
        else:
            max_loan_amount = max_allowed
        
        # Get term (default to 36 months)
        term = app_data.get('term_months', 36)
        
        # Calculate pricing
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
        
        # Build explanation
        explanation = self._build_explanation(app_data, risk_score, prob_default)
        
        # Get recommended term
        recommended_term = self._get_recommended_term(app_data['loan_amount'], risk_score)
        
        # Build amortization schedule
        amortization_schedule = self.pricing.calculate_amortization_schedule(
            app_data['loan_amount'], interest_rate, recommended_term
        )
        
        return {
            'risk_score': risk_score,
            'risk_tier': risk_tier,
            'risk_label': self.pricing.get_risk_label(risk_tier),
            'approved': approved,
            'interest_rate': interest_rate,
            'max_loan_amount': max_loan_amount,
            'recommended_term_months': recommended_term,
            'monthly_payment': monthly_payment,
            'origination_fee': origination_fee,
            'total_cost': total_cost_info,
            'probability_of_default': round(prob_default, 4),
            'explanation': explanation,
            'amortization_schedule': amortization_schedule,
            'cash_flow_adjusted': cash_flow_adjusted,
        }

    def _build_explanation(self, app_data, risk_score, prob_default):
        """Build human-readable explanation of the credit decision."""
        factors = []
        
        # Credit score analysis
        cs = app_data['credit_score']
        if cs >= 740:
            cs_impact = 'positive'
            cs_desc = 'Very good credit score'
        elif cs >= 670:
            cs_impact = 'positive'
            cs_desc = 'Good credit score'
        elif cs >= 580:
            cs_impact = 'neutral'
            cs_desc = 'Fair credit score'
        else:
            cs_impact = 'negative'
            cs_desc = 'Below average credit score'
        factors.append({
            'factor': 'credit_score',
            'impact': cs_impact,
            'value': cs,
            'description': cs_desc,
        })
        
        # DTI analysis
        dti = app_data['dti_ratio']
        if dti < 0.2:
            dti_impact = 'positive'
            dti_desc = 'Low debt-to-income ratio'
        elif dti < 0.36:
            dti_impact = 'positive'
            dti_desc = 'Manageable debt-to-income ratio'
        elif dti < 0.43:
            dti_impact = 'neutral'
            dti_desc = 'Moderate debt-to-income ratio'
        else:
            dti_impact = 'negative'
            dti_desc = 'High debt-to-income ratio'
        factors.append({
            'factor': 'dti_ratio',
            'impact': dti_impact,
            'value': dti,
            'description': dti_desc,
        })
        
        # Utilization
        util = app_data['utilization']
        if util < 0.3:
            util_impact = 'positive'
            util_desc = 'Low credit utilization'
        elif util < 0.6:
            util_impact = 'neutral'
            util_desc = 'Moderate credit utilization'
        else:
            util_impact = 'negative'
            util_desc = 'High credit utilization'
        factors.append({
            'factor': 'utilization',
            'impact': util_impact,
            'value': util,
            'description': util_desc,
        })
        
        # Derogatory marks
        derog = app_data['num_derogatory']
        if derog == 0:
            derog_impact = 'positive'
            derog_desc = 'No derogatory marks'
        elif derog <= 2:
            derog_impact = 'neutral'
            derog_desc = 'Few derogatory marks'
        else:
            derog_impact = 'negative'
            derog_desc = 'Multiple derogatory marks'
        factors.append({
            'factor': 'num_derogatory',
            'impact': derog_impact,
            'value': derog,
            'description': derog_desc,
        })
        
        # Home ownership
        home = app_data['home_ownership']
        if home == 'own':
            home_impact = 'positive'
        elif home == 'mortgage':
            home_impact = 'positive'
        else:
            home_impact = 'neutral'
        factors.append({
            'factor': 'home_ownership',
            'impact': home_impact,
            'value': home,
            'description': f'Home ownership status: {home}',
        })
        
        # Income
        income = app_data['annual_income']
        loan = app_data['loan_amount']
        lti = loan / max(1, income)
        if lti < 0.2:
            income_impact = 'positive'
        elif lti < 0.4:
            income_impact = 'neutral'
        else:
            income_impact = 'negative'
        factors.append({
            'factor': 'loan_to_income',
            'impact': income_impact,
            'value': round(lti, 3),
            'description': f'Loan is {lti*100:.0f}% of annual income',
        })
        
        # Sort: negative first, then neutral, then positive
        impact_order = {'negative': 0, 'neutral': 1, 'positive': 2}
        factors.sort(key=lambda f: impact_order.get(f['impact'], 1))
        
        # Summary
        positive_count = sum(1 for f in factors if f['impact'] == 'positive')
        negative_count = sum(1 for f in factors if f['impact'] == 'negative')
        
        if negative_count == 0 and positive_count >= 4:
            summary = 'Strong credit profile with excellent financial health'
        elif negative_count == 0:
            summary = 'Good credit profile with manageable risk factors'
        elif negative_count <= 2 and risk_score < 50:
            summary = 'Moderate credit profile with some areas for improvement'
        elif risk_score < 60:
            summary = 'Fair credit profile with notable risk factors to address'
        else:
            summary = 'High-risk credit profile with several concerning factors'
        
        return {
            'top_factors': factors,
            'summary': summary,
        }

    def _get_recommended_term(self, loan_amount, risk_score):
        """Recommend loan term based on amount and risk."""
        if risk_score > 70 or loan_amount < 5000:
            return 24
        elif risk_score > 50 or loan_amount < 15000:
            return 36
        elif loan_amount > 30000:
            return 48
        else:
            return 36

    def score_batch(self, applications: list) -> list:
        """Score multiple applications.
        
        Args:
            applications: List of app_data dicts
            
        Returns:
            List of scored result dicts
        """
        return [self.score_application(app) for app in applications]


# Quick test if run directly
if __name__ == '__main__':
    scorer = LoanScorer()
    
    # Check if model exists
    model_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'model_weights.json')
    if os.path.exists(model_path):
        scorer.load()
    else:
        print("No model found. Run train.py first.")
        print("\nTest application (mock):")
    
    # Sample application
    app = {
        'age': 35,
        'annual_income': 85000,
        'employment_length': 5,
        'credit_score': 720,
        'dti_ratio': 0.25,
        'utilization': 0.3,
        'num_derogatory': 0,
        'num_credit_lines': 8,
        'home_ownership': 'mortgage',
        'loan_amount': 10000,
        'loan_purpose': 'debt_consolidation',
    }
    
    if scorer.model_loaded:
        result = scorer.score_application(app)
        print("\n" + "=" * 60)
        print("  LOAN SCORING RESULT")
        print("=" * 60)
        for key, value in result.items():
            if key == 'explanation':
                print(f"  {key}:")
                print(f"    Summary: {value['summary']}")
                for f in value['top_factors'][:4]:
                    print(f"    - {f['factor']}: {f['impact']} (value={f['value']})")
            elif key == 'total_cost':
                print(f"  {key}: {json.dumps(value, indent=4)}")
            elif key == 'amortization_schedule':
                print(f"  {key}: {len(value)} payments")
            else:
                print(f"  {key}: {value}")
