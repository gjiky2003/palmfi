#!/usr/bin/env python3
"""Combined ensemble model for credit underwriting."""

import numpy as np
from logistic_regression import LogisticRegression
from decision_tree import DecisionTree
from random_forest import RandomForest


class CreditEnsemble:
    """Ensemble of logistic regression, decision tree, and random forest."""

    WEIGHTS = {'logistic': 0.30, 'tree': 0.30, 'forest': 0.40}

    def __init__(self):
        self.logistic = LogisticRegression(lr=0.01, iterations=2000, l2=0.01)
        self.tree = DecisionTree(max_depth=5, min_samples_split=20)
        self.forest = RandomForest(
            n_trees=25, max_depth=5, sample_ratio=0.8, feature_ratio=0.3, min_samples_split=20
        )
        self.models_fitted = {
            'logistic': False,
            'tree': False,
            'forest': False,
        }

    def fit(self, X, y):
        """Train all three models."""
        print("Training Logistic Regression...")
        self.logistic.fit(X, y)
        self.models_fitted['logistic'] = True
        
        print("Training Decision Tree...")
        self.tree.fit(X, y)
        self.models_fitted['tree'] = True
        
        print("Training Random Forest (%d trees)..." % self.forest.n_trees)
        self.forest.fit(X, y)
        self.models_fitted['forest'] = True
        
        print("All models trained.")
        return self

    def predict_proba(self, X):
        """Weighted average of all three model predictions."""
        probs = np.zeros((X.shape[0], 3), dtype=np.float64)
        
        if self.models_fitted['logistic']:
            probs[:, 0] = self.logistic.predict_proba(X)
        if self.models_fitted['tree']:
            probs[:, 1] = self.tree.predict_proba(X)
        if self.models_fitted['forest']:
            probs[:, 2] = self.forest.predict_proba(X)
        
        w = self.WEIGHTS
        result = (w['logistic'] * probs[:, 0] +
                  w['tree'] * probs[:, 1] +
                  w['forest'] * probs[:, 2])
        
        return result

    def predict(self, X, threshold=0.5):
        """Binary decision based on ensemble probability."""
        proba = self.predict_proba(X)
        return (proba >= threshold).astype(np.int64)

    def get_risk_score(self, X):
        """Return 0-100 risk score (higher = riskier)."""
        proba = self.predict_proba(X)
        # Scale to 0-100
        scores = np.round(proba * 100).astype(np.int64)
        return np.clip(scores, 0, 100)

    def to_dict(self):
        """Serialize full ensemble to dict."""
        return {
            'type': 'credit_ensemble',
            'weights': self.WEIGHTS,
            'models_fitted': self.models_fitted,
            'logistic': self.logistic.to_dict() if self.models_fitted['logistic'] else None,
            'tree': self.tree.to_dict() if self.models_fitted['tree'] else None,
            'forest': self.forest.to_dict() if self.models_fitted['forest'] else None,
        }

    @classmethod
    def from_dict(cls, d):
        """Load ensemble from dict."""
        ensemble = cls()
        ensemble.WEIGHTS = d.get('weights', cls.WEIGHTS)
        ensemble.models_fitted = d.get('models_fitted', {
            'logistic': False, 'tree': False, 'forest': False
        })
        
        if d.get('logistic'):
            ensemble.logistic = LogisticRegression.from_dict(d['logistic'])
        if d.get('tree'):
            ensemble.tree = DecisionTree.from_dict(d['tree'])
        if d.get('forest'):
            ensemble.forest = RandomForest.from_dict(d['forest'])
        
        return ensemble
