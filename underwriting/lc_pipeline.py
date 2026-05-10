#!/usr/bin/env python3
"""
LendingClub → PalmFi Model Pipeline
=====================================
Downloads, maps, and trains the underwriting model on real LendingClub data.
Maps 151 LC columns → 11 model features + default_flag.
"""

import csv
import gzip
import json
import math
import os
import random
import sys
from collections import Counter
from datetime import datetime

import numpy as np

# ── Paths ──
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LC_DIR = os.path.expanduser(
    "~/.cache/kagglehub/datasets/wordsforthewise/lending-club/versions/3"
)

# Add underwriting to path for importing model classes
sys.path.insert(0, BASE_DIR)

from feature_engineer import CreditFeatureEngineer
from ensemble_model import CreditEnsemble
from train import compute_auc_fast, compute_metrics


def parse_emp_length(s):
    """Parse '10+ years', '< 1 year', '2 years', empty → years float."""
    if not s or s.strip() == '':
        return 0.0
    s = s.strip().lower()
    if s == '< 1 year':
        return 0.5
    if s == '10+ years':
        return 10.0
    if s == 'n/a':
        return 0.0
    # format: "2 years"
    parts = s.split()
    try:
        return float(parts[0])
    except (ValueError, IndexError):
        return 0.0


def parse_home_ownership(s):
    """Normalize home ownership to rent/mortgage/own."""
    s = s.strip().upper() if s else ''
    if s in ('MORTGAGE', 'OWN', 'RENT'):
        return s.lower()
    if s in ('NONE', 'OTHER', 'ANY'):
        return 'rent'
    return 'rent'


def parse_purpose(s):
    """Normalize loan purpose to our categories."""
    mapping = {
        'debt_consolidation': 'debt_consolidation',
        'credit_card': 'debt_consolidation',
        'home_improvement': 'home_improvement',
        'major_purchase': 'personal',
        'small_business': 'business',
        'business': 'business',
        'medical': 'medical',
        'educational': 'education',
        'education': 'education',
        'moving': 'personal',
        'vacation': 'personal',
        'wedding': 'personal',
        'house': 'home_improvement',
        'car': 'auto',
        'renewable_energy': 'home_improvement',
        'other': 'personal',
    }
    key = s.strip().lower() if s else 'personal'
    return mapping.get(key, 'personal')


def parse_term(s):
    """Parse '36 months' → 36"""
    if not s:
        return 36
    try:
        return int(s.strip().split()[0])
    except (ValueError, IndexError):
        return 36


def parse_percent(s):
    """Parse '13.99%' → 0.1399"""
    if not s or s.strip() == '':
        return 0.0
    try:
        return float(s.strip().rstrip('%')) / 100.0
    except ValueError:
        return 0.0


def estimate_age(emp_years, earliest_cr_line, issue_d):
    """Estimate borrower age from employment length and credit history."""
    # Base age: assume person starts working at ~22
    base_age = 22.0

    # Add employment years
    age_from_emp = base_age + emp_years

    # Credit history: earliest_cr_line format like "Aug-2003"
    # If someone opened credit in 2003, they were likely at least 18-22 then
    try:
        if earliest_cr_line and earliest_cr_line.strip():
            cr_date = datetime.strptime(earliest_cr_line.strip(), '%b-%Y')
            issue_date = datetime.strptime(issue_d.strip(), '%b-%Y')
            years_since_first_credit = (issue_date - cr_date).days / 365.25
            age_from_credit = 18.0 + years_since_first_credit
        else:
            age_from_credit = age_from_emp
    except (ValueError, AttributeError):
        age_from_credit = age_from_emp

    # Take higher estimate + add ~2 years for education/post-grad
    estimated = max(age_from_emp, age_from_credit) + 2.0
    return int(min(75, max(18, round(estimated))))


def parse_loan_status(status):
    """Map loan_status to default_flag (0=paid, 1=defaulted)."""
    if not status:
        return None
    s = status.strip().upper()

    # Clearly good
    if s in ('FULLY PAID', 'DOES NOT MEET THE CREDIT POLICY. STATUS:FULLY PAID'):
        return 0

    # Clearly bad
    if s in (
        'CHARGED OFF', 'DEFAULT', 'DOES NOT MEET THE CREDIT POLICY. STATUS:CHARGED OFF',
        'LATE (31-120 DAYS)', 'LATE (16-30 DAYS)',
        'IN GRACE PERIOD',
    ):
        return 1

    # Currently active — skip (can't determine outcome)
    if s in ('CURRENT', 'ISSUED'):
        return None

    # Sub-funded or other — skip these edge cases
    return None


def map_row(row):
    """Map a single LC CSV row to our model format."""
    try:
        # ── Core mapped features ──
        loan_amnt = float(row.get('loan_amnt', 0) or 0)
        annual_inc = float(row.get('annual_inc', 0) or 0)
        if loan_amnt <= 0 or annual_inc <= 0:
            return None
        if annual_inc > 1000000:
            annual_inc = 1000000  # cap extreme outlier (data entry error)
        if loan_amnt > 100000:
            loan_amnt = 100000  # cap extreme outlier

        emp_length = parse_emp_length(row.get('emp_length', ''))
        home_ownership = parse_home_ownership(row.get('home_ownership', ''))
        loan_purpose = parse_purpose(row.get('purpose', ''))
        dti = float(row.get('dti', 0) or 0) / 100.0  # LC dti is percentage
        if dti > 1.0:
            dti = dti / 100.0  # safety: some versions store as 0-100
        if dti > 1.0:
            dti = 0.5  # cap absurd values

        revol_util = parse_percent(row.get('revol_util', ''))
        if revol_util > 1.0:
            revol_util /= 100.0

        delinq = int(float(row.get('delinq_2yrs', 0) or 0))
        open_acc = int(float(row.get('open_acc', 0) or 0))
        if open_acc <= 0:
            open_acc = 1

        # Credit score: use fico_range_low
        try:
            credit_score = int(float(row.get('fico_range_low', 0) or 0))
        except (ValueError, TypeError):
            credit_score = 700
        if credit_score < 300 or credit_score > 850:
            credit_score = max(300, min(850, credit_score))

        # Term
        term_months = parse_term(row.get('term', ''))

        # Issue date for age estimation
        issue_d = row.get('issue_d', '')
        earliest_cr_line = row.get('earliest_cr_line', '')
        age = estimate_age(emp_length, earliest_cr_line, issue_d)

        # Default flag
        loan_status = row.get('loan_status', '')
        default_flag = parse_loan_status(loan_status)
        if default_flag is None:
            return None

        return {
            'age': age,
            'annual_income': annual_inc,
            'employment_length': emp_length,
            'credit_score': credit_score,
            'dti_ratio': dti,
            'utilization': revol_util,
            'num_derogatory': min(20, delinq),
            'num_credit_lines': min(80, open_acc),
            'home_ownership': home_ownership,
            'loan_amount': loan_amnt,
            'loan_purpose': loan_purpose,
            'term_months': term_months,
            'default_flag': default_flag,
        }
    except Exception as e:
        return None


def load_lc_data(max_rows=200000):
    """Load LendingClub data, map to our format. Returns list of mapped dicts."""
    gz_path = os.path.join(LC_DIR, 'accepted_2007_to_2018Q4.csv.gz')

    print(f"Loading LendingClub data from {gz_path}")
    print(f"  Max rows to process: {max_rows}")

    mapped = []
    skipped = 0
    total = 0
    status_counts = Counter()

    with gzip.open(gz_path, 'rt', errors='replace') as f:
        reader = csv.DictReader(f)
        for row in reader:
            total += 1
            result = map_row(row)
            if result is None:
                skipped += 1
                if skipped <= 5:
                    status = row.get('loan_status', 'UNKNOWN')
                    status_counts[status] += 1
                continue

            mapped.append(result)
            if len(mapped) >= max_rows:
                break

    print(f"\n  Total rows scanned: {total}")
    print(f"  Rows mapped:        {len(mapped)}")
    print(f"  Rows skipped:       {skipped}")
    print(f"  Default rate:       {sum(1 for r in mapped if r['default_flag']==1)}/{len(mapped)} = "
          f"{100*sum(1 for r in mapped if r['default_flag']==1)/max(1,len(mapped)):.1f}%")
    if status_counts:
        print(f"  Skip reasons (sample): {dict(status_counts.most_common(3))}")

    return mapped


def write_csv(data, filepath):
    """Write dataset to CSV in train.py's expected format."""
    fieldnames = [
        'age', 'annual_income', 'employment_length', 'credit_score',
        'dti_ratio', 'utilization', 'num_derogatory', 'num_credit_lines',
        'home_ownership', 'loan_amount', 'loan_purpose', 'default_flag'
    ]
    with open(filepath, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in data:
            # Only write fields in fieldnames
            writer.writerow({k: row[k] for k in fieldnames if k in row})

    actual_defaults = sum(1 for d in data if d['default_flag'] == 1)
    print(f"  Written {len(data)} records to {filepath}")
    print(f"  Default rate: {actual_defaults}/{len(data)} = {100*actual_defaults/len(data):.1f}%")


def main():
    print("=" * 60)
    print("  LENDINGCLUB → PALMFI DATA PIPELINE")
    print("  Real-world loan data for credit underwriting model")
    print("=" * 60)

    # 1. Load and map LC data
    print("\n[1] Loading and mapping LendingClub data...")
    all_data = load_lc_data(max_rows=200000)

    # 2. Show data distributions
    print("\n[2] Feature distributions (from real LC data):")
    print("-" * 50)
    for feat in ['age', 'annual_income', 'credit_score', 'dti_ratio',
                 'utilization', 'num_derogatory', 'num_credit_lines',
                 'loan_amount', 'employment_length']:
        vals = [d[feat] for d in all_data]
        print(f"  {feat:20s}: mean={np.mean(vals):>10.1f}  "
              f"min={min(vals):>10.1f}  max={max(vals):>10.1f}")

    home_counts = Counter(d['home_ownership'] for d in all_data)
    purpose_counts = Counter(d['loan_purpose'] for d in all_data)
    print(f"  {'home_ownership':20s}: {dict(home_counts.most_common(5))}")
    print(f"  {'loan_purpose':20s}: {dict(purpose_counts.most_common(5))}")

    # 3. Split 70/15/15
    print("\n[3] Splitting data...")
    random.seed(42)
    random.shuffle(all_data)
    n = len(all_data)
    train = all_data[:int(n * 0.70)]
    val = all_data[int(n * 0.70):int(n * 0.85)]
    test = all_data[int(n * 0.85):]

    print(f"  Train: {len(train)}, Val: {len(val)}, Test: {len(test)}")

    # 4. Write CSVs (overwrites the synthetic ones)
    print("\n[4] Writing CSV files...")
    train_path = os.path.join(BASE_DIR, 'train_lc.csv')
    val_path = os.path.join(BASE_DIR, 'val_lc.csv')
    test_path = os.path.join(BASE_DIR, 'test_lc.csv')
    write_csv(train, train_path)
    write_csv(val, val_path)
    write_csv(test, test_path)

    # 5. Train model on LC data
    print("\n[5] Training model on LendingClub data...")
    from train import load_csv, extract_features_labels

    train_data = load_csv(train_path)
    val_data = load_csv(val_path)
    test_data = load_csv(test_path)

    print(f"  Train: {len(train_data)} samples")
    print(f"  Val:   {len(val_data)} samples")
    print(f"  Test:  {len(test_data)} samples")

    engineer = CreditFeatureEngineer()
    train_features_data, y_train = extract_features_labels(train_data)
    val_features_data, y_val = extract_features_labels(val_data)
    test_features_data, y_test = extract_features_labels(test_data)

    X_train = engineer.fit_transform(train_features_data)
    X_val = engineer.transform(val_features_data)
    X_test = engineer.transform(test_features_data)

    feature_names = engineer.get_feature_names()
    print(f"  Features: {len(feature_names)}")
    print(f"  X_train shape: {X_train.shape}")

    print("\n[6] Training ensemble model on real LC data...")
    ensemble = CreditEnsemble()
    ensemble.fit(X_train, y_train)

    # 7. Evaluate
    print("\n[7] Evaluation on REAL DATA:")
    print("-" * 50)

    for name, X, y in [('Train', X_train, y_train),
                        ('Val', X_val, y_val),
                        ('Test', X_test, y_test)]:
        y_pred = ensemble.predict_proba(X)
        auc = compute_auc_fast(y, y_pred)
        print(f"\n  {name} Set:")
        print(f"    AUC: {auc:.4f}")
        for thresh in [0.3, 0.5, 0.7]:
            m = compute_metrics(y, y_pred, threshold=thresh)
            print(f"    Threshold={thresh}: Prec={m['precision']:.3f}, "
                  f"Recall={m['recall']:.3f}, F1={m['f1']:.3f}, "
                  f"Acc={m['accuracy']:.3f}")

    # 8. Feature importance
    print("\n[8] Feature Importance (from Logistic Regression coefficients):")
    print("-" * 50)
    weights = ensemble.logistic.get_weights()
    coefs = weights['weights']
    feat_imp = list(zip(feature_names, coefs))
    feat_imp.sort(key=lambda x: -abs(x[1]))
    for name, coef in feat_imp[:15]:
        direction = "POSITIVE" if coef > 0 else "NEGATIVE"
        print(f"  {name:35s} {coef:+.6f}  ({direction})")

    # 9. Save model
    print("\n[9] Saving model (as model_weights_lc.json)...")
    model_dict = {
        'ensemble': ensemble.to_dict(),
        'engineer': engineer.to_dict(),
        'metrics': {
            'train_auc': compute_auc_fast(y_train, ensemble.predict_proba(X_train)),
            'val_auc': compute_auc_fast(y_val, ensemble.predict_proba(X_val)),
            'test_auc': compute_auc_fast(y_test, ensemble.predict_proba(X_test)),
        },
        'feature_names': feature_names,
        'source': 'lending_club_2007_2018',
        'num_samples': len(all_data),
        'default_rate': sum(1 for r in all_data if r['default_flag']==1) / max(1, len(all_data)),
    }
    model_path = os.path.join(BASE_DIR, 'model_weights_lc.json')
    with open(model_path, 'w') as f:
        json.dump(model_dict, f, indent=2)
    print(f"  Saved to {model_path}")

    # Also save as default model_weights.json so scorer uses it
    import shutil
    shutil.copy(model_path, os.path.join(BASE_DIR, 'model_weights.json'))
    print(f"  Also copied to model_weights.json (active model)")

    print("\n" + "=" * 60)
    print("  LENDINGCLUB MODEL TRAINING COMPLETE!")
    print(f"  Test AUC: {model_dict['metrics']['test_auc']:.4f}")
    print("=" * 60)


if __name__ == '__main__':
    main()
