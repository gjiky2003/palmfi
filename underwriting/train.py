#!/usr/bin/env python3
"""Training script for the credit underwriting engine."""

import csv
import json
import os
import sys
import math
import numpy as np

from feature_engineer import CreditFeatureEngineer
from logistic_regression import LogisticRegression
from decision_tree import DecisionTree
from random_forest import RandomForest
from ensemble_model import CreditEnsemble

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def load_csv(filepath):
    """Load CSV data into list of dicts."""
    data = []
    with open(filepath, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Convert numeric fields
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
    """Extract feature rows and labels from data dicts."""
    # The data dicts already have loan_purpose and home_ownership as strings
    features_data = []
    labels = []
    for row in data:
        features_data.append({
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
        })
        labels.append(row['default_flag'])
    return features_data, np.array(labels, dtype=np.float64)


def compute_auc(y_true, y_pred):
    """Compute AUC using the trapezoidal rule."""
    n = len(y_true)
    # Sort by predicted probability descending
    pairs = list(zip(y_pred, y_true))
    pairs.sort(key=lambda x: -x[0])
    
    n_pos = sum(y_true)
    n_neg = n - n_pos
    
    if n_pos == 0 or n_neg == 0:
        return 0.5
    
    # Count pairs where positive score > negative score
    pos_count = 0
    neg_count = 0
    correct_pairs = 0
    tie_pairs = 0
    
    for pred, label in pairs:
        if label == 1:
            correct_pairs += neg_count
            pos_count += 1
        else:
            neg_count += 1
    
    for i in range(n):
        for j in range(i + 1, n):
            if pairs[i][1] == 1 and pairs[j][1] == 0:
                if pairs[i][0] > pairs[j][0]:
                    correct_pairs += 1
                elif pairs[i][0] == pairs[j][0]:
                    tie_pairs += 1
    
    total_pairs = n_pos * n_neg
    if total_pairs == 0:
        return 0.5
    
    auc = (correct_pairs + 0.5 * tie_pairs) / total_pairs
    return auc


def compute_auc_fast(y_true, y_pred):
    """Fast AUC computation using the Mann-Whitney U statistic."""
    n = len(y_true)
    pairs = list(zip(y_pred, y_true))
    # Sort by predicted probability ASCENDING
    pairs.sort(key=lambda x: x[0])

    n_pos = int(sum(y_true))
    n_neg = n - n_pos

    if n_pos == 0 or n_neg == 0:
        return 0.5

    # Sum of ranks of positive examples
    rank_sum = 0
    for i, (_, label) in enumerate(pairs):
        if label == 1:
            rank_sum += (i + 1)

    # Mann-Whitney U statistic
    u = rank_sum - (n_pos * (n_pos + 1)) / 2
    auc = u / (n_pos * n_neg)
    return auc


def compute_metrics(y_true, y_pred, threshold=0.5):
    """Compute precision, recall, F1 at a given threshold."""
    y_binary = (y_pred >= threshold).astype(np.int64)
    
    tp = np.sum((y_binary == 1) & (y_true == 1))
    fp = np.sum((y_binary == 1) & (y_true == 0))
    tn = np.sum((y_binary == 0) & (y_true == 0))
    fn = np.sum((y_binary == 0) & (y_true == 1))
    
    precision = tp / max(1, tp + fp)
    recall = tp / max(1, tp + fn)
    f1 = 2 * precision * recall / max(1e-10, precision + recall)
    accuracy = (tp + tn) / max(1, len(y_true))
    
    return {
        'precision': round(precision, 4),
        'recall': round(recall, 4),
        'f1': round(f1, 4),
        'accuracy': round(accuracy, 4),
        'tp': int(tp),
        'fp': int(fp),
        'tn': int(tn),
        'fn': int(fn),
    }


def main():
    print("=" * 60)
    print("  CREDIT UNDERWRITING ENGINE - TRAINING")
    print("=" * 60)
    
    # 1. Load data
    print("\n[1] Loading data...")
    train_data = load_csv(os.path.join(BASE_DIR, 'train.csv'))
    val_data = load_csv(os.path.join(BASE_DIR, 'val.csv'))
    test_data = load_csv(os.path.join(BASE_DIR, 'test.csv'))
    
    print(f"  Train: {len(train_data)} samples")
    print(f"  Val:   {len(val_data)} samples")
    print(f"  Test:  {len(test_data)} samples")
    
    train_defaults = sum(1 for d in train_data if d['default_flag'] == 1)
    val_defaults = sum(1 for d in val_data if d['default_flag'] == 1)
    test_defaults = sum(1 for d in test_data if d['default_flag'] == 1)
    print(f"  Default rates: Train={100*train_defaults/len(train_data):.1f}%, "
          f"Val={100*val_defaults/len(val_data):.1f}%, "
          f"Test={100*test_defaults/len(test_data):.1f}%")
    
    # 2. Feature engineering
    print("\n[2] Feature engineering...")
    engineer = CreditFeatureEngineer()
    
    train_features_data, y_train = extract_features_labels(train_data)
    val_features_data, y_val = extract_features_labels(val_data)
    test_features_data, y_test = extract_features_labels(test_data)
    
    X_train = engineer.fit_transform(train_features_data)
    X_val = engineer.transform(val_features_data)
    X_test = engineer.transform(test_features_data)
    
    feature_names = engineer.get_feature_names()
    print(f"  Features: {len(feature_names)}")
    print(f"  Feature names: {feature_names}")
    print(f"  X_train shape: {X_train.shape}")
    
    # 3. Train ensemble
    print("\n[3] Training ensemble model...")
    ensemble = CreditEnsemble()
    ensemble.fit(X_train, y_train)
    
    # 4. Evaluate
    print("\n[4] Evaluation:")
    print("-" * 50)
    
    for name, X, y in [('Train', X_train, y_train), ('Val', X_val, y_val), ('Test', X_test, y_test)]:
        y_pred = ensemble.predict_proba(X)
        auc = compute_auc_fast(y, y_pred)
        
        print(f"\n  {name} Set:")
        print(f"    AUC: {auc:.4f}")
        
        for thresh in [0.3, 0.5, 0.7]:
            m = compute_metrics(y, y_pred, threshold=thresh)
            print(f"    Threshold={thresh}: Prec={m['precision']:.3f}, Recall={m['recall']:.3f}, "
                  f"F1={m['f1']:.3f}, Acc={m['accuracy']:.3f}")
    
    # 5. Feature importance
    print("\n[5] Feature Importance (from Logistic Regression coefficients):")
    print("-" * 50)
    weights = ensemble.logistic.get_weights()
    coefs = weights['weights']
    
    # Sort by absolute value
    feat_imp = list(zip(feature_names, coefs))
    feat_imp.sort(key=lambda x: -abs(x[1]))
    
    for name, coef in feat_imp[:15]:
        direction = "POSITIVE" if coef > 0 else "NEGATIVE"
        print(f"  {name:35s} {coef:+.6f}  ({direction})")
    
    # 6. Save model
    print("\n[6] Saving model...")
    model_dir = BASE_DIR
    model_path = os.path.join(model_dir, 'model_weights.json')
    
    model_dict = {
        'ensemble': ensemble.to_dict(),
        'engineer': engineer.to_dict(),
        'metrics': {
            'train_auc': compute_auc_fast(y_train, ensemble.predict_proba(X_train)),
            'val_auc': compute_auc_fast(y_val, ensemble.predict_proba(X_val)),
            'test_auc': compute_auc_fast(y_test, ensemble.predict_proba(X_test)),
        },
        'feature_names': feature_names,
    }
    
    with open(model_path, 'w') as f:
        json.dump(model_dict, f, indent=2)
    
    print(f"  Saved to {model_path}")
    
    # Also save individual model predictions for analysis
    print("\n[7] Model comparison on test set:")
    y_pred_log = ensemble.logistic.predict_proba(X_test)
    y_pred_tree = ensemble.tree.predict_proba(X_test)
    y_pred_forest = ensemble.forest.predict_proba(X_test)
    y_pred_ensemble = ensemble.predict_proba(X_test)
    
    auc_log = compute_auc_fast(y_test, y_pred_log)
    auc_tree = compute_auc_fast(y_test, y_pred_tree)
    auc_forest = compute_auc_fast(y_test, y_pred_forest)
    auc_ens = compute_auc_fast(y_test, y_pred_ensemble)
    
    print(f"  Logistic Regression AUC: {auc_log:.4f}")
    print(f"  Decision Tree AUC:       {auc_tree:.4f}")
    print(f"  Random Forest AUC:       {auc_forest:.4f}")
    print(f"  Ensemble AUC:            {auc_ens:.4f}")
    
    print("\n" + "=" * 60)
    print("  TRAINING COMPLETE")
    print("=" * 60)


if __name__ == '__main__':
    main()
