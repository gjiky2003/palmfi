"""Plaid Bank Linking Integration — Mock-First

Handles Plaid Link token creation, public token exchange,
and transaction fetching. Works in mock mode by default.
Set PLAID_CLIENT_ID + PLAID_SECRET in env for real mode.
"""
from __future__ import annotations

import json
import logging
import os
import random
from datetime import datetime, timedelta
from typing import Any

log = logging.getLogger(__name__)


# ── Configuration ──
PLAID_CLIENT_ID = os.getenv('PLAID_CLIENT_ID', '')
PLAID_SECRET = os.getenv('PLAID_SECRET', '')
PLAID_ENV = os.getenv('PLAID_ENV', 'sandbox')  # sandbox | development | production
PLAID_MOCK_MODE = not PLAID_CLIENT_ID or PLAID_CLIENT_ID.startswith('mock_')


def _is_real() -> bool:
    return bool(PLAID_CLIENT_ID) and not PLAID_CLIENT_ID.startswith('mock_')


# ═══════════════════════════════════════════════════════════════
#  Public API
# ═══════════════════════════════════════════════════════════════

def create_link_token(user_id: str, user_name: str = '') -> dict[str, Any]:
    """Create a Plaid Link token for the front-end to initialize Plaid Link.

    Returns dict with 'link_token' string.
    """
    if _is_real():
        return _real_create_link_token(user_id, user_name)
    return {
        'link_token': f'link-sandbox-mock-{user_id}-{random.randint(10000, 99999)}',
        'expiration': (datetime.now() + timedelta(hours=4)).isoformat(),
        'method': 'mock',
    }


def exchange_public_token(public_token: str) -> dict[str, Any]:
    """Exchange a Plaid Link public token for an access token.

    Args:
        public_token: The public token returned by Plaid Link

    Returns:
        Dict with access_token, item_id, and request_id
    """
    if _is_real():
        return _real_exchange_token(public_token)
    return {
        'access_token': f'access-sandbox-mock-{random.randint(100000, 999999)}',
        'item_id': f'item-mock-{random.randint(100000, 999999)}',
        'request_id': f'req-mock-{random.randint(10000, 99999)}',
        'method': 'mock',
    }


def get_transactions(access_token: str, days: int = 90) -> dict[str, Any]:
    """Fetch bank transactions for cash flow analysis.

    Args:
        access_token: Plaid access token
        days: Number of days of history to fetch

    Returns:
        Dict with 'transactions' list and metadata
    """
    if _is_real():
        return _real_get_transactions(access_token, days)
    return _mock_get_transactions(days)


def get_accounts(access_token: str) -> list[dict]:
    """Get list of linked bank accounts.

    Returns list of dicts with account_id, name, type, balance.
    """
    if _is_real():
        return _real_get_accounts(access_token)
    return _mock_get_accounts()


def get_auth(access_token: str) -> dict[str, Any]:
    """Get account + routing numbers for ACH disbursement.

    Returns dict with accounts containing account_number and routing_number.
    """
    if _is_real():
        return _real_get_auth(access_token)
    return _mock_get_auth()


def get_balance(access_token: str) -> dict[str, Any]:
    """Get current balance for the primary account.

    Returns dict with available, current, and currency.
    """
    if _is_real():
        return _real_get_balance(access_token)
    return {
        'available': random.uniform(500, 5000),
        'current': random.uniform(500, 6000),
        'currency': 'USD',
        'method': 'mock',
    }


# ═══════════════════════════════════════════════════════════════
#  Real API calls
# ═══════════════════════════════════════════════════════════════

def _plaid_request(endpoint: str, payload: dict) -> dict:
    """Make a real Plaid API request."""
    import requests  # lazy import

    url = f'https://{PLAID_ENV}.plaid.com/{endpoint}'
    payload['client_id'] = PLAID_CLIENT_ID
    payload['secret'] = PLAID_SECRET
    headers = {'Content-Type': 'application/json'}

    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=30)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        log.error('Plaid API error on %s: %s', endpoint, e)
        raise


def _real_create_link_token(user_id: str, user_name: str = '') -> dict:
    user = {'client_user_id': user_id}
    if user_name:
        user['legal_name'] = user_name
    return _plaid_request('link/token/create', {
        'user': user,
        'client_name': 'SunCredit Lending',
        'products': ['transactions', 'auth'],
        'country_codes': ['US'],
        'language': 'en',
    })


def _real_exchange_token(public_token: str) -> dict:
    return _plaid_request('item/public_token/exchange', {
        'public_token': public_token,
    })


def _real_get_transactions(access_token: str, days: int = 90) -> dict:
    start = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
    end = datetime.now().strftime('%Y-%m-%d')
    return _plaid_request('transactions/get', {
        'access_token': access_token,
        'start_date': start,
        'end_date': end,
        'options': {'count': 500},
    })


def _real_get_accounts(access_token: str) -> list:
    resp = _plaid_request('accounts/get', {'access_token': access_token})
    return resp.get('accounts', [])


def _real_get_auth(access_token: str) -> dict:
    return _plaid_request('auth/get', {'access_token': access_token})


def _real_get_balance(access_token: str) -> dict:
    resp = _plaid_request('accounts/balance/get', {'access_token': access_token})
    accounts = resp.get('accounts', [])
    if accounts:
        bal = accounts[0].get('balances', {})
        return {
            'available': bal.get('available', 0),
            'current': bal.get('current', 0),
            'currency': bal.get('iso_currency_code', 'USD'),
        }
    return {'available': 0, 'current': 0, 'currency': 'USD'}


# ═══════════════════════════════════════════════════════════════
#  Mock data generators
# ═══════════════════════════════════════════════════════════════

def _mock_get_transactions(days: int = 90) -> dict:
    """Generate 90 days of realistic mock bank transactions."""
    rng = random.Random(42)
    transactions = []
    start = datetime.now() - timedelta(days=days)

    # Income pattern: bi-weekly deposits of ~$2,500
    for week in range(0, days // 14 + 1):
        txn_date = start + timedelta(days=week * 14 + rng.randint(0, 2))
        if txn_date <= datetime.now():
            base_income = 2500 + rng.gauss(0, 200)
            transactions.append({
                'transaction_id': f'mock_txn_inc_{week}',
                'date': txn_date.strftime('%Y-%m-%d'),
                'amount': round(max(1000, base_income), 2),
                'name': rng.choice(['ACME CORP PAYROLL', 'TECHNOLOGY INC DIRECT DEP',
                                    'GLOBAL SYSTEMS PAYROLL', 'DELTA SERVICES DD']),
                'category': ['INCOME', 'PAYROLL'],
                'pending': False,
            })

    # Housing payment (monthly)
    for month in range(days // 30 + 1):
        txn_date = start.replace(day=1) + timedelta(days=month * 30 + rng.randint(0, 3))
        if txn_date <= datetime.now():
            transactions.append({
                'transaction_id': f'mock_txn_rent_{month}',
                'date': txn_date.strftime('%Y-%m-%d'),
                'amount': -round(rng.uniform(800, 2000), 2),
                'name': rng.choice(['PROPERTY MGMT RENT PAYMENT', 'MORTGAGE PAYMENT - WELLS FARGO']),
                'category': ['HOUSING', 'RENT'],
                'pending': False,
            })

    # Regular expenses
    for day in range(days):
        txn_date = start + timedelta(days=day)
        if txn_date > datetime.now():
            break
        if rng.random() < 0.3:  # ~3 expenses per 10 days
            merchants = [
                (-round(rng.uniform(20, 150), 2), ['FOOD', 'GROCERY'],
                 ['KROGER', 'WALMART', 'SAFEWAY', 'WHOLE FOODS']),
                (-round(rng.uniform(5, 60), 2), ['TRANSPORT', 'GAS'],
                 ['SHELL OIL', 'CHEVRON', 'EXXON', 'UBER RIDE']),
                (-round(rng.uniform(5, 25), 2), ['ENTERTAINMENT', 'SUBSCRIPTION'],
                 ['NETFLIX', 'SPOTIFY', 'AMAZON PRIME', 'APPLE SUBSCRIPTION']),
                (-round(rng.uniform(10, 100), 2), ['UTILITIES'],
                 ['ELECTRIC COMPANY', 'WATER UTILITY', 'INTERNET PROVIDER']),
                (-round(rng.uniform(25, 200), 2), ['INSURANCE'],
                 ['GEICO INSURANCE', 'STATE FARM', 'AFLAC']),
            ]
            merchant = rng.choice(merchants)
            transactions.append({
                'transaction_id': f'mock_txn_exp_{day}',
                'date': txn_date.strftime('%Y-%m-%d'),
                'amount': merchant[0],
                'name': rng.choice(merchant[2]),
                'category': merchant[1],
                'pending': rng.random() < 0.05,
            })

    # Sort by date
    transactions.sort(key=lambda t: t['date'])

    return {
        'transactions': transactions,
        'total_transactions': len(transactions),
        'accounts': _mock_get_accounts(),
        'request_id': f'mock-req-{rng.randint(10000, 99999)}',
        'method': 'mock',
    }


def _mock_get_accounts() -> list[dict]:
    return [
        {
            'account_id': 'mock-checking-001',
            'name': 'Platinum Checking',
            'mask': '1234',
            'type': 'depository',
            'subtype': 'checking',
            'balances': {
                'available': 3420.50,
                'current': 3650.00,
                'iso_currency_code': 'USD',
                'limit': None,
            },
        },
        {
            'account_id': 'mock-savings-002',
            'name': 'High-Yield Savings',
            'mask': '5678',
            'type': 'depository',
            'subtype': 'savings',
            'balances': {
                'available': 12500.00,
                'current': 12500.00,
                'iso_currency_code': 'USD',
                'limit': None,
            },
        },
    ]


def _mock_get_auth() -> dict:
    return {
        'accounts': [
            {
                'account_id': 'mock-checking-001',
                'account_number': '123456789',
                'routing_number': '021000021',
                'wire_routing_number': '021000021',
            }
        ],
        'method': 'mock',
    }


# ═══════════════════════════════════════════════════════════════
#  Quick test
# ═══════════════════════════════════════════════════════════════
if __name__ == '__main__':
    print("Testing Plaid Integration (Mock Mode)")
    print("=" * 50)

    # Test 1: Link token
    lt = create_link_token('user_001', 'John Doe')
    print(f"\nLink Token: {lt['link_token'][:30]}...")
    print(f"  Expires: {lt['expiration']}")

    # Test 2: Exchange token
    at = exchange_public_token('public-sandbox-mock-12345')
    print(f"\nAccess Token: {at['access_token'][:30]}...")

    # Test 3: Get transactions
    txns = get_transactions(at['access_token'], 90)
    print(f"\nTransactions: {txns['total_transactions']} records")
    income_txns = [t for t in txns['transactions'] if t['amount'] > 0]
    expense_txns = [t for t in txns['transactions'] if t['amount'] < 0]
    total_income = sum(t['amount'] for t in income_txns)
    total_expenses = abs(sum(t['amount'] for t in expense_txns))
    print(f"  Income: ${total_income:.0f} across {len(income_txns)} txns")
    print(f"  Expenses: ${total_expenses:.0f} across {len(expense_txns)} txns")
    print(f"  Net: ${total_income - total_expenses:.0f}")

    # Test 4: Accounts
    accounts = get_accounts(at['access_token'])
    print(f"\nAccounts: {len(accounts)} linked")
    for acct in accounts:
        print(f"  - {acct['name']}: ${acct['balances']['available']:.0f}")

    # Test 5: Auth (ACH info)
    auth = get_auth(at['access_token'])
    print(f"\nACH: {auth['accounts'][0]['account_number']} "
          f"routing {auth['accounts'][0]['routing_number']}")

    print("\n✅ Plaid integration ready")
