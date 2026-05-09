#!/usr/bin/env python3
"""Pure Python logistic regression with L2 regularization."""

import numpy as np
import math


class LogisticRegression:
    """Binary logistic regression trained via gradient descent."""

    def __init__(self, lr=0.01, iterations=2000, l2=0.01):
        self.lr = lr
        self.iterations = iterations
        self.l2 = l2  # L2 regularization strength
        self.weights = None
        self.bias = None
        self.loss_history = []

    def sigmoid(self, z):
        """Numerically stable sigmoid."""
        # Clip to avoid overflow
        z = np.clip(z, -500, 500)
        return 1.0 / (1.0 + np.exp(-z))

    def fit(self, X, y):
        """Gradient descent with L2 regularization.
        
        Args:
            X: np.ndarray of shape (n_samples, n_features)
            y: np.ndarray of shape (n_samples,) with 0/1 values
        """
        n_samples, n_features = X.shape
        
        # Initialize weights
        self.weights = np.zeros(n_features, dtype=np.float64)
        self.bias = 0.0
        
        self.loss_history = []
        
        for i in range(self.iterations):
            # Forward pass
            linear = np.dot(X, self.weights) + self.bias
            predictions = self.sigmoid(linear)
            
            # Compute loss (binary cross-entropy + L2)
            eps = 1e-15
            loss = -np.mean(
                y * np.log(predictions + eps) + 
                (1 - y) * np.log(1 - predictions + eps)
            ) + (self.l2 / (2 * n_samples)) * np.sum(self.weights ** 2)
            
            self.loss_history.append(loss)
            
            # Gradients
            dw = (1 / n_samples) * np.dot(X.T, (predictions - y)) + (self.l2 / n_samples) * self.weights
            db = (1 / n_samples) * np.sum(predictions - y)
            
            # Update
            self.weights -= self.lr * dw
            self.bias -= self.lr * db
        
        return self

    def predict_proba(self, X):
        """Predict probability of class 1 (default)."""
        if self.weights is None:
            raise ValueError("Model not fitted yet.")
        linear = np.dot(X, self.weights) + self.bias
        return self.sigmoid(linear)

    def predict(self, X, threshold=0.5):
        """Predict binary class labels."""
        proba = self.predict_proba(X)
        return (proba >= threshold).astype(np.int64)

    def get_weights(self):
        """Return model weights and bias."""
        return {
            'weights': self.weights.tolist() if isinstance(self.weights, np.ndarray) else self.weights,
            'bias': float(self.bias),
            'l2': self.l2,
        }

    def to_dict(self):
        """Serialize model to dict."""
        return {
            'type': 'logistic_regression',
            'weights': self.weights.tolist() if isinstance(self.weights, np.ndarray) else self.weights,
            'bias': float(self.bias),
            'l2': self.l2,
            'loss_history': self.loss_history,
        }

    @classmethod
    def from_dict(cls, d):
        """Load model from dict."""
        model = cls(
            lr=d.get('lr', 0.01),
            iterations=d.get('iterations', 2000),
            l2=d.get('l2', 0.01),
        )
        model.weights = np.array(d['weights'], dtype=np.float64)
        model.bias = float(d['bias'])
        model.loss_history = d.get('loss_history', [])
        return model
