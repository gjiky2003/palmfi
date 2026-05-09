#!/usr/bin/env python3
"""Pure Python decision tree for binary classification using Gini impurity."""

import numpy as np
import math


class DecisionTree:
    """Decision tree classifier with Gini impurity splitting."""

    def __init__(self, max_depth=5, min_samples_split=20, n_features=None):
        self.max_depth = max_depth
        self.min_samples_split = min_samples_split
        self.n_features = n_features  # None = use all, int = random subset
        self.tree = None
        self.feature_importances_ = None

    def _gini(self, y):
        """Compute Gini impurity for a set of labels."""
        if len(y) == 0:
            return 0.0
        counts = np.bincount(y.astype(np.int64))
        p = counts / len(y)
        return 1.0 - np.sum(p ** 2)

    def _best_split(self, X, y, feature_indices):
        """Find the best split point using Gini impurity.
        
        Args:
            X: feature matrix
            y: labels
            feature_indices: indices of features to consider
            
        Returns:
            (best_feature_idx, best_threshold, best_gain) or None
        """
        n = len(y)
        if n < self.min_samples_split:
            return None
        
        parent_gini = self._gini(y)
        best_gain = 0.0
        best_feature = None
        best_threshold = None
        
        for feat_idx in feature_indices:
            col = X[:, feat_idx]
            # Get unique sorted values for potential splits
            unique_vals = np.unique(col)
            if len(unique_vals) <= 1:
                continue
            
            # Consider midpoints between sorted unique values
            thresholds = (unique_vals[:-1] + unique_vals[1:]) / 2.0
            
            for threshold in thresholds:
                left_mask = col <= threshold
                right_mask = ~left_mask
                
                n_left = np.sum(left_mask)
                n_right = np.sum(right_mask)
                
                if n_left < self.min_samples_split or n_right < self.min_samples_split:
                    continue
                
                gini_left = self._gini(y[left_mask])
                gini_right = self._gini(y[right_mask])
                
                weighted_gini = (n_left / n) * gini_left + (n_right / n) * gini_right
                gain = parent_gini - weighted_gini
                
                if gain > best_gain:
                    best_gain = gain
                    best_feature = int(feat_idx)
                    best_threshold = float(threshold)
        
        if best_gain <= 0:
            return None
        
        return best_feature, best_threshold, best_gain

    def _build_tree(self, X, y, depth=0):
        """Recursively build decision tree."""
        n_samples = len(y)
        n_classes = len(np.unique(y))
        
        # Stopping conditions
        if (depth >= self.max_depth or 
            n_samples < self.min_samples_split or 
            n_classes == 1):
            # Leaf node: return probability distribution
            prob = float(np.mean(y))
            return {
                'type': 'leaf',
                'probability': prob,
                'n_samples': n_samples,
                'depth': depth,
            }
        
        # Determine feature subset
        n_features_total = X.shape[1]
        if self.n_features is not None:
            n_subset = min(self.n_features, n_features_total)
            feature_indices = np.random.choice(n_features_total, n_subset, replace=False)
        else:
            feature_indices = np.arange(n_features_total)
        
        # Find best split
        result = self._best_split(X, y, feature_indices)
        if result is None:
            prob = float(np.mean(y))
            return {
                'type': 'leaf',
                'probability': prob,
                'n_samples': n_samples,
                'depth': depth,
            }
        
        feat_idx, threshold, gain = result
        
        # Split data
        left_mask = X[:, feat_idx] <= threshold
        right_mask = ~left_mask
        
        left = self._build_tree(X[left_mask], y[left_mask], depth + 1)
        right = self._build_tree(X[right_mask], y[right_mask], depth + 1)
        
        return {
            'type': 'node',
            'feature': feat_idx,
            'threshold': threshold,
            'gain': gain,
            'left': left,
            'right': right,
            'n_samples': n_samples,
            'depth': depth,
        }

    def _compute_importances(self, tree, total_samples):
        """Recursively compute feature importance based on Gini gain weighted by samples."""
        if tree['type'] == 'leaf':
            return {}
        
        feat = tree['feature']
        gain = tree['gain']
        weight = tree['n_samples'] / total_samples
        imp = gain * weight
        
        importances = {feat: imp}
        
        left_imp = self._compute_importances(tree['left'], total_samples)
        right_imp = self._compute_importances(tree['right'], total_samples)
        
        for k, v in left_imp.items():
            importances[k] = importances.get(k, 0.0) + v
        for k, v in right_imp.items():
            importances[k] = importances.get(k, 0.0) + v
        
        return importances

    def fit(self, X, y):
        """Build the decision tree from training data."""
        y = y.astype(np.float64)
        self.tree = self._build_tree(X, y, depth=0)
        
        # Compute feature importances
        n_features = X.shape[1]
        importances = self._compute_importances(self.tree, len(y))
        self.feature_importances_ = np.zeros(n_features, dtype=np.float64)
        for idx, imp in importances.items():
            if idx < n_features:
                self.feature_importances_[idx] = imp
        
        # Normalize
        total = np.sum(self.feature_importances_)
        if total > 0:
            self.feature_importances_ /= total
        
        return self

    def _predict_tree(self, tree, x):
        """Predict probability for a single sample."""
        if tree['type'] == 'leaf':
            return tree['probability']
        
        if x[tree['feature']] <= tree['threshold']:
            return self._predict_tree(tree['left'], x)
        else:
            return self._predict_tree(tree['right'], x)

    def predict_proba(self, X):
        """Predict probability of default for each sample."""
        if self.tree is None:
            raise ValueError("Model not fitted yet.")
        return np.array([self._predict_tree(self.tree, x) for x in X], dtype=np.float64)

    def to_dict(self):
        """Serialize tree to dict."""
        return {
            'type': 'decision_tree',
            'max_depth': self.max_depth,
            'min_samples_split': self.min_samples_split,
            'n_features': self.n_features,
            'tree': self.tree,
            'feature_importances': self.feature_importances_.tolist() if isinstance(self.feature_importances_, np.ndarray) else self.feature_importances_,
        }

    @classmethod
    def from_dict(cls, d):
        """Load tree from dict."""
        tree = cls(
            max_depth=d.get('max_depth', 5),
            min_samples_split=d.get('min_samples_split', 20),
            n_features=d.get('n_features'),
        )
        tree.tree = d['tree']
        tree.feature_importances_ = np.array(d.get('feature_importances', []), dtype=np.float64)
        return tree
