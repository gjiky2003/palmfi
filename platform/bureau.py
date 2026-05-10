"""Stipula Credit Bureau API — Mock-First Integration

Pulls full credit report data using SSN + DOB.
Works in mock mode by default (no API key needed).
Set STIPULA_API_KEY in env for real pulls.
"""
from __future__ import annotations

import json
import logging
import os
import random
import re
from datetime import datetime
from typing import Any

log = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


# ── Configuration ──
STIPULA_API_KEY = os.getenv('STIPULA_API_KEY', '')
STIPULA_BASE_URL = os.getenv('STIPULA_BASE_URL', 'https://api.stipula.io/v1')
STIPULA_MOCK_MODE = not STIPULA_API_KEY or STIPULA_API_KEY.startswith('mock_')


def _is_real() -> bool:
    """Check if we're in real API mode vs mock."""
    return bool(STIPULA_API_KEY) and not STIPULA_API_KEY.startswith('mock_')


# ═══════════════════════════════════════════════════════════════
#  Public API
# ═══════════════════════════════════════════════════════════════

def pull_credit_report(ssn: str, dob: str, full_name: str = '',
                       address: dict | None = None) -> dict[str, Any]:
    """Pull a full credit report from Stipula (or mock).

    Args:
        ssn: Full 9-digit SSN (digits only, no dashes)
        dob: Date of birth 'YYYY-MM-DD'
        full_name: Optional full name for KYC matching
        address: Optional dict with street, city, state, zip

    Returns:
        Dict with credit report data (see mock below for full schema)
    """
    if _is_real():
        return _real_pull_credit(ssn, dob, full_name, address)
    return _mock_pull_credit(ssn, dob, full_name)


def verify_identity(ssn: str, dob: str, full_name: str) -> dict[str, Any]:
    """KYC identity verification via Stipula.

    Returns dict with 'matched' bool and verification details.
    """
    if _is_real():
        return _real_verify_id(ssn, dob, full_name)
    # Mock: always match (most SSN/DOB combos we generate will be valid)
    return {
        'matched': True,
        'confidence': random.uniform(0.85, 0.99),
        'name_match': True,
        'dob_match': True,
        'ssn_match': True,
        'address_verified': False,
        'method': 'mock',
    }


def compute_credit_score(ssn: str, dob: str) -> dict[str, Any]:
    """Quick score pull (cheaper, lighter than full report).

    Returns just the FICO score and risk factors.
    """
    if _is_real():
        return _real_pull_score(ssn, dob)
    report = _mock_pull_credit(ssn, dob)
    return {
        'fico_score': report['fico_score'],
        'fico_range': report.get('fico_range', '660-845'),
        'factors': report['risk_factors'],
        'score_category': _categorize_score(report['fico_score']),
        'method': 'mock',
    }


# ═══════════════════════════════════════════════════════════════
#  Real API calls (Stipula REST)
# ═══════════════════════════════════════════════════════════════

def _real_pull_credit(ssn: str, dob: str, name: str = '',
                      address: dict | None = None) -> dict:
    """Real Stipula API call to pull credit report."""
    import requests  # lazy import

    headers = {
        'Authorization': f'Bearer {STIPULA_API_KEY}',
        'Content-Type': 'application/json',
    }
    payload = {
        'ssn': re.sub(r'[^0-9]', '', ssn),
        'dob': dob,
        'name': name or None,
    }
    if address:
        payload['address'] = address

    try:
        resp = requests.post(
            f'{STIPULA_BASE_URL}/credit/pull',
            json=payload,
            headers=headers,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        return _parse_stipula_report(data)
    except Exception as e:
        log.error('Stipula credit pull failed: %s', e)
        raise


def _real_verify_id(ssn: str, dob: str, name: str) -> dict:
    """Real Stipula identity verification."""
    import requests

    headers = {
        'Authorization': f'Bearer {STIPULA_API_KEY}',
        'Content-Type': 'application/json',
    }
    payload = {'ssn': re.sub(r'[^0-9]', '', ssn), 'dob': dob, 'name': name}
    try:
        resp = requests.post(
            f'{STIPULA_BASE_URL}/kyc/verify',
            json=payload,
            headers=headers,
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        log.error('Stipula KYC failed: %s', e)
        return {'matched': False, 'error': str(e)}


def _real_pull_score(ssn: str, dob: str) -> dict:
    """Real Stipula quick score pull."""
    import requests

    headers = {
        'Authorization': f'Bearer {STIPULA_API_KEY}',
        'Content-Type': 'application/json',
    }
    payload = {'ssn': re.sub(r'[^0-9]', '', ssn), 'dob': dob}
    try:
        resp = requests.post(
            f'{STIPULA_BASE_URL}/credit/score',
            json=payload,
            headers=headers,
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        log.error('Stipula score pull failed: %s', e)
        raise


def _parse_stipula_report(data: dict) -> dict:
    """Parse Stipula API response into our standard format."""
    return {
        'fico_score': data.get('score', data.get('fico', 680)),
        'fico_range': f"{data.get('score_range_low', 300)}-{data.get('score_range_high', 850)}",
        'dti_ratio': data.get('dti_ratio', 0.30),
        'revolving_utilization': data.get('revolving_utilization', 0.30),
        'open_trade_lines': data.get('open_trade_lines', 5),
        'derogatory_count': data.get('derogatory_count', 0),
        'total_trade_lines': data.get('total_trade_lines', 10),
        'credit_age_years': data.get('credit_age_years', 5),
        'bankruptcy_flag': data.get('bankruptcy_flag', False),
        'public_records': data.get('public_records', 0),
        'collections_count': data.get('collections_count', 0),
        'credit_limit_total': data.get('credit_limit_total', 25000),
        'balances_total': data.get('balances_total', 7500),
        'monthly_debt_payments': data.get('monthly_debt_payments', 500),
        'inquiries_2y': data.get('inquiries_2y', 1),
        'risk_factors': data.get('risk_factors', []),
        'identity_verified': data.get('identity_verified', True),
        'source': 'stipula',
    }


# ═══════════════════════════════════════════════════════════════
#  Mock data (realistic distributions based on LendingClub stats)
# ═══════════════════════════════════════════════════════════════

def _mock_pull_credit(ssn: str, dob: str, name: str = '') -> dict:
    """Generate realistic mock credit report data based on SSN hash."""
    # Deterministic seed from SSN so same SSN always gets same score
    seed = hash(ssn) & 0x7FFFFFFF if ssn else random.randint(0, 1000000)
    rng = random.Random(seed)

    # Age from DOB
    age = 35
    if dob:
        try:
            b = [int(x) for x in dob.split('-')]
            age = datetime.now().year - b[0]
            age = max(18, min(75, age))
        except Exception:
            pass

    # Generate realistic credit profile based on "age" + randomness
    base_score = 660 + rng.randint(0, 185)  # 660-845 range (matching LC)
    # Younger = slightly lower scores
    if age < 25:
        base_score -= rng.randint(0, 40)
    elif age < 30:
        base_score -= rng.randint(0, 20)
    elif age > 55:
        base_score += rng.randint(0, 20)

    fico = max(350, min(850, base_score))

    # Correlated features
    dti = round(rng.uniform(0.05, 0.50), 4)
    if fico < 620:
        dti = round(rng.uniform(0.30, 0.60), 4)

    utilization = round(rng.uniform(0.05, 0.90), 4)
    if fico < 620:
        utilization = round(rng.uniform(0.40, 1.0), 4)

    derog = 0
    if fico < 640:
        derog = rng.randint(0, 3)
    elif fico < 700:
        derog = rng.randint(0, 1)

    open_lines = rng.randint(2, 20)
    total_lines = open_lines + rng.randint(0, 5)
    credit_age = max(1, age - 22 + rng.randint(-3, 5))

    inquiries = rng.randint(0, 5)
    if fico > 720:
        inquiries = max(0, inquiries - 2)

    collections = 0
    if fico < 660:
        collections = rng.randint(0, 2)

    bankruptcies = False
    if fico < 600:
        bankruptcies = rng.choice([True, False])

    # Risk factors
    risk_factors = []
    if fico < 640:
        risk_factors.append('Limited credit history')
    if utilization > 0.7:
        risk_factors.append('High credit card utilization')
    if dti > 0.40:
        risk_factors.append('High debt-to-income ratio')
    if derog > 0:
        risk_factors.append('Recent delinquencies on file')
    if collections > 0:
        risk_factors.append('Collection accounts reported')
    if fico >= 740:
        risk_factors.append('Excellent payment history')
    if not risk_factors:
        risk_factors.append('Stable credit profile')

    # Monthly debt payments derived from DTI
    est_income = 50000 + (fico - 600) * 200 + rng.randint(0, 30000)
    monthly_debt = int(est_income * dti / 12)

    return {
        'fico_score': fico,
        'fico_range': '660-845' if fico >= 660 else f'{fico-20}-{fico+20}',
        'dti_ratio': dti,
        'revolving_utilization': utilization,
        'open_trade_lines': open_lines,
        'total_trade_lines': total_lines,
        'credit_age_years': credit_age,
        'derogatory_count': derog,
        'bankruptcy_flag': bankruptcies,
        'public_records': 1 if bankruptcies else 0,
        'collections_count': collections,
        'credit_limit_total': int(open_lines * (5000 + fico * 10)),
        'balances_total': int(open_lines * utilization * 5000),
        'monthly_debt_payments': monthly_debt,
        'inquiries_2y': inquiries,
        'risk_factors': risk_factors,
        'identity_verified': True,
        'estimated_income': est_income,
        'source': 'mock',
    }


def _categorize_score(score: int) -> str:
    if score >= 800:
        return 'excellent'
    elif score >= 740:
        return 'very_good'
    elif score >= 670:
        return 'good'
    elif score >= 580:
        return 'fair'
    else:
        return 'poor'


# ═══════════════════════════════════════════════════════════════
#  Quick test
# ═══════════════════════════════════════════════════════════════
if __name__ == '__main__':
    print("Testing Stipula Bureau Integration (Mock Mode)")
    print("=" * 50)

    # Test 1: Score pull
    score = compute_credit_score('123-45-6789', '1990-05-15')
    print(f"\nQuick Score Pull:")
    print(f"  FICO: {score['fico_score']} ({score['score_category']})")
    print(f"  Factors: {score['factors']}")

    # Test 2: Full report
    report = pull_credit_report('123-45-6789', '1990-05-15', 'John Doe')
    print(f"\nFull Credit Report:")
    for k, v in report.items():
        if k != 'risk_factors':
            print(f"  {k}: {v}")
    print(f"  risk_factors: {report.get('risk_factors', [])}")

    # Test 3: Different SSN yields different scores
    report2 = pull_credit_report('987-65-4321', '1985-08-22', 'Jane Smith')
    print(f"\nDifferent applicant:")
    print(f"  FICO: {report2['fico_score']} | DTI: {report2['dti_ratio']} | "
          f"Util: {report2['revolving_utilization']}")

    print("\n✅ Bureau module ready")
