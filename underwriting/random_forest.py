#!/usr/bin/env python3
"""Pure Python random forest classifier."""

import numpy as np
from decision_tree import DecisionTree


class RandomForest:
    """Random forest classifier with bootstrapping and feature subsampling."""

    def __init__(self, n_trees=100, max_depth=5, sample_ratio=0.8, feature_ratio=0.3, min_samples_split=20):
        self.n_trees = n_trees
        self.max_depth = max_depth
        self.sample_ratio = sample_ratio
        self.feature_ratio = feature_ratio
        self.min_samples_split = min_samples_split
        self.trees = []
        self.feature_importances_ = None

    def fit(self, X, y):
        """Train the random forest.
        
        Args:
            X: np.ndarray of shape (n_samples, n_features)
            y: np.ndarray of shape (n_samples,) with 0/1 values
        """
        n_samples, n_features = X.shape
        self.trees = []
        
        n_sub_features = max(1, int(n_features * self.feature_ratio))
        n_sample_size = max(2, int(n_samples * self.sample_ratio))
        
        for i in range(self.n_trees):
            # Bootstrap sample
            indices = np.random.choice(n_samples, n_sample_size, replace=True)
            X_boot = X[indices]
            y_boot = y[indices]
            
            # Train tree with random feature subsampling
            tree = DecisionTree(
                max_depth=self.max_depth,
                min_samples_split=self.min_samples_split,
                n_features=n_sub_features,
            )
            tree.fit(X_boot, y_boot)
            self.trees.append(tree)
        
        # Aggregate feature importances
        self.feature_importances_ = np.zeros(n_features, dtype=np.float64)
        for tree in self.trees:
            if tree.feature_importances_ is not None:
                n_f = min(len(tree.feature_importances_), n_features)
                self.feature_importances_[:n_f] += tree.feature_importances_[:n_f]
        
        total = np.sum(self.feature_importances_)
        if total > 0:
            self.feature_importances_ /= total
        
        return self

    def predict_proba(self, X):
        """Predict probability of default by averaging tree predictions.
        
        Args:
            X: np.ndarray of shape (n_samples, n_features)
            
        Returns:
            np.ndarray of shape (n_samples,) with probabilities
        """
        if not self.trees:
            raise ValueError("Model not fitted yet.")
        
        n_samples = X.shape[0]
        predictions = np.zeros((n_samples, len(self.trees)), dtype=np.float64)
        
        for i, tree in enumerate(self.trees):
            predictions[:, i] = tree.predict_proba(X)
        
        return np.mean(predictions, axis=1)

    def predict(self, X, threshold=0.5):
        """Predict binary class labels."""
        proba = self.predict_proba(X)
        return (proba >= threshold).astype(np.int64)

    def to_dict(self):
        """Serialize forest to dict."""
        return {
            'type': 'random_forest',
            'n_trees': self.n_trees,
            'max_depth': self.max_depth,
            'sample_ratio': self.sample_ratio,
            'feature_ratio': self.feature_ratio,
            'min_samples_split': self.min_samples_split,
            'trees': [t.to_dict() for t in self.trees],
            'feature_importances': self.feature_importances_.tolist() if isinstance(
                self.feature_importances_, np.ndarray) else self.feature_importances_,
        }

    @classmethod
    def from_dict(cls, d):
        """Load forest from dict."""
        forest = cls(
            n_trees=d.get('n_trees', 100),
            max_depth=d.get('max_depth', 5),
            sample_ratio=d.get('sample_ratio', 0.8),
            feature_ratio=d.get('feature_ratio', 0.3),
            min_samples_split=d.get('min_samples_split', 20),
        )
        forest.trees = [DecisionTree.from_dict(td) for td in d.get('trees', [])]
        forest.feature_importances_ = np.array(
            d.get('feature_importances', []), dtype=np.float64)
        return forest
