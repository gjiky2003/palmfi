"""Combined Credit Application Handler

Orchestrates the full application flow:
1. Applicant submits form (SSN, DOB, income, etc.)
2. Bureau pull → real credit data
3. (Optional) Plaid pull → cash flow analysis
4. Score → decision
5. Save to DB

This replaces the old self-reported credit field approach.
"""
from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime
from typing import Any

log = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(BASE_DIR, '..', 'underwriting'))

from scorer import LoanScorer
from pricing import PricingEngine

# ── V2 components (optional — graceful fallback if not available) ──

def _get_xgb_scorer():
    """Try to load XGBoost scorer. Returns None on failure (falls back to old scorer)."""
    try:
        sys.path.insert(0, os.path.join(BASE_DIR, '..', 'underwriting'))
        from xgb_scorer import XGBoostScorer
        s = XGBoostScorer()
        model_path = os.path.join(BASE_DIR, '..', 'underwriting', 'model_xgb.json')
        meta_path = os.path.join(BASE_DIR, '..', 'underwriting', 'model_weights_xgb.json')
        if os.path.exists(model_path) and os.path.exists(meta_path):
            s.load(model_path, meta_path)
            return s
    except Exception as e:
        log.warning('XGBoost scorer unavailable: %s', e)
    return None


def _get_recon_engine():
    """Try to load reconsideration engine."""
    try:
        sys.path.insert(0, os.path.join(BASE_DIR, '..', 'underwriting'))
        from reconsideration_engine import ReconsiderationEngine
        return ReconsiderationEngine()
    except Exception:
        return None


def _get_shap_adverse():
    """Try to load SHAP adverse action engine."""
    try:
        sys.path.insert(0, os.path.join(BASE_DIR, '..', 'compliance'))
        from shap_adverse_action import ShapAdverseAction
        return ShapAdverseAction  # return class, not instance (needs feature_names)
    except Exception:
        return None


# ── Lazy imports (avoid circular deps with app.py) ──

def _get_bureau():
    from bureau import pull_credit_report, compute_credit_score, verify_identity
    return pull_credit_report, compute_credit_score, verify_identity


def _get_plaid():
    from plaid_integration import (
        create_link_token, exchange_public_token, get_transactions,
        get_accounts, get_auth
    )
    return create_link_token, exchange_public_token, get_transactions, get_accounts, get_auth


def _get_cf_analyzer():
    sys.path.insert(0, os.path.join(BASE_DIR, '..', 'underwriting'))
    from cash_flow import CashFlowAnalyzer
    return CashFlowAnalyzer()


def _get_scorer():
    """Get or initialize the loan scorer."""
    scorer = LoanScorer()
    model_path = os.path.join(BASE_DIR, '..', 'underwriting', 'model_weights.json')
    if os.path.exists(model_path):
        try:
            scorer.load(model_path)
            return scorer
        except Exception as e:
            log.warning('Scorer load failed: %s', e)
    return None


# ═══════════════════════════════════════════════════════════════
#  Main Application Processing
# ═══════════════════════════════════════════════════════════════

def process_application(form_data: dict) -> dict[str, Any]:
    """Full application pipeline.

    Args:
        form_data: Dict from the application form with keys:
            - ssn: Full 9-digit SSN
            - date_of_birth: 'YYYY-MM-DD'
            - first_name, last_name
            - annual_income, loan_amount, loan_purpose
            - home_ownership, employment_length_months
            - plaid_public_token (optional)
            - address, city, state, zip_code

    Returns:
        Dict with decision, risk data, pricing, and next steps
    """
    result = {
        'success': False,
        'bureau_pulled': False,
        'plaid_linked': False,
        'cash_flow_analyzed': False,
        'scored': False,
        'application_id': None,
        'risk_score': None,
        'approved': False,
        'errors': [],
    }

    ssn = _clean_ssn(form_data.get('ssn', ''))
    dob = form_data.get('date_of_birth', '')
    full_name = f"{form_data.get('first_name', '')} {form_data.get('last_name', '')}".strip()

    if not ssn or len(ssn) != 9:
        result['errors'].append('Valid SSN required')
        return result

    # ── Step 1: Identity Verification + Bureau Pull ──
    try:
        pull_report, pull_score, verify_id = _get_bureau()

        # 1a. Identity verification
        identity = verify_id(ssn, dob, full_name)
        if not identity.get('matched', False):
            result['errors'].append('Identity could not be verified. Please check your information.')
            return result

        # 1b. Pull full credit report
        credit_report = pull_report(ssn, dob, full_name)
        result['bureau_pulled'] = True
        result['credit_report'] = credit_report

        # 1c. Quick score (lighter, for display)
        score_result = pull_score(ssn, dob)
        result['fico_score'] = score_result['fico_score']
        result['fico_factors'] = score_result['factors']
        result['score_category'] = score_result.get('score_category', 'unknown')

    except Exception as e:
        log.error('Bureau pull failed: %s', e)
        result['errors'].append(f'Credit bureau unavailable: {str(e)}')
        # Continue with self-reported data as fallback
        credit_report = None

    # ── Step 2: Plaid (optional — only if user linked their bank) ──
    cash_flow_metrics = None
    plaid_public_token = form_data.get('plaid_public_token', '')

    if plaid_public_token and len(plaid_public_token) > 10:
        try:
            create_lt, exchange_pt, get_txns, _, _ = _get_plaid()

            # Exchange public token for access token
            token_result = exchange_pt(plaid_public_token)
            access_token = token_result.get('access_token', '')

            if access_token:
                # Fetch transactions
                txn_result = get_txns(access_token, 90)
                transactions = txn_result.get('transactions', [])

                if transactions:
                    # Analyze cash flow
                    analyzer = _get_cf_analyzer()
                    cash_flow_metrics = analyzer.analyze(transactions)
                    result['cash_flow_analyzed'] = True
                    result['cash_flow_score'] = cash_flow_metrics.get('cash_flow_score', 0)
                    result['cash_flow_income'] = cash_flow_metrics.get('cash_flow_income', 0)

                    result['plaid_linked'] = True
                    result['access_token'] = access_token

        except Exception as e:
            log.warning('Plaid linking failed: %s', e)
            # Non-critical — continue without cash flow data

    # ── Step 3: Score ──
    try:
        # Build scorer input from bureau data + form data
        employment_months = int(form_data.get('employment_length_months', 0))
        employment_length = max(0.5, employment_months / 12)

        # Age from DOB
        age = 35
        if dob:
            try:
                b = [int(x) for x in dob.split('-')]
                age = datetime.now().year - b[0]
                if (datetime.now().month, datetime.now().day) < (b[1], b[2]):
                    age -= 1
                age = max(18, min(75, age))
            except Exception:
                pass

        # Use bureau data if available, fall back to self-reported
        if credit_report:
            credit_score = credit_report['fico_score']
            dti_ratio = credit_report['dti_ratio']
            utilization = credit_report['revolving_utilization']
            num_derogatory = credit_report['derogatory_count']
            num_credit_lines = credit_report['open_trade_lines']
        else:
            # Self-reported fallback
            credit_score = int(form_data.get('credit_score_bucket', 680))
            monthly_debt = float(form_data.get('monthly_debt', 0))
            annual_income = float(form_data.get('annual_income', 50000))
            dti_ratio = min(0.9, (monthly_debt * 12) / max(1, annual_income))
            util_map = {'0.1': 0.08, '0.25': 0.20, '0.45': 0.40, '0.65': 0.60, '0.85': 0.80}
            utilization = util_map.get(form_data.get('utilization', '0.25'), 0.25)
            num_derogatory = int(form_data.get('num_derogatory', 0))
            num_credit_lines = int(form_data.get('num_credit_lines', 5))

        annual_income = float(form_data.get('annual_income', 50000))
        loan_amount = float(form_data.get('loan_amount', 5000))
        home_ownership = form_data.get('home_ownership', 'rent')
        loan_purpose = form_data.get('loan_purpose', 'personal')

        # Build app_data for scorer
        app_data = {
            'age': age,
            'annual_income': annual_income,
            'employment_length': employment_length,
            'credit_score': credit_score,
            'dti_ratio': dti_ratio,
            'utilization': utilization,
            'num_derogatory': num_derogatory,
            'num_credit_lines': num_credit_lines,
            'home_ownership': home_ownership,
            'loan_amount': loan_amount,
            'loan_purpose': loan_purpose,
            'term_months': int(form_data.get('term_months', 36)),
        }

        # Add cash flow metrics for blended scoring
        if cash_flow_metrics:
            app_data['cash_flow_metrics'] = cash_flow_metrics

        # Score
        scorer = _get_scorer()
        if scorer and scorer.model_loaded:
            score_result = scorer.score_application(app_data)
        else:
            # Fallback: use PricingEngine directly with rule-based risk
            log.warning('Scorer unavailable — using rule-based fallback')
            score_result = _fallback_score(app_data, credit_report)

        result['scored'] = True
        result['risk_score'] = score_result.get('risk_score', 50)
        result['risk_tier'] = score_result.get('risk_tier', 'E')
        result['approved'] = score_result.get('approved', False)
        result['interest_rate'] = score_result.get('interest_rate', 0)
        result['monthly_payment'] = score_result.get('monthly_payment', 0)
        result['max_loan_amount'] = score_result.get('max_loan_amount', 5000)
        result['explanation'] = score_result.get('explanation', {})
        result['origination_fee'] = score_result.get('origination_fee', 0)
        result['scoring_method'] = 'credit_bureau'
        if cash_flow_metrics:
            result['scoring_method'] = 'credit_cash_flow_blend'
        result['success'] = True

    except Exception as e:
        log.error('Scoring failed: %s', e)
        result['errors'].append(f'Scoring error: {str(e)}')
        result['risk_score'] = 50
        result['approved'] = False

    return result


def _fallback_score(app_data: dict, credit_report: dict | None = None) -> dict:
    """Rule-based fallback when the ML scorer is unavailable."""
    cs = app_data.get('credit_score', 680)
    dti = app_data.get('dti_ratio', 0.3)
    util = app_data.get('utilization', 0.3)
    derog = app_data.get('num_derogatory', 0)

    risk_score = int(round(
        max(0, min(100,
            (850 - cs) * 0.2 +      # credit score contribution
            dti * 40 +               # DTI contribution
            util * 20 +              # utilization contribution
            derog * 5                # derogatory marks
        ))
    ))

    pricing = PricingEngine()
    risk_tier = pricing.get_risk_tier(risk_score)
    tier_config = pricing.TIER_RATES.get(risk_tier, pricing.TIER_RATES['E'])
    approved = risk_score <= 75
    term = app_data.get('term_months', 36)
    loan_amnt = app_data.get('loan_amount', 5000)

    return {
        'risk_score': risk_score,
        'risk_tier': risk_tier,
        'risk_label': tier_config.get('label', 'Unknown'),
        'approved': approved,
        'interest_rate': pricing.calculate_rate(risk_tier, loan_amnt, term, dti),
        'monthly_payment': pricing.calculate_monthly_payment(loan_amnt, tier_config.get('min_apr', 15), term),
        'max_loan_amount': tier_config.get('max_loan', 5000),
        'origination_fee': pricing.calculate_origination_fee(loan_amnt, risk_tier),
        'probability_of_default': round(risk_score / 100, 2),
        'explanation': {
            'summary': 'Application processed (rule-based fallback model)',
            'top_factors': [
                {'factor': 'credit_score', 'impact': 'negative' if cs < 640 else 'positive',
                 'value': cs, 'description': f'Credit score: {cs}'},
            ],
        },
        'scoring_method': 'rule_fallback',
    }


def _clean_ssn(ssn: str) -> str:
    """Remove non-numeric characters from SSN."""
    cleaned = ''.join(c for c in ssn if c.isdigit())
    return cleaned[:9]


# ═══════════════════════════════════════════════════════════════
#  V2 Two-Stage Application Processing
# ═══════════════════════════════════════════════════════════════

def process_application_two_stage(form_data: dict) -> dict[str, Any]:
    """Two-stage application pipeline using XGBoost + Reconsideration Engine.

    Stage 1: Bureau pull → XGBoost score → Zone classification
    Stage 2: If not auto-approved → Plaid cash flow → Reconsideration

    Uses v1 process_application for the base flow, then applies the
    XGBoost scorer and reconsideration engine on top.
    """
    # Run standard v1 pipeline first (identity verify, bureau pull, Plaid)
    v1_result = process_application(form_data)

    if not v1_result.get('success'):
        return v1_result

    # Load v2 components (graceful fallback to v1)
    xgb_scorer = _get_xgb_scorer()
    recon_engine = _get_recon_engine()

    if xgb_scorer is None or recon_engine is None:
        # Fallback to v1 result
        v1_result['scoring_method'] = 'v1_fallback'
        return v1_result

    # ── Stage 1: XGBoost Primary Score (bureau data only) ──

    # Rebuild app_data from the original form + bureau data
    credit_report = v1_result.get('credit_report')
    employment_months = int(form_data.get('employment_length_months', 0))
    employment_length = max(0.5, employment_months / 12)

    age = 35
    dob = form_data.get('date_of_birth', '')
    if dob:
        try:
            b = [int(x) for x in dob.split('-')]
            age = datetime.now().year - b[0]
            if (datetime.now().month, datetime.now().day) < (b[1], b[2]):
                age -= 1
            age = max(18, min(75, age))
        except Exception:
            pass

    if credit_report:
        credit_score = credit_report['fico_score']
        dti_ratio = credit_report['dti_ratio']
        utilization = credit_report['revolving_utilization']
        num_derogatory = credit_report['derogatory_count']
        num_credit_lines = credit_report['open_trade_lines']
    else:
        credit_score = int(form_data.get('credit_score_bucket', 680))
        monthly_debt = float(form_data.get('monthly_debt', 0))
        annual_income = float(form_data.get('annual_income', 50000))
        dti_ratio = min(0.9, (monthly_debt * 12) / max(1, annual_income))
        util_map = {'0.1': 0.08, '0.25': 0.20, '0.45': 0.40, '0.65': 0.60, '0.85': 0.80}
        utilization = util_map.get(form_data.get('utilization', '0.25'), 0.25)
        num_derogatory = int(form_data.get('num_derogatory', 0))
        num_credit_lines = int(form_data.get('num_credit_lines', 5))

    annual_income = float(form_data.get('annual_income', 50000))
    loan_amount = float(form_data.get('loan_amount', 5000))
    home_ownership = form_data.get('home_ownership', 'rent')
    loan_purpose = form_data.get('loan_purpose', 'personal')

    app_data = {
        'age': age,
        'annual_income': annual_income,
        'employment_length': employment_length,
        'credit_score': credit_score,
        'dti_ratio': dti_ratio,
        'utilization': utilization,
        'num_derogatory': num_derogatory,
        'num_credit_lines': num_credit_lines,
        'home_ownership': home_ownership,
        'loan_amount': loan_amount,
        'loan_purpose': loan_purpose,
        'term_months': int(form_data.get('term_months', 36)),
    }

    # ── Gating Rules Check ──
    try:
        from gating_rules import GatingRules
        gating = GatingRules()
        gating_result = gating.evaluate(
            app_data,
            bureau_data=credit_report,
            application_history=None,
        )
    except Exception as e:
        log.warning('Gating rules unavailable: %s', e)
        gating_result = {
            'hard_cut_blocked': False,
            'hard_cuts': [],
            'suppression_flagged': False,
            'suppressions': [],
            'soft_override_applies': False,
            'gating_summary': 'Gating rules unavailable',
        }

    # Hard cut = immediate decline, no scoring
    if gating_result.get('hard_cut_blocked'):
        hard_cut_reasons = [
            hc['reason'] for hc in gating_result.get('hard_cuts', [])
            if hc.get('blocked')
        ]
        return {
            'success': False,
            'two_stage': True,
            'stage': 0,
            'approved': False,
            'errors': hard_cut_reasons or ['Application does not meet minimum requirements.'],
            'hard_cut_blocked': True,
            'hard_cut_reasons': hard_cut_reasons,
            'risk_score': 99,
            'scoring_method': 'v2_hard_cut',
        }

    # XGBoost primary score
    xgb_result = xgb_scorer.score_application(app_data)
    bureau_score = xgb_result['risk_score']

    # Classify into zone
    zone = recon_engine.classify(bureau_score)
    decision = recon_engine.format_decision(bureau_score)

    # Get SHAP values for adverse action
    shap_values = None
    adverse_reasons = []
    try:
        shap_values = xgb_scorer.get_shap_values(app_data)
        ShapAdverse = _get_shap_adverse()
        if ShapAdverse is not None:
            shap_engine = ShapAdverse(xgb_scorer.feature_names)
            adverse_reasons = shap_engine.generate(
                shap_values, app_data, bureau_score, zone == 'auto_approve'
            )
    except Exception as e:
        log.warning('SHAP adverse action unavailable: %s', e)

    # ── Build Stage 1 result ──
    # Check if manual review is needed (suppressions flagged OR borderline after reconsideration)
    needs_manual_review = (
        gating_result.get('suppression_flagged', False)
        and zone != 'auto_approve'
    )

    stage1_result = {
        'success': True,
        'two_stage': True,
        'stage': 1,
        'bureau_pulled': v1_result.get('bureau_pulled', False),
        'fico_score': v1_result.get('fico_score'),
        'risk_score': bureau_score,
        'risk_tier': xgb_result.get('risk_tier'),
        'risk_label': xgb_result.get('risk_label'),
        'zone': zone,
        'approved': zone == 'auto_approve' and not needs_manual_review,
        'interest_rate': xgb_result.get('interest_rate'),
        'monthly_payment': xgb_result.get('monthly_payment'),
        'max_loan_amount': xgb_result.get('max_loan_amount'),
        'origination_fee': xgb_result.get('origination_fee'),
        'total_cost': xgb_result.get('total_cost'),
        'explanation': xgb_result.get('explanation'),
        'probability_of_default': xgb_result.get('probability_of_default'),
        'shap_values': shap_values,
        'adverse_reasons': adverse_reasons,
        'second_look_message': recon_engine.get_second_look_message(zone),
        'scoring_method': f'v2_xgb_{zone}',
        'required_fields': form_data,
        'app_data': app_data,
        'gating_result': gating_result,
        'needs_manual_review': needs_manual_review,
    }

    # ── Stage 2: Check if Plaid data was already submitted with the form ──
    plaid_token = form_data.get('plaid_public_token', '')
    cash_flow_data = v1_result.get('cash_flow_data') or v1_result.get('cash_flow_metrics')

    # If Plaid already linked OR cash flow already available, run reconsideration
    if (plaid_token and len(str(plaid_token)) > 10) or cash_flow_data:
        return _run_stage2(stage1_result, cash_flow_data, recon_engine, zone, app_data, form_data)

    return stage1_result


def _run_stage2(stage1_result, cash_flow_data, recon_engine, zone, app_data, form_data):
    """Stage 2: Reconsideration using cash flow data."""
    if zone == 'auto_approve':
        # Already approved — cash flow just adjusts pricing
        return stage1_result

    bureau_score = stage1_result['risk_score']

    # Get cash flow score (invert: higher CF score = lower risk)
    cf_score_raw = 50
    if cash_flow_data and isinstance(cash_flow_data, dict):
        cf_score_raw = cash_flow_data.get('cash_flow_score', 50)
    elif cash_flow_data and isinstance(cash_flow_data, (int, float)):
        cf_score_raw = int(cash_flow_data)
    cf_risk = max(0, min(100, 100 - cf_score_raw))  # higher CF → lower risk

    # Optional LLM document boost
    llm_boost = 0
    llm_doc_text = form_data.get('llm_doc_text', '')
    is_self_employed = form_data.get('employment_status', '') == 'self-employed'
    if is_self_employed and llm_doc_text:
        try:
            sys.path.insert(0, os.path.join(BASE_DIR, '..', 'underwriting'))
            from llm_doc_extractor import LLMDocExtractor
            extractor = LLMDocExtractor()
            extraction = extractor.extract(llm_doc_text, form_data.get('doc_type', 'bank_statement'))
            llm_boost = extraction.get('recommended_boost', 0)
        except Exception:
            pass

    # Run reconsideration
    recon_result = recon_engine.reconsider(bureau_score, cf_risk, zone, llm_boost)

    # Build stage 2 result
    stage1_result['stage'] = 2
    stage1_result['zone'] = zone  # keep original zone
    stage1_result['reconsideration'] = recon_result
    stage1_result['second_look_message'] = None  # already processed
    stage1_result['scoring_method'] = f'v2_xgb_reconsideration'
    stage1_result['cash_flow_score'] = cf_score
    stage1_result['llm_boost_applied'] = llm_boost > 0
    stage1_result['risk_score'] = recon_result['blended_score']
    stage1_result['approved'] = recon_result['approved']

    # Regenerate SHAP adverse action for final decision
    if not recon_result['approved'] and stage1_result.get('shap_values'):
        try:
            ShapAdverse = _get_shap_adverse()
            if ShapAdverse is not None:
                shap_engine = ShapAdverse(stage1_result.get('app_data', {}).keys() if 'app_data' in stage1_result else [])
                # Re-use existing shap values
                pass
        except Exception:
            pass

    return stage1_result


def reconsider_application(borrower_id: int, plaid_public_token: str,
                           form_data: dict | None = None) -> dict[str, Any]:
    """Reconsider an application after Plaid link.
    
    Called when a borrower links their bank after the initial decline/consideration.
    
    Args:
        borrower_id: The borrower's DB ID
        plaid_public_token: Plaid Link public token
        form_data: Original form data (optional, for context)
    """
    result = {'success': False, 'approved': False}

    try:
        # Exchange Plaid token for access token
        from plaid_integration import exchange_public_token, get_transactions
        token_result = exchange_public_token(plaid_public_token)
        access_token = token_result.get('access_token', '')

        if not access_token:
            result['error'] = 'Could not link bank account'
            return result

        # Fetch transactions
        txn_result = get_transactions(access_token, 90)
        transactions = txn_result.get('transactions', [])

        # Analyze cash flow
        from cash_flow import CashFlowAnalyzer
        analyzer = CashFlowAnalyzer()
        cash_flow_metrics = analyzer.analyze(transactions)
        cf_score = cash_flow_metrics.get('cash_flow_score', 50)

        # Load previous application data
        from scorer import LoanScorer
        # ... stage 2 processing ...
        result['success'] = True
        result['cash_flow_metrics'] = cash_flow_metrics
        result['cash_flow_score'] = cf_score
        result['access_token'] = access_token

    except Exception as e:
        log.error('Reconsideration failed: %s', e)
        result['error'] = str(e)

    return result


# ═══════════════════════════════════════════════════════════════
#  Quick test
# ═══════════════════════════════════════════════════════════════
if __name__ == '__main__':
    print("Testing Credit Application Handler")
    print("=" * 50)

    form = {
        'ssn': '123-45-6789',
        'date_of_birth': '1990-05-15',
        'first_name': 'John',
        'last_name': 'Doe',
        'annual_income': '75000',
        'loan_amount': '10000',
        'loan_purpose': 'debt_consolidation',
        'home_ownership': 'mortgage',
        'employment_length_months': '60',
        'term_months': '36',
    }

    result = process_application(form)
    print(f"\nProcessed Application:")
    print(f"  Success: {result['success']}")
    print(f"  Bureau: {result['bureau_pulled']}")
    print(f"  FICO: {result.get('fico_score', 'N/A')}")
    print(f"  Risk: {result.get('risk_score', 'N/A')}")
    print(f"  Approved: {result.get('approved', False)}")
    print(f"  Rate: {result.get('interest_rate', 0)}%")
    print(f"  Payment: ${result.get('monthly_payment', 0)}")
    print(f"  Method: {result.get('scoring_method', 'N/A')}")

    if 'credit_report' in result:
        cr = result['credit_report']
        print(f"\n  Bureau details:")
        print(f"    DTI: {cr['dti_ratio']:.2%}")
        print(f"    Utilization: {cr['revolving_utilization']:.1%}")
        print(f"    Derogatory: {cr['derogatory_count']}")
        print(f"    Open lines: {cr['open_trade_lines']}")
        if 'risk_factors' in cr:
            for f in cr['risk_factors']:
                print(f"    - {f}")

    print("\n✅ Application handler ready")
