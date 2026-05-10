#!/usr/bin/env python3
"""
Train Main Underwriting Model on LendingClub Data
==================================================
Uses cleaned raw features (no engineered derived features that add noise).
Trains logistic regression + decision tree ensemble.
"""
import csv
import json
import math
import os
import random
import sys
import time

import numpy as np

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
from logistic_regression import LogisticRegression
from decision_tree import DecisionTree


def compute_auc_fast(y_true, y_pred):
    n = len(y_true)
    pairs = list(zip(y_pred, y_true))
    pairs.sort(key=lambda x: x[0])
    n_pos = int(sum(y_true))
    n_neg = n - n_pos
    if n_pos == 0 or n_neg == 0:
        return 0.5
    rank_sum = sum(i + 1 for i, (_, label) in enumerate(pairs) if label == 1)
    u = rank_sum - (n_pos * (n_pos + 1)) / 2
    return u / (n_pos * n_neg)


def compute_metrics(y_true, y_pred, threshold=0.5):
    y_binary = (y_pred >= threshold).astype(np.int64)
    tp = np.sum((y_binary == 1) & (y_true == 1))
    fp = np.sum((y_binary == 1) & (y_true == 0))
    tn = np.sum((y_binary == 0) & (y_true == 0))
    fn = np.sum((y_binary == 0) & (y_true == 1))
    precision = tp / max(1, tp + fp)
    recall = tp / max(1, tp + fn)
    f1 = 2 * precision * recall / max(1e-10, precision + recall)
    accuracy = (tp + tn) / max(1, len(y_true))
    return {'precision': round(precision, 4), 'recall': round(recall, 4),
            'f1': round(f1, 4), 'accuracy': round(accuracy, 4)}


class RealDataFeatureEngineer:
    """Lightweight feature engineer for real LendingClub data."""

    def __init__(self):
        self.norm_params = {}
        self.fitted = False

    def _raw_features(self, row):
        """Extract and transform raw features into a vector."""
        income = max(20000, row['annual_income'])
        return [
            row['age'] / 100.0,                         # age_scaled
            math.log10(income),                         # log_income
            row['employment_length'] / 20.0,             # emp_length_scaled
            (row['credit_score'] - 300) / 550.0,         # cs_scaled [0,1]
            row['dti_ratio'],                            # dti raw
            row['utilization'],                          # util raw
            row['num_derogatory'] / 20.0,                # derog_scaled
            row['num_credit_lines'] / 50.0,               # num_lines_scaled
            math.log(max(500, row['loan_amount'])),      # log_loan_amnt
            1.0 if row['home_ownership'] == 'rent' else 0.0,
            1.0 if row['home_ownership'] == 'mortgage' else 0.0,
            1.0 if row['home_ownership'] == 'own' else 0.0,
        ]

    FEATURE_NAMES = [
        'age_scaled', 'log_income', 'emp_length_scaled', 'cs_scaled',
        'dti', 'utilization', 'derog_scaled', 'num_lines_scaled',
        'log_loan_amnt', 'home_rent', 'home_mortgage', 'home_own',
    ]

    def fit(self, data):
        # Compute means and stds for standardization
        X = np.array([self._raw_features(r) for r in data])
        self.norm_params = {
            'mean': np.mean(X, axis=0).tolist(),
            'std': np.std(X, axis=0).tolist(),
        }
        # Avoid division by zero
        self.norm_params['std'] = [max(0.001, s) for s in self.norm_params['std']]
        self.fitted = True
        return self

    def transform(self, data):
        if not self.fitted:
            raise ValueError("Not fitted")
        X = np.array([self._raw_features(r) for r in data], dtype=np.float64)
        mean = np.array(self.norm_params['mean'])
        std = np.array(self.norm_params['std'])
        return (X - mean) / std

    def fit_transform(self, data):
        self.fit(data)
        return self.transform(data)

    def to_dict(self):
        return {'norm_params': self.norm_params}

    @classmethod
    def from_dict(cls, d):
        eng = cls()
        eng.norm_params = d['norm_params']
        eng.fitted = True
        return eng

    def get_feature_names(self):
        return list(self.FEATURE_NAMES)


def load_csv(filepath):
    data = []
    with open(filepath, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            data.append({
                'age': int(row['age']),
                'annual_income': float(row['annual_income']),
                'employment_length': float(row['employment_length']),
                'credit_score': int(row['credit_score']),
                'dti_ratio': float(row['dti_ratio']),
                'utilization': float(row['utilization']),
                'num_derogatory': int(row['num_derogatory']),
                'num_credit_lines': int(row['num_credit_lines']),
                'loan_amount': float(row['loan_amount']),
                'home_ownership': row['home_ownership'],
                'loan_purpose': row['loan_purpose'],
                'default_flag': int(row['default_flag']),
            })
    return data


def main():
    t_start = time.time()
    print("=" * 60)
    print("  MAIN MODEL — LENDINGCLUB REAL DATA TRAINING")
    print("=" * 60)

    # 1. Load
    print("\n[1] Loading LC data...")
    train = load_csv(os.path.join(BASE_DIR, 'train_lc.csv'))
    val = load_csv(os.path.join(BASE_DIR, 'val_lc.csv'))
    test = load_csv(os.path.join(BASE_DIR, 'test_lc.csv'))
    random.seed(42)
    random.shuffle(train)
    train = train[:50000]

    print(f"  Train: {len(train)} | Val: {len(val)} | Test: {len(test)}")
    for name, d in [('Train', train), ('Val', val), ('Test', test)]:
        dr = sum(1 for r in d if r['default_flag'] == 1) / max(1, len(d))
        print(f"  {name} default rate: {100*dr:.1f}%")

    # 2. Feature engineering
    print("\n[2] Feature engineering...")
    engineer = RealDataFeatureEngineer()
    y_train = np.array([r['default_flag'] for r in train], dtype=np.float64)
    y_val = np.array([r['default_flag'] for r in val], dtype=np.float64)
    y_test = np.array([r['default_flag'] for r in test], dtype=np.float64)

    X_train = engineer.fit_transform(train)
    X_val = engineer.transform(val)
    X_test = engineer.transform(test)
    feat_names = engineer.get_feature_names()
    print(f"  {len(feat_names)} features → X_train: {X_train.shape}")
    print(f"  Feature names: {feat_names}")

    # 3. Train logistic regression
    print("\n[3] Training Logistic Regression...")
    t0 = time.time()
    log = LogisticRegression(lr=0.1, iterations=5000, l2=0.001)
    log.fit(X_train, y_train)
    print(f"  Done in {time.time()-t0:.1f}s")
    print(f"  Loss: {log.loss_history[0]:.4f} → {log.loss_history[-1]:.4f}")

    # 4. Train decision tree
    print("\n[4] Training Decision Tree...")
    t0 = time.time()
    tree = DecisionTree(max_depth=5, min_samples_split=50)
    tree.fit(X_train, y_train)
    print(f"  Done in {time.time()-t0:.1f}s")

    # 5. Evaluate both
    print("\n[5] Evaluation:")
    print("-" * 55)
    for name, X, y, label in [('LogReg Train', X_train, y_train, 'log'),
                                ('LogReg Val', X_val, y_val, 'log'),
                                ('LogReg Test', X_test, y_test, 'log'),
                                ('Tree Val', X_val, y_val, 'tree'),
                                ('Tree Test', X_test, y_test, 'tree')]:
        if 'LogReg' in name:
            pred = log.predict_proba(X)
        else:
            pred = tree.predict_proba(X)
        a = compute_auc_fast(y, pred)
        m = compute_metrics(y, pred, threshold=0.43)
        print(f"  {name:20s} AUC={a:.4f}  P={m['precision']:.3f} R={m['recall']:.3f} F1={m['f1']:.3f}")

    # 6. Feature importance
    print("\n[6] Feature Importance (LogReg coefficients):")
    print("-" * 55)
    weights = log.get_weights()
    imp = list(zip(feat_names, weights['weights']))
    imp.sort(key=lambda x: -abs(x[1]))
    for name, coef in imp:
        direction = "RISK↑" if coef > 0 else "RISK↓"
        print(f"  {name:20s} {coef:+.4f}  ({direction})")

    # Weight blend: 70% logreg + 30% tree
    print("\n[7] Blending ensemble (70% LogReg + 30% Tree)...")
    ensemble_weight = {'logistic': 0.70, 'tree': 0.30}

    def ensemble_proba(X):
        return (ensemble_weight['logistic'] * log.predict_proba(X)
                + ensemble_weight['tree'] * tree.predict_proba(X))

    for name, X, y in [('Train', X_train, y_train),
                        ('Val', X_val, y_val),
                        ('Test', X_test, y_test)]:
        pred = ensemble_proba(X)
        a = compute_auc_fast(y, pred)
        m = compute_metrics(y, pred, threshold=0.43)
        print(f"  Ensemble {name:10s} AUC={a:.4f}  P={m['precision']:.3f} "
              f"R={m['recall']:.3f} F1={m['f1']:.3f} (T=0.43)")

    # 8. Save model
    print("\n[8] Saving model...")
    model_dict = {
        'logistic': log.to_dict(),
        'tree': tree.to_dict(),
        'engineer': engineer.to_dict(),
        'ensemble_weights': ensemble_weight,
        'feature_names': feat_names,
        'metrics': {
            'val_auc': compute_auc_fast(y_val, ensemble_proba(X_val)),
            'test_auc': compute_auc_fast(y_test, ensemble_proba(X_test)),
        },
        'source': 'lending_club_2007_2018',
        'default_rate': sum(1 for r in train if r['default_flag']==1) / len(train),
        'threshold': 0.43,
    }
    model_path = os.path.join(BASE_DIR, 'model_weights.json')
    with open(model_path, 'w') as f:
        json.dump(model_dict, f, indent=2)
    print(f"  Saved to {model_path}")
    print(f"  Test AUC: {model_dict['metrics']['test_auc']:.4f}")

    print(f"\n  Total time: {time.time()-t_start:.1f}s")
    print("=" * 60)


if __name__ == '__main__':
    main()
