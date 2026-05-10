#!/usr/bin/env python3
"""Train XGBoost model on LendingClub data — primary bureau underwriting model.

Trains, validates, saves model + SHAP explainer. Outputs:
  - model_xgb.json  (XGBoost native format)
  - model_weights_xgb.json  (full metadata + feature names + SHAP baseline)

Usage:
    python3 train_xgb_model.py
"""
import csv
import json
import os
import sys
import random
import time

import numpy as np
import xgboost as xgb

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def compute_auc(y_true, y_pred):
    from sklearn.metrics import roc_auc_score
    return roc_auc_score(y_true, y_pred)


def compute_metrics(y_true, y_pred, threshold=0.5):
    y_bin = (y_pred >= threshold).astype(np.int64)
    tp = np.sum((y_bin == 1) & (y_true == 1))
    fp = np.sum((y_bin == 1) & (y_true == 0))
    tn = np.sum((y_bin == 0) & (y_true == 0))
    fn = np.sum((y_bin == 0) & (y_true == 1))
    precision = tp / max(1, tp + fp)
    recall = tp / max(1, tp + fn)
    f1 = 2 * precision * recall / max(1e-10, precision + recall)
    accuracy = (tp + tn) / max(1, len(y_true))
    return {'precision': round(precision, 4), 'recall': round(recall, 4),
            'f1': round(f1, 4), 'accuracy': round(accuracy, 4)}


# ── Feature schema ──────────────────────────────────────────────────────────
# Must match the order used during training
BASE_FEATURES = [
    'credit_score', 'dti_ratio', 'utilization', 'num_derogatory',
    'num_credit_lines', 'age', 'log_income', 'employment_length',
    'log_loan_amount',
]
CAT_FEATURES = ['home_rent', 'home_mortgage', 'home_own']

ALL_FEATURES = BASE_FEATURES + CAT_FEATURES
NUM_FEATURES = len(ALL_FEATURES)  # 12


def load_csv(filepath):
    """Load LC CSV into list of dicts."""
    data = []
    with open(filepath, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            data.append(row)
    return data


def extract_features_labels(rows, fit_enc=None):
    """Convert raw rows to numpy feature matrix + labels.

    Encodes home_ownership as one-hot.
    If fit_enc is provided, reuses same encoding.
    """
    if fit_enc is not None:
        # Use pre-fitted encoding mapping
        home_map = fit_enc
    else:
        # Build mapping from all data
        unique_homes = sorted(set(r['home_ownership'] for r in rows))
        if 'mortgage' in unique_homes:
            base = ['mortgage', 'own', 'rent']
        elif 'own' in unique_homes:
            base = ['mortgage', 'own', 'rent']
        else:
            base = unique_homes
        # Map to our 3 categories
        home_map = {}
        for h in unique_homes:
            if h in ('mortgage',):
                home_map[h] = 0
            elif h in ('own',):
                home_map[h] = 1
            else:
                home_map[h] = 2

    X_list = []
    y_list = []

    for row in rows:
        try:
            credit_score = float(row['credit_score'])
            dti = float(row['dti_ratio'])
            util = float(row['utilization'])
            derog = float(row['num_derogatory'])
            lines = float(row['num_credit_lines'])
            age = float(row['age'])
            income = float(row['annual_income'])
            emp_len = float(row['employment_length'])
            loan_amt = float(row['loan_amount'])
            home = row['home_ownership']

            # Derived
            log_income = np.log10(max(1000, income))
            log_loan = np.log10(max(100, loan_amt))

            # One-hot home ownership
            home_idx = home_map.get(home, 2)
            home_oh = [0, 0, 0]
            home_oh[home_idx] = 1

            features = [
                credit_score, dti, util, derog, lines,
                age, log_income, emp_len, log_loan,
            ] + home_oh

            X_list.append(features)
            y_list.append(float(row['default_flag']))
        except (ValueError, KeyError) as e:
            continue

    return np.array(X_list, dtype=np.float64), np.array(y_list, dtype=np.float64), home_map


def main():
    print("=" * 60)
    print("  PALMFI XGBOOST MODEL TRAINING")
    print("=" * 60)

    train_path = os.path.join(BASE_DIR, 'train_lc.csv')
    val_path = os.path.join(BASE_DIR, 'val_lc.csv')
    test_path = os.path.join(BASE_DIR, 'test_lc.csv')

    print("\n[1] Loading LendingClub CSV files...")
    train_raw = load_csv(train_path)
    val_raw = load_csv(val_path)
    test_raw = load_csv(test_path)

    random.seed(42)
    random.shuffle(train_raw)
    train_raw = train_raw[:100000]  # Use 100K for speed
    val_raw = val_raw[:20000]
    test_raw = test_raw[:20000]

    print(f"  Train: {len(train_raw)} | Val: {len(val_raw)} | Test: {len(test_raw)}")
    train_def = sum(1 for r in train_raw if r['default_flag'] == '1')
    print(f"  Default rate: {100*train_def/len(train_raw):.1f}%")

    print("\n[2] Extracting features...")
    X_train, y_train, home_map = extract_features_labels(train_raw)
    X_val, y_val, _ = extract_features_labels(val_raw, fit_enc=home_map)
    X_test, y_test, _ = extract_features_labels(test_raw, fit_enc=home_map)
    print(f"  X_train shape: {X_train.shape} | Feature count: {NUM_FEATURES}")

    # Compute class weight (handle imbalance)
    neg = np.sum(y_train == 0)
    pos = np.sum(y_train == 1)
    scale_pos_weight = neg / max(1, pos) if pos > 0 else 1.0
    print(f"  Scale pos weight: {scale_pos_weight:.2f} ({pos} positives, {neg} negatives)")

    print("\n[3] Training XGBoost...")
    t0 = time.time()

    dtrain = xgb.DMatrix(X_train, label=y_train)
    dval = xgb.DMatrix(X_val, label=y_val)

    params = {
        'objective': 'binary:logistic',
        'eval_metric': 'auc',
        'max_depth': 6,
        'eta': 0.05,
        'subsample': 0.8,
        'colsample_bytree': 0.8,
        'scale_pos_weight': scale_pos_weight,
        'min_child_weight': 3,
        'gamma': 0.1,
        'seed': 42,
        'verbosity': 1,
    }

    model = xgb.train(
        params,
        dtrain,
        num_boost_round=500,
        evals=[(dtrain, 'train'), (dval, 'val')],
        early_stopping_rounds=30,
        verbose_eval=50,
    )

    elapsed = time.time() - t0
    best_iter = model.best_iteration if hasattr(model, 'best_iteration') else 500

    print(f"\n  Training completed in {elapsed:.0f}s, best iteration: {best_iter}")

    # Evaluate
    print("\n[4] Evaluation:")
    print("-" * 55)
    for name, X, y in [('Train', X_train, y_train),
                        ('Val', X_val, y_val),
                        ('Test', X_test, y_test)]:
        d = xgb.DMatrix(X)
        y_pred = model.predict(d)
        auc = compute_auc(y, y_pred)
        metrics = compute_metrics(y, y_pred, threshold=0.5)
        print(f"\n  {name} — AUC: {auc:.4f}")
        print(f"    P={metrics['precision']:.3f}  R={metrics['recall']:.3f}  "
              f"F1={metrics['f1']:.3f}  Acc={metrics['accuracy']:.3f}")

    # Feature importance
    print("\n[5] Feature Importance:")
    print("-" * 55)
    importance = model.get_score(importance_type='gain')
    feat_imp = [(ALL_FEATURES[i], importance.get(f'f{i}', 0))
                for i in range(NUM_FEATURES)]
    feat_imp.sort(key=lambda x: -x[1])
    for name, imp in feat_imp[:15]:
        pct = 100 * imp / max(1, sum(v for _, v in feat_imp))
        print(f"  {name:25s}  {pct:.1f}%")

    # Save model
    print("\n[6] Saving model...")
    xgb_path = os.path.join(BASE_DIR, 'model_xgb.json')
    model.save_model(xgb_path)
    print(f"  XGBoost model → {xgb_path}")

    # Also compute SHAP baseline for later use
    try:
        import shap
        explainer = shap.TreeExplainer(model)
        shap_baseline = explainer.expected_value
        if isinstance(shap_baseline, (list, np.ndarray)):
            shap_baseline = float(shap_baseline[1]) if len(shap_baseline) > 1 else float(shap_baseline[0])
        else:
            shap_baseline = float(shap_baseline)
        print(f"  SHAP baseline value: {shap_baseline:.4f}")
    except Exception as e:
        shap_baseline = 0.0
        print(f"  SHAP baseline computation failed: {e}")

    # Save metadata
    y_test_pred = model.predict(xgb.DMatrix(X_test))
    test_auc = compute_auc(y_test, y_test_pred)

    meta = {
        'model_path': 'model_xgb.json',
        'model_type': 'xgboost',
        'num_features': NUM_FEATURES,
        'feature_names': ALL_FEATURES,
        'home_ownership_map': {str(k): v for k, v in home_map.items()},
        'best_iteration': best_iter,
        'metrics': {
            'train_auc': round(compute_auc(y_train, model.predict(xgb.DMatrix(X_train))), 4),
            'val_auc': round(compute_auc(y_val, model.predict(xgb.DMatrix(X_val))), 4),
            'test_auc': round(test_auc, 4),
        },
        'source': 'lending_club_2007_2018',
        'num_samples_train': len(train_raw),
        'shap_baseline': round(shap_baseline, 4),
        'scale_pos_weight': round(scale_pos_weight, 2),
        'thresholds': {
            'auto_approve': 0.30,  # Corresponds to risk_score ≤ 60 / 100
            'reconsideration': 0.40,  # Corresponds to risk_score ≤ 80 / 100
        },
        'default_rate': train_def / max(1, len(train_raw)),
    }

    meta_path = os.path.join(BASE_DIR, 'model_weights_xgb.json')
    with open(meta_path, 'w') as f:
        json.dump(meta, f, indent=2)
    print(f"  Metadata → {meta_path}")

    print("\n" + "=" * 60)
    print("  XGBOOST TRAINING COMPLETE")
    print("=" * 60)
    print(f"\n  Test AUC: {test_auc:.4f}")
    if test_auc > 0.70:
        print("  ✅ Excellent — beats previous pure-Python ensemble (0.666)")
    else:
        print("  ℹ️  Acceptable for prime-borrower LendingClub data")


if __name__ == '__main__':
    main()
