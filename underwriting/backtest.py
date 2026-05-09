#!/usr/bin/env python3
"""Backtesting and validation for the credit underwriting engine."""

import csv
import json
import os
import sys
import numpy as np

from scorer import LoanScorer
from pricing import PricingEngine

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def load_test_data(filepath):
    """Load test CSV data."""
    data = []
    with open(filepath, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            row['age'] = int(row['age'])
            row['annual_income'] = float(row['annual_income'])
            row['employment_length'] = float(row['employment_length'])
            row['credit_score'] = int(row['credit_score'])
            row['dti_ratio'] = float(row['dti_ratio'])
            row['utilization'] = float(row['utilization'])
            row['num_derogatory'] = int(row['num_derogatory'])
            row['num_credit_lines'] = int(row['num_credit_lines'])
            row['loan_amount'] = float(row['loan_amount'])
            row['default_flag'] = int(row['default_flag'])
            data.append(row)
    return data


def compute_auc_fast(y_true, y_pred):
    """Fast AUC computation."""
    n = len(y_true)
    pairs = list(zip(y_pred, y_true))
    pairs.sort(key=lambda x: -x[0])
    
    n_pos = int(sum(y_true))
    n_neg = n - n_pos
    
    if n_pos == 0 or n_neg == 0:
        return 0.5
    
    rank_sum = 0
    for i, (_, label) in enumerate(pairs):
        if label == 1:
            rank_sum += (i + 1)
    
    u = rank_sum - (n_pos * (n_pos + 1)) / 2
    auc = u / (n_pos * n_neg)
    return auc


def precision_at_k(y_true, y_pred_scores, k):
    """Precision at top K by predicted risk (lower score = better)."""
    # Sort by predicted probability descending (highest risk first)
    pairs = list(zip(y_pred_scores, y_true))
    pairs.sort(key=lambda x: -x[0])
    
    top_k = pairs[:k]
    n_defaults_in_top_k = sum(label for _, label in top_k)
    return n_defaults_in_top_k / max(1, k)


def simulate_profit(y_true, y_pred_probs, approval_threshold, 
                     good_profit_rate=0.15, default_loss_rate=0.60, 
                     operating_cost_rate=0.03):
    """Simulate lending profit given an approval threshold.
    
    We approve borrowers with predicted default prob < approval_threshold.
    
    Args:
        y_true: actual default flags (0=good, 1=default)
        y_pred_probs: predicted default probabilities
        approval_threshold: only approve if prob < this
        good_profit_rate: profit from a good loan (% of amount)
        default_loss_rate: loss from a default (% of amount)
        operating_cost_rate: cost to service (% of amount)
        
    Returns:
        dict with profit simulation results
    """
    n = len(y_true)
    approved = y_pred_probs < approval_threshold
    n_approved = int(np.sum(approved))
    
    if n_approved == 0:
        return {
            'n_approved': 0,
            'n_good': 0,
            'n_defaults': 0,
            'total_profit': 0.0,
            'total_loss': 0.0,
            'operating_cost': 0.0,
            'net_profit': 0.0,
            'roi': 0.0,
            'approval_rate': 0.0,
            'default_rate_among_approved': 0.0,
        }
    
    approved_defaults = y_true[approved]
    n_good = int(np.sum(approved_defaults == 0))
    n_bad = int(np.sum(approved_defaults == 1))
    
    # Assume each loan is $10,000 for simplicity
    avg_loan = 10000.0
    
    gross_profit = n_good * avg_loan * good_profit_rate
    default_loss = n_bad * avg_loan * default_loss_rate
    op_cost = n_approved * avg_loan * operating_cost_rate
    
    net_profit = gross_profit - default_loss - op_cost
    total_loaned = n_approved * avg_loan
    roi = (net_profit / total_loaned * 100) if total_loaned > 0 else 0.0
    
    return {
        'n_approved': n_approved,
        'n_good': n_good,
        'n_defaults': n_bad,
        'total_profit': round(gross_profit, 2),
        'total_loss': round(default_loss, 2),
        'operating_cost': round(op_cost, 2),
        'net_profit': round(net_profit, 2),
        'roi': round(roi, 2),
        'approval_rate': round(n_approved / n * 100, 2),
        'default_rate_among_approved': round(n_bad / n_approved * 100, 2),
    }


def print_confusion_matrix(y_true, y_pred_binary):
    """Print confusion matrix."""
    tp = int(np.sum((y_pred_binary == 1) & (y_true == 1)))
    fp = int(np.sum((y_pred_binary == 1) & (y_true == 0)))
    tn = int(np.sum((y_pred_binary == 0) & (y_true == 0)))
    fn = int(np.sum((y_pred_binary == 0) & (y_true == 1)))
    
    print("               Predicted")
    print("               Default  Non-Default")
    print(f" Actual Default   {tp:4d}      {fn:4d}")
    print(f"       Non-Default {fp:4d}      {tn:4d}")
    print()
    print(f" Precision: {tp/max(1,tp+fp):.4f}")
    print(f" Recall:    {tp/max(1,tp+fn):.4f}")
    print(f" F1 Score:  {2*tp/max(1,2*tp+fp+fn):.4f}")
    print(f" Accuracy:  {(tp+tn)/max(1,len(y_true)):.4f}")
    
    return {
        'tp': tp, 'fp': fp, 'tn': tn, 'fn': fn,
        'precision': tp/max(1,tp+fp),
        'recall': tp/max(1,tp+fn),
        'f1': 2*tp/max(1,2*tp+fp+fn),
        'accuracy': (tp+tn)/max(1,len(y_true)),
    }


def main():
    print("=" * 70)
    print("  CREDIT UNDERWRITING ENGINE - BACKTESTING & VALIDATION")
    print("=" * 70)
    
    # 1. Load model
    print("\n[1] Loading model...")
    scorer = LoanScorer()
    model_path = os.path.join(BASE_DIR, 'model_weights.json')
    
    if not os.path.exists(model_path):
        print("  ERROR: No model found. Run train.py first.")
        sys.exit(1)
    
    scorer.load(model_path)
    
    # 2. Load test data
    print("\n[2] Loading test data...")
    test_file = os.path.join(BASE_DIR, 'test.csv')
    if not os.path.exists(test_file):
        print("  ERROR: Test data not found. Run data_generator.py first.")
        sys.exit(1)
    
    test_data = load_test_data(test_file)
    print(f"  Loaded {len(test_data)} test samples")
    
    test_defaults = sum(1 for d in test_data if d['default_flag'] == 1)
    print(f"  Actual default rate: {test_defaults}/{len(test_data)} = "
          f"{100*test_defaults/len(test_data):.1f}%")
    
    # 3. Score all applications
    print("\n[3] Scoring all applications...")
    y_true = np.array([d['default_flag'] for d in test_data], dtype=np.float64)
    y_pred_probs = np.zeros(len(test_data), dtype=np.float64)
    results = []
    
    for i, row in enumerate(test_data):
        app_data = {
            'age': row['age'],
            'annual_income': row['annual_income'],
            'employment_length': row['employment_length'],
            'credit_score': row['credit_score'],
            'dti_ratio': row['dti_ratio'],
            'utilization': row['utilization'],
            'num_derogatory': row['num_derogatory'],
            'num_credit_lines': row['num_credit_lines'],
            'home_ownership': row['home_ownership'],
            'loan_amount': row['loan_amount'],
            'loan_purpose': row['loan_purpose'],
        }
        result = scorer.score_application(app_data)
        y_pred_probs[i] = result['probability_of_default']
        results.append(result)
    
    # 4. Binary classification metrics
    print("\n[4] Binary Classification Metrics:")
    print("-" * 50)
    
    auc = compute_auc_fast(y_true, y_pred_probs)
    print(f"\n  AUC: {auc:.4f}")
    
    # Confusion matrix at default threshold of 0.5
    print("\n  Confusion Matrix (threshold=0.5):")
    y_pred_05 = (y_pred_probs >= 0.5).astype(np.int64)
    cm = print_confusion_matrix(y_true, y_pred_05)
    
    # Metrics at various thresholds
    print("\n  Metrics at different thresholds:")
    print(f"  {'Threshold':>10s} {'Prec':>6s} {'Recall':>6s} {'F1':>6s} {'Acc':>6s} {'APR Rate':>9s}")
    print(f"  {'-'*8} {'-'*6} {'-'*6} {'-'*6} {'-'*6} {'-'*9}")
    
    for thresh in [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8]:
        y_bin = (y_pred_probs >= thresh).astype(np.int64)
        tp = int(np.sum((y_bin == 1) & (y_true == 1)))
        fp = int(np.sum((y_bin == 1) & (y_true == 0)))
        tn = int(np.sum((y_bin == 0) & (y_true == 0)))
        fn = int(np.sum((y_bin == 0) & (y_true == 1)))
        
        prec = tp / max(1, tp + fp)
        rec = tp / max(1, tp + fn)
        f1 = 2 * prec * rec / max(1e-10, prec + rec)
        acc = (tp + tn) / max(1, len(y_true))
        apr_rate = np.sum(y_bin) / len(y_true) * 100
        
        print(f"  {thresh:>10.1f} {prec:>6.4f} {rec:>6.4f} {f1:>6.4f} {acc:>6.4f} {apr_rate:>8.2f}%")
    
    # 5. Profit simulation
    print("\n[5] Profit Simulation (avg loan=$10,000):")
    print("-" * 50)
    print(f"  Good loan profit: 15% of loan amount")
    print(f"  Default loss:     60% of loan amount")
    print(f"  Operating cost:   3% of loan amount")
    print()
    print(f"  {'Threshold':>10s} {'Approved':>8s} {'Good':>6s} {'Bad':>6s} {'Net Profit':>12s} {'ROI':>8s}")
    print(f"  {'-'*8} {'-'*8} {'-'*6} {'-'*6} {'-'*12} {'-'*8}")
    
    best_profit = -float('inf')
    best_threshold = 0.0
    
    for thresh in [0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.35, 0.4, 0.45, 0.5, 0.55, 0.6]:
        sim = simulate_profit(y_true, y_pred_probs, thresh)
        print(f"  {thresh:>10.2f} {sim['n_approved']:>8d} {sim['n_good']:>6d} {sim['n_defaults']:>6d} "
              f"${sim['net_profit']:>9.2f} {sim['roi']:>7.2f}%")
        
        if sim['net_profit'] > best_profit and sim['n_approved'] > 0:
            best_profit = sim['net_profit']
            best_threshold = thresh
    
    print(f"\n  Optimal approval threshold: {best_threshold:.2f} "
          f"(max profit = ${best_profit:.2f})")
    
    # 6. Risk tier distribution
    print("\n[6] Risk Tier Distribution:")
    print("-" * 50)
    from collections import Counter
    tier_counts = Counter(r['risk_tier'] for r in results)
    for tier in ['A', 'B', 'C', 'D', 'E']:
        count = tier_counts.get(tier, 0)
        pct = count / len(results) * 100
        print(f"  Tier {tier}: {count:4d} ({pct:5.1f}%)")
    
    # 7. Default rate by tier
    print("\n[7] Actual Default Rate by Predicted Tier:")
    print("-" * 50)
    tier_defaults = {}
    for i, r in enumerate(results):
        tier = r['risk_tier']
        if tier not in tier_defaults:
            tier_defaults[tier] = {'total': 0, 'defaults': 0}
        tier_defaults[tier]['total'] += 1
        if y_true[i] == 1:
            tier_defaults[tier]['defaults'] += 1
    
    for tier in ['A', 'B', 'C', 'D', 'E']:
        if tier in tier_defaults:
            d = tier_defaults[tier]
            rate = d['defaults'] / max(1, d['total']) * 100
            print(f"  Tier {tier}: {d['defaults']}/{d['total']} defaults = {rate:.1f}%")
    
    # 8. Precision at different approval rates
    print("\n[8] Precision at K (identifying defaults):")
    print("-" * 50)
    for pct in [1, 5, 10, 20, 30]:
        k = max(1, int(len(y_true) * pct / 100))
        prec = precision_at_k(y_true, y_pred_probs, k)
        print(f"  Top {pct:2d}% ({k:3d} applications): {prec:.4f} default rate "
              f"(vs overall {np.mean(y_true):.4f})")
    
    print("\n" + "=" * 70)
    print("  BACKTEST SUMMARY")
    print("=" * 70)
    
    # Optimal threshold recommendation
    sim_best = simulate_profit(y_true, y_pred_probs, best_threshold)
    sim_default = simulate_profit(y_true, y_pred_probs, 0.5)
    
    print(f"\n  Recommended approval threshold: {best_threshold:.2f}")
    print(f"  At this threshold:")
    print(f"    Approval rate: {sim_best['approval_rate']:.1f}%")
    print(f"    Default rate among approved: {sim_best['default_rate_among_approved']:.1f}%")
    print(f"    Expected net profit: ${sim_best['net_profit']:.2f}")
    print(f"    ROI: {sim_best['roi']:.2f}%")
    print()
    print(f"  Model AUC on test set: {auc:.4f}")
    print(f"  Precision (threshold=0.5): {cm['precision']:.4f}")
    print(f"  Recall (threshold=0.5):    {cm['recall']:.4f}")
    print(f"  F1 Score (threshold=0.5):  {cm['f1']:.4f}")
    
    print("\nDone!")


if __name__ == '__main__':
    main()
