#!/usr/bin/env python3
"""Cash Flow Underwriting Engine

Analyzes bank transaction data to derive cash flow metrics for underwriting.
Replaces reliance on self-reported income with actual income/expense analysis.

Can be used as:
1. REPLACEMENT scorer (for thin-file / gig workers)
2. ADJUSTMENT to existing credit score (blended score)

Key metrics produced:
- cash_flow_income: Monthly recurring income from deposits
- cash_flow_expenses: Monthly recurring expenses
- discretionary_income: Income - fixed expenses
- income_volatility: Coefficient of variation of monthly income
- expense_volatility: Coefficient of variation of monthly expenses
- overdraft_frequency: Number of overdrafts per month
- nsf_count: Number of insufficient funds events
- savings_rate: (Income - Expenses) / Income
- income_consistency: Score 0-1 based on regular deposit patterns
- paycheck_confidence: Whether income appears to be payroll (regular deposits)
- avg_daily_balance: Average daily balance across all months
- min_balance_ratio: Minimum balance / average income

Usage:
    from cash_flow import CashFlowAnalyzer
    analyzer = CashFlowAnalyzer()
    metrics = analyzer.analyze(transactions)
    # metrics is a dict with all the above fields

Transaction format (Plaid-like / OFX standard):
    [
        {
            'date': '2025-01-15',
            'amount': 2500.00,          # positive = deposit, negative = withdrawal
            'name': 'ACME CORP PAYROLL',
            'category': 'income',       # optional
        },
        ...
    ]
"""

import json
import math
import re
from datetime import datetime, timedelta
from collections import defaultdict


class CashFlowAnalyzer:
    """Analyze bank transaction data for underwriting signals."""

    INCOME_KEYWORDS = [
        'payroll', 'deposit', 'direct deposit', 'salary', 'wage',
        'income', 'payment', 'ach', 'credit', 'refund', 'transfer',
    ]
    
    EXPENSE_CATEGORIES = {
        'housing': ['rent', 'mortgage', 'property management', 'apartment'],
        'utilities': ['electric', 'power', 'gas', 'water', 'utility', 'internet', 'phone'],
        'insurance': ['insurance', 'aflac', 'geico', 'progressive', 'allstate', 'state farm'],
        'transportation': ['gas station', 'shell', 'chevron', 'exxon', 'uber', 'lyft', 'parking'],
        'food': ['grocery', 'walmart', 'target', 'kroger', 'safeway', 'whole foods', 'restaurant'],
        'debt': ['credit card', 'loan payment', 'student loan', 'minimum payment'],
        'subscription': ['netflix', 'spotify', 'amazon prime', 'hulu', 'apple', 'subscription'],
    }

    def __init__(self):
        self.metrics = {}
        self._transactions = []

    def analyze(self, transactions, num_months=3):
        """Main entry point. Returns dict of cash flow metrics."""
        if not transactions or len(transactions) < 5:
            return self._empty_metrics()
        
        self._transactions = sorted(transactions, key=lambda t: t.get('date', ''))
        
        # Parse dates
        parsed = []
        for t in self._transactions:
            try:
                d = datetime.strptime(t['date'], '%Y-%m-%d')
                parsed.append({**t, '_parsed_date': d})
            except (ValueError, KeyError):
                continue
        
        if len(parsed) < 5:
            return self._empty_metrics()
        
        # Group by month
        monthly = defaultdict(lambda: {'deposits': [], 'withdrawals': [], 'all': []})
        for t in parsed:
            key = t['_parsed_date'].strftime('%Y-%m')
            monthly[key]['all'].append(t)
            if t.get('amount', 0) > 0:
                monthly[key]['deposits'].append(t)
            else:
                monthly[key]['withdrawals'].append(t)
        
        months = sorted(monthly.keys())
        if len(months) < 1:
            return self._empty_metrics()
        
        # Use last num_months of data
        months = months[-num_months:]
        
        # ---- Income Analysis ----
        monthly_income = []
        for m in months:
            dep = monthly[m]['deposits']
            # Filter to likely income (regular deposits, not transfers between accounts)
            income = [d for d in dep if self._is_likely_income(d)]
            total = sum(d['amount'] for d in income)
            monthly_income.append(total)
        
        avg_income = sum(monthly_income) / len(monthly_income) if monthly_income else 0
        
        # Income volatility
        income_vol = self._coefficient_of_variation(monthly_income) if len(monthly_income) > 1 else 0.5
        
        # Income consistency score
        income_consistency = self._score_income_consistency(parsed)
        
        # Paycheck confidence
        paycheck_conf = self._detect_paycheck_pattern(parsed)
        
        # ---- Expense Analysis ----
        monthly_expenses = []
        for m in months:
            wd = monthly[m]['withdrawals']
            total = abs(sum(t['amount'] for t in wd))
            monthly_expenses.append(total)
        
        avg_expenses = sum(monthly_expenses) / len(monthly_expenses) if monthly_expenses else 0
        expense_vol = self._coefficient_of_variation(monthly_expenses) if len(monthly_expenses) > 1 else 0.5
        
        # ---- Derived Metrics ----
        discretionary = max(0, avg_income - avg_expenses)
        savings_rate = (avg_income - avg_expenses) / max(1, avg_income)
        
        # ---- Risk Signals ----
        overdraft_freq = self._count_overdrafts(parsed) / max(1, len(months))
        nsf_count = self._count_nsf(parsed)
        
        # ---- Balance Analysis ----
        daily_balances = self._compute_daily_balances(parsed)
        avg_daily = sum(daily_balances) / len(daily_balances) if daily_balances else 0
        min_balance = min(daily_balances) if daily_balances else 0
        min_balance_ratio = min_balance / max(1, avg_income) if avg_income > 0 else -1
        
        # ---- Expense Breakdown ----
        expense_breakdown = self._categorize_expenses(parsed)
        housing_ratio = expense_breakdown.get('housing', 0) / max(1, avg_income)
        total_debt_payments = expense_breakdown.get('debt', 0)
        
        # ---- Cash Flow Score (0-100, higher = better) ----
        cash_flow_score = self._compute_cash_flow_score({
            'avg_income': avg_income,
            'avg_expenses': avg_expenses,
            'discretionary': discretionary,
            'income_vol': income_vol,
            'savings_rate': savings_rate,
            'overdraft_freq': overdraft_freq,
            'nsf_count': nsf_count,
            'income_consistency': income_consistency,
            'paycheck_conf': paycheck_conf,
            'avg_daily': avg_daily,
            'min_balance_ratio': min_balance_ratio,
            'housing_ratio': housing_ratio,
        })
        
        return {
            'cash_flow_income': round(avg_income, 2),
            'cash_flow_expenses': round(avg_expenses, 2),
            'discretionary_income': round(discretionary, 2),
            'income_volatility': round(income_vol, 4),
            'expense_volatility': round(expense_vol, 4),
            'overdraft_frequency': round(overdraft_freq, 2),
            'nsf_count': nsf_count,
            'savings_rate': round(savings_rate, 4),
            'income_consistency': round(income_consistency, 4),
            'paycheck_confidence': round(paycheck_conf, 4),
            'avg_daily_balance': round(avg_daily, 2),
            'min_balance_ratio': round(min_balance_ratio, 4),
            'housing_ratio': round(housing_ratio, 4),
            'total_monthly_debt': round(total_debt_payments, 2),
            'expense_breakdown': {k: round(v, 2) for k, v in expense_breakdown.items()},
            'cash_flow_score': cash_flow_score,
            'months_analyzed': len(months),
            'total_transactions': len(parsed),
        }

    def _empty_metrics(self):
        return {
            'cash_flow_income': 0,
            'cash_flow_expenses': 0,
            'discretionary_income': 0,
            'income_volatility': 1.0,
            'expense_volatility': 1.0,
            'overdraft_frequency': 1.0,
            'nsf_count': 5,
            'savings_rate': 0,
            'income_consistency': 0,
            'paycheck_confidence': 0,
            'avg_daily_balance': 0,
            'min_balance_ratio': -1,
            'housing_ratio': 0.5,
            'total_monthly_debt': 0,
            'expense_breakdown': {},
            'cash_flow_score': 20,
            'months_analyzed': 0,
            'total_transactions': 0,
        }

    def _is_likely_income(self, transaction):
        """Determine if a deposit is likely income (not transfer between own accounts)."""
        name = transaction.get('name', '').lower()
        amount = transaction.get('amount', 0)
        
        # Must be a deposit
        if amount <= 0:
            return False
        
        # Too small to be income
        if amount < 50:
            return False
        
        # Check for income keywords
        if any(kw in name for kw in self.INCOME_KEYWORDS):
            return True
        
        # Regular ACH deposits
        if 'ach' in name and amount >= 100:
            return True
        
        # Large recurring deposits (likely gig work / freelance)
        if amount >= 100:
            return True
        
        return False

    def _detect_paycheck_pattern(self, transactions):
        """Detect regular paycheck patterns (bi-weekly, semi-monthly, weekly)."""
        deposits = [t for t in transactions if self._is_likely_income(t)]
        
        if len(deposits) < 4:
            return 0.0
        
        # Sort by date
        deposits.sort(key=lambda t: t['_parsed_date'])
        
        # Check gaps between deposits
        gaps = []
        for i in range(1, len(deposits)):
            gap = (deposits[i]['_parsed_date'] - deposits[i-1]['_parsed_date']).days
            gaps.append(gap)
        
        if not gaps:
            return 0.0
        
        avg_gap = sum(gaps) / len(gaps)
        
        # Bi-weekly (14-16 days) or semi-monthly (13-17 days)
        if 12 <= avg_gap <= 18:
            return self._gap_consistency_score(gaps, 14)
        
        # Monthly (28-35 days)
        if 25 <= avg_gap <= 35:
            return self._gap_consistency_score(gaps, 30)
        
        # Weekly (6-8 days)
        if 5 <= avg_gap <= 9:
            return self._gap_consistency_score(gaps, 7)
        
        # Irregular
        if 18 < avg_gap < 25:
            return 0.5  # Semi-monthly pattern (1st and 15th)
        
        return 0.3

    def _gap_consistency_score(self, gaps, expected):
        """Score how consistently deposits match expected interval (0-1)."""
        if not gaps:
            return 0.0
        deviations = [abs(g - expected) for g in gaps]
        avg_dev = sum(deviations) / len(deviations)
        # Under 2 days deviation = perfect, over 7 = poor
        score = max(0, 1 - (avg_dev - 1) / 6)
        return min(1.0, score)

    def _score_income_consistency(self, transactions):
        """Score income consistency based on regular deposit patterns."""
        deposits = [t for t in transactions if self._is_likely_income(t) and t.get('amount', 0) > 200]
        
        if len(deposits) < 3:
            return 0.0
        
        # Check amount consistency
        amounts = [d['amount'] for d in deposits]
        if len(amounts) > 1:
            cv = self._coefficient_of_variation(amounts)
            # Low CV = consistent amounts
            amount_score = max(0, 1 - cv * 2)
        else:
            amount_score = 0.5
        
        # Check timing consistency
        timing_score = self._detect_paycheck_pattern(transactions)
        
        return (amount_score * 0.4 + timing_score * 0.6)

    def _count_overdrafts(self, transactions):
        """Count overdraft/overdrawn events."""
        count = 0
        for t in transactions:
            name = t.get('name', '').lower()
            if any(kw in name for kw in ['overdraft', 'overdrawn', 'nsf', 'insufficient', 'overdraft fee']):
                count += 1
        return count

    def _count_nsf(self, transactions):
        """Count NSF (non-sufficient funds) events."""
        count = 0
        for t in transactions:
            name = t.get('name', '').lower()
            if any(kw in name for kw in ['nsf', 'insufficient funds', 'returned check', 'returned payment', 'non-sufficient']):
                count += 1
        return count

    def _categorize_expenses(self, transactions):
        """Categorize recurring expenses."""
        categories = defaultdict(float)
        
        for t in transactions:
            if t.get('amount', 0) >= 0:
                continue  # Skip deposits
            name = t.get('name', '').lower()
            amount = abs(t['amount'])
            
            categorized = False
            for cat, keywords in self.EXPENSE_CATEGORIES.items():
                if any(kw in name for kw in keywords):
                    categories[cat] += amount
                    categorized = True
                    break
            
            if not categorized and amount >= 50:
                categories['other'] += amount
        
        # Divide by months to get monthly
        if len(self._transactions) > 0:
            # Rough month count
            month_count = max(1, len(self._transactions) / 30)
            for k in categories:
                categories[k] /= month_count
        
        return dict(categories)

    def _compute_daily_balances(self, transactions):
        """Simulate daily account balances from transactions."""
        if not transactions:
            return []
        
        start_date = transactions[0]['_parsed_date']
        end_date = transactions[-1]['_parsed_date']
        days = (end_date - start_date).days
        
        if days < 1:
            return [1000]  # Default
        
        # Start with starting balance (simulated)
        balance = 1000
        balances = []
        current_date = start_date
        
        # Create date → net amount map
        daily_net = defaultdict(float)
        for t in transactions:
            daily_net[t['_parsed_date'].strftime('%Y-%m-%d')] += t.get('amount', 0)
        
        for i in range(days + 1):
            d = (start_date + timedelta(days=i)).strftime('%Y-%m-%d')
            balance += daily_net.get(d, 0)
            balance = max(-500, balance)  # Allow small overdraft
            balances.append(balance)
        
        return balances

    def _coefficient_of_variation(self, values):
        """Calculate coefficient of variation (std/mean)."""
        clean = [v for v in values if v > 0]
        if len(clean) < 2:
            return 0.5
        mean = sum(clean) / len(clean)
        if mean == 0:
            return 1.0
        variance = sum((v - mean) ** 2 for v in clean) / len(clean)
        return math.sqrt(variance) / mean

    def _compute_cash_flow_score(self, metrics):
        """Compute a composite cash flow health score (0-100, higher = better)."""
        score = 50  # Start at neutral
        
        # Income level (up to +15)
        if metrics['avg_income'] >= 5000:
            score += 10
        elif metrics['avg_income'] >= 3000:
            score += 7
        elif metrics['avg_income'] >= 2000:
            score += 3
        
        # Discretionary income (up to +15)
        ratio = metrics['discretionary'] / max(1, metrics['avg_income'])
        score += ratio * 15
        
        # Income volatility penalty (up to -15)
        score -= metrics['income_vol'] * 15
        
        # Savings rate (up to +10)
        score += metrics['savings_rate'] * 10
        
        # Overdraft penalty (up to -15)
        score -= min(15, metrics['overdraft_freq'] * 5)
        
        # NSF penalty (up to -15 each)
        score -= min(15, metrics['nsf_count'] * 7)
        
        # Income consistency bonus (up to +10)
        score += metrics['income_consistency'] * 10
        
        # Paycheck confidence bonus (up to +10)
        score += metrics['paycheck_conf'] * 10
        
        # Housing ratio penalty (up to -10)
        if metrics['housing_ratio'] > 0.5:
            score -= min(10, (metrics['housing_ratio'] - 0.4) * 20)
        
        # Min balance positive bonus (up to +5)
        if metrics['min_balance_ratio'] >= 0.1:
            score += 5
        elif metrics['min_balance_ratio'] >= 0.05:
            score += 2
        
        # Daily balance bonus (up to +5)
        if metrics['avg_daily'] >= 3000:
            score += 5
        elif metrics['avg_daily'] >= 1500:
            score += 3
        elif metrics['avg_daily'] >= 500:
            score += 1
        
        return max(0, min(100, int(round(score))))


# ---------------------------------------------------------------------------
# Demo data generator — creates realistic bank transactions
# ---------------------------------------------------------------------------

def generate_demo_transactions(profile='good'):
    """Generate 90 days of realistic bank transactions for testing.
    
    Profiles: 'good', 'average', 'thin', 'gig_worker', 'risky'
    """
    base_date = datetime.now() - timedelta(days=90)
    transactions = []
    
    patterns = {
        'good': {
            'income': 5500,
            'income_interval': 14,  # bi-weekly
            'misc_expenses': 1200,
            'overdrafts': 0,
            'nsf': 0,
        },
        'average': {
            'income': 3800,
            'income_interval': 14,
            'misc_expenses': 1600,
            'overdrafts': 1,
            'nsf': 0,
        },
        'thin': {
            'income': 2500,
            'income_interval': 7,  # weekly
            'misc_expenses': 1300,
            'overdrafts': 2,
            'nsf': 1,
        },
        'gig_worker': {
            'income': 4200,
            'income_interval': 0,  # irregular
            'misc_expenses': 1100,
            'overdrafts': 0,
            'nsf': 0,
        },
        'risky': {
            'income': 2000,
            'income_interval': 0,
            'misc_expenses': 1900,
            'overdrafts': 5,
            'nsf': 3,
        },
    }
    
    p = patterns.get(profile, patterns['average'])
    current_date = base_date
    
    # Income deposits
    if p['income_interval'] > 0:
        income_dates = []
        d = base_date
        while d < datetime.now():
            income_dates.append(d)
            d += timedelta(days=p['income_interval'])
        
        for d in income_dates:
            transactions.append({
                'date': d.strftime('%Y-%m-%d'),
                'amount': p['income'],
                'name': 'ACME CORP PAYROLL',
                'category': 'income',
            })
            current_date = d
    else:
        # Irregular income (gig worker)
        import random
        random.seed(42)
        d = base_date
        for _ in range(8):
            transactions.append({
                'date': d.strftime('%Y-%m-%d'),
                'amount': random.randint(300, 1200),
                'name': random.choice(['UBER PAYMENT', 'UPWORK DEPOSIT', 'FIVERR PAYMENT', 'DOORDASH PAYOUT', 'VENMO']),
                'category': 'income',
            })
            d += timedelta(days=random.randint(5, 14))
    
    # Recurring expenses
    expenses = [
        ('RENT PAYMENT', 1500, 30),
        ('PG&E ELECTRIC', 85, 30),
        ('COMCAST INTERNET', 75, 30),
        ('VERIZON WIRELESS', 95, 30),
        ('T-MOBILE', 120, 30),
        ('GEICO INSURANCE', 145, 30),
        ('NETFLIX', 18, 30),
        ('SPOTIFY', 12, 30),
        ('AMAZON PRIME', 15, 30),
        ('CREDIT CARD PAYMENT', 350, 30),
        ('CAR LOAN PAYMENT', 420, 30),
        ('STUDENT LOAN PAYMENT', 280, 30),
    ]
    
    # Randomize which expenses apply
    import random
    random.seed(42 + hash(profile) % 1000)
    
    start_offset = random.randint(1, 28)
    for name, amount, interval in expenses:
        if random.random() < 0.3:  # Skip some expenses
            continue
        d = base_date + timedelta(days=start_offset)
        while d < datetime.now():
            transactions.append({
                'date': d.strftime('%Y-%m-%d'),
                'amount': -amount,
                'name': name,
                'category': 'expense',
            })
            d += timedelta(days=interval)
    
    # Overdrafts
    for i in range(p['overdrafts']):
        d = base_date + timedelta(days=random.randint(10, 80))
        transactions.append({
            'date': d.strftime('%Y-%m-%d'),
            'amount': -35,
            'name': 'OVERDRAFT FEE',
            'category': 'fee',
        })
    
    # NSF events
    for i in range(p['nsf']):
        d = base_date + timedelta(days=random.randint(15, 75))
        transactions.append({
            'date': d.strftime('%Y-%m-%d'),
            'amount': -25,
            'name': 'NSF FEE',
            'category': 'fee',
        })
    
    # Misc spending
    for _ in range(int(p['misc_expenses'] / 25)):
        d = base_date + timedelta(days=random.randint(1, 89))
        transactions.append({
            'date': d.strftime('%Y-%m-%d'),
            'amount': -abs(random.gauss(25, 15)),
            'name': random.choice(['AMAZON', 'WALMART', 'KROGER', 'SHELL GAS', 'STARBUCKS', 'DOORDASH', 'MCDONALDS']),
            'category': 'misc',
        })
    
    # Sort by date
    transactions.sort(key=lambda t: t['date'])
    return transactions


def test_analyzer():
    """Run a quick test on all profiles."""
    analyzer = CashFlowAnalyzer()
    
    for profile in ['good', 'average', 'thin', 'gig_worker', 'risky']:
        txns = generate_demo_transactions(profile)
        metrics = analyzer.analyze(txns)
        print(f"\n{'='*50}")
        print(f"PROFILE: {profile.upper()}")
        print(f"{'='*50}")
        print(f"Monthly Income:    ${metrics['cash_flow_income']:>8.2f}")
        print(f"Monthly Expenses:  ${metrics['cash_flow_expenses']:>8.2f}")
        print(f"Discretionary:     ${metrics['discretionary_income']:>8.2f}")
        print(f"Income Volatility:  {metrics['income_volatility']:>8.4f}")
        print(f"Overdraft Freq:     {metrics['overdraft_frequency']:>8.2f}/mo")
        print(f"NSF Count:          {metrics['nsf_count']:>8d}")
        print(f"Savings Rate:       {metrics['savings_rate']:>8.4f}")
        print(f"Income Consistency: {metrics['income_consistency']:>8.4f}")
        print(f"Paycheck Conf:      {metrics['paycheck_confidence']:>8.4f}")
        print(f"Avg Daily Bal:     ${metrics['avg_daily_balance']:>8.2f}")
        print(f"Cash Flow Score:    {metrics['cash_flow_score']:>8d}/100")
        print(f"  → (risk {max(0, 100-metrics['cash_flow_score'])})")


if __name__ == '__main__':
    test_analyzer()
