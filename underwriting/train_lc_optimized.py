#!/usr/bin/env python3
"""Train on LendingClub data — optimized for speed (50K samples, 10 trees)."""
import csv
import json
import os
import sys
import random
import numpy as np

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from feature_engineer import CreditFeatureEngineer
from ensemble_model import CreditEnsemble


def compute_auc_fast(y_true, y_pred):
    n = len(y_true)
    pairs = list(zip(y_pred, y_true))
    pairs.sort(key=lambda x: x[0])
    n_pos = int(sum(y_true))
    n_neg = n - n_pos
    if n_pos == 0 or n_neg == 0:
        return 0.5
    rank_sum = 0
    for i, (_, label) in enumerate(pairs):
        if label == 1:
            rank_sum += (i + 1)
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


def load_csv(filepath):
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


def extract_features_labels(data):
    features_data = []
    labels = []
    for row in data:
        features_data.append({
            'age': row['age'], 'annual_income': row['annual_income'],
            'employment_length': row['employment_length'], 'credit_score': row['credit_score'],
            'dti_ratio': row['dti_ratio'], 'utilization': row['utilization'],
            'num_derogatory': row['num_derogatory'], 'num_credit_lines': row['num_credit_lines'],
            'home_ownership': row['home_ownership'], 'loan_amount': row['loan_amount'],
            'loan_purpose': row['loan_purpose'],
        })
        labels.append(row['default_flag'])
    return features_data, np.array(labels, dtype=np.float64)


def main():
    print("=" * 60)
    print("  LENDINGCLUB → PALMFI — OPTIMIZED TRAINING")
    print("=" * 60)

    # Step 1: Load from existing CSVs (already written by lc_pipeline.py)
    train_path = os.path.join(BASE_DIR, 'train_lc.csv')
    val_path = os.path.join(BASE_DIR, 'val_lc.csv')
    test_path = os.path.join(BASE_DIR, 'test_lc.csv')

    print("\n[1] Loading LendingClub CSV files...")
    train = load_csv(train_path)
    val = load_csv(val_path)
    test = load_csv(test_path)

    # Subsample train to 50K for speed
    random.seed(42)
    random.shuffle(train)
    train = train[:50000]

    print(f"  Train: {len(train)} | Val: {len(val)} | Test: {len(test)}")
    train_defaults = sum(1 for d in train if d['default_flag'] == 1)
    val_defaults = sum(1 for d in val if d['default_flag'] == 1)
    test_defaults = sum(1 for d in test if d['default_flag'] == 1)
    print(f"  Default rates: Train={100*train_defaults/len(train):.1f}% "
          f"Val={100*val_defaults/len(val):.1f}% Test={100*test_defaults/len(test):.1f}%")

    # Step 2: Feature engineering
    print("\n[2] Feature engineering...")
    engineer = CreditFeatureEngineer()
    train_features, y_train = extract_features_labels(train)
    val_features, y_val = extract_features_labels(val)
    test_features, y_test = extract_features_labels(test)

    X_train = engineer.fit_transform(train_features)
    X_val = engineer.transform(val_features)
    X_test = engineer.transform(test_features)
    feature_names = engineer.get_feature_names()
    print(f"  {len(feature_names)} features → X_train shape: {X_train.shape}")

    # Step 3: Train lightweight ensemble (fewer trees for speed)
    print("\n[3] Training ensemble (10 trees)...")
    ensemble = CreditEnsemble()
    ensemble.forest.n_trees = 10  # Speed optimization
    ensemble.fit(X_train, y_train)

    # Step 4: Evaluate
    print("\n[4] Evaluation on REAL LendingClub data:")
    print("-" * 55)
    for name, X, y in [('Train', X_train, y_train),
                        ('Val', X_val, y_val),
                        ('Test', X_test, y_test)]:
        y_pred = ensemble.predict_proba(X)
        auc = compute_auc_fast(y, y_pred)
        print(f"\n  {name} Set — AUC: {auc:.4f}")
        for thresh in [0.3, 0.5, 0.7]:
            m = compute_metrics(y, y_pred, threshold=thresh)
            print(f"    T={thresh:.1f}  P={m['precision']:.3f}  R={m['recall']:.3f}  "
                  f"F1={m['f1']:.3f}  Acc={m['accuracy']:.3f}")

    # Step 5: Feature importance
    print("\n[5] Feature Importance (Logistic Regression coefficients):")
    print("-" * 55)
    weights = ensemble.logistic.get_weights()
    feat_imp = list(zip(feature_names, weights['weights']))
    feat_imp.sort(key=lambda x: -abs(x[1]))
    for name, coef in feat_imp[:20]:
        direction = "RISK↑" if coef > 0 else "RISK↓"
        print(f"  {name:35s} {coef:+.6f}  ({direction})")

    # Step 6: Save as ACTIVE model — overwrites model_weights.json
    print("\n[6] Saving model as model_weights.json...")
    final_auc = {
        'train_auc': compute_auc_fast(y_train, ensemble.predict_proba(X_train)),
        'val_auc': compute_auc_fast(y_val, ensemble.predict_proba(X_val)),
        'test_auc': compute_auc_fast(y_test, ensemble.predict_proba(X_test)),
    }
    model_dict = {
        'ensemble': ensemble.to_dict(),
        'engineer': engineer.to_dict(),
        'metrics': final_auc,
        'feature_names': feature_names,
        'source': 'lending_club_2007_2018',
        'num_samples_train': len(train),
        'num_samples_total': len(train) + len(val) + len(test),
        'default_rate_train': train_defaults / max(1, len(train)),
    }
    model_path = os.path.join(BASE_DIR, 'model_weights.json')
    with open(model_path, 'w') as f:
        json.dump(model_dict, f, indent=2)
    print(f"  Saved to {model_path}")
    print(f"  Metrics: Train AUC={final_auc['train_auc']:.4f}, "
          f"Val AUC={final_auc['val_auc']:.4f}, "
          f"Test AUC={final_auc['test_auc']:.4f}")

    # Report the model's actual performance
    y_test_pred = ensemble.predict_proba(X_test)
    test_m = compute_metrics(y_test, y_test_pred, threshold=0.5)
    print(f"\n  Production-ready threshold (0.5): P={test_m['precision']:.3f} "
          f"R={test_m['recall']:.3f} F1={test_m['f1']:.3f}")

    print("\n" + "=" * 60)
    print("  MAIN MODEL TRAINING COMPLETE — LENDINGCLUB REAL DATA")
    print("=" * 60)


if __name__ == '__main__':
    main()
