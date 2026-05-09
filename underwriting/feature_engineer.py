#!/usr/bin/env python3
"""Feature engineering pipeline for credit underwriting."""

import numpy as np
from collections import OrderedDict


class CreditFeatureEngineer:
    """Transform raw borrower data into model-ready feature vectors.
    
    Fits on training data, then consistently transforms any data.
    """

    def __init__(self):
        # Min/max for normalization (fitted from training data)
        self.norm_min = {}
        self.norm_max = {}
        
        # Categorical encodings
        self.home_ownership_categories = ['rent', 'mortgage', 'own']
        self.loan_purpose_categories = [
            'debt_consolidation', 'home_improvement', 'medical',
            'education', 'business', 'personal'
        ]
        self.purpose_encoding = {}
        
        # Median values for imputation
        self.medians = {}
        
        # Whether fit has been called
        self.fitted = False
        
        # Order of features output by transform
        self.feature_names = None

    def _init_norm(self):
        """Initialize normalization bounds for continuous features."""
        self.cont_features = [
            'age', 'annual_income', 'employment_length', 'credit_score',
            'dti_ratio', 'utilization', 'num_derogatory', 'num_credit_lines',
            'loan_amount'
        ]
        for feat in self.cont_features:
            self.norm_min[feat] = 0.0
            self.norm_max[feat] = 1.0

    def fit(self, data):
        """Fit feature engineering pipeline to training data.
        
        Args:
            data: List of dicts with raw borrower features
        """
        n = len(data)
        
        # Initialize normalization bounds
        self._init_norm()
        
        # Compute min/max for continuous features
        for feat in self.cont_features:
            values = [row[feat] for row in data]
            self.norm_min[feat] = float(min(values))
            self.norm_max[feat] = float(max(values))
            if self.norm_max[feat] == self.norm_min[feat]:
                self.norm_max[feat] = self.norm_min[feat] + 1.0

        # Compute medians for imputation
        for feat in self.cont_features:
            values = sorted([row[feat] for row in data])
            if n % 2 == 0:
                median = (values[n // 2 - 1] + values[n // 2]) / 2.0
            else:
                median = float(values[n // 2])
            self.medians[feat] = median

        # Build purpose encoding (label encoding by frequency)
        purpose_counts = {}
        for row in data:
            p = row['loan_purpose']
            purpose_counts[p] = purpose_counts.get(p, 0) + 1
        
        sorted_purposes = sorted(purpose_counts.items(), key=lambda x: -x[1])
        for idx, (purpose, _) in enumerate(sorted_purposes):
            self.purpose_encoding[purpose] = idx
        
        # Ensure all purposes are encoded
        for p in self.loan_purpose_categories:
            if p not in self.purpose_encoding:
                self.purpose_encoding[p] = len(self.purpose_encoding)

        # Build feature names
        self.feature_names = (
            [f for f in self.cont_features] +  # normalized continuous
            ['loan_to_income', 'debt_payment_ratio', 
             'credit_utilization_score', 'account_diversity', 'risk_flags'] +
            [f'home_{h}' for h in self.home_ownership_categories] +
            ['loan_purpose_encoded']
        )
        
        self.fitted = True
        return self

    def transform(self, data):
        """Transform raw data into feature matrix.
        
        Args:
            data: List of dicts with raw borrower features
            
        Returns:
            np.ndarray of shape (n_samples, n_features)
        """
        if not self.fitted:
            raise ValueError("Engine must be fitted before transform. Call .fit() first.")
        
        rows = []
        for row in data:
            features = self._transform_row(row)
            rows.append(features)
        
        return np.array(rows, dtype=np.float64)

    def fit_transform(self, data):
        """Fit and transform in one step."""
        self.fit(data)
        return self.transform(data)

    def _transform_row(self, row):
        """Transform a single row into feature vector."""
        # Impute missing values with median
        r = {}
        for feat in self.cont_features:
            val = row.get(feat)
            if val is None or (isinstance(val, float) and np.isnan(val)):
                val = self.medians[feat]
            r[feat] = val

        # 1. Normalize continuous features to [0, 1]
        normalized = []
        for feat in self.cont_features:
            v = r[feat]
            min_v = self.norm_min[feat]
            max_v = self.norm_max[feat]
            if max_v > min_v:
                norm_val = (v - min_v) / (max_v - min_v)
            else:
                norm_val = 0.5
            normalized.append(max(0.0, min(1.0, norm_val)))

        # 2. Derived features
        annual_income = max(1, r['annual_income'])
        loan_to_income = r['loan_amount'] / annual_income
        # debt_payment_ratio: combines dti with loan burden
        debt_payment_ratio = r['dti_ratio'] * (1.0 + loan_to_income * 3.0)
        # credit_utilization_score: penalizes high util + low score
        credit_utilization_score = r['utilization'] * (1.0 - r['credit_score'] / 850.0)
        # account_diversity: how many credit lines relative to age
        account_diversity = min(1.0, r['num_credit_lines'] / max(1, max(1, r['age'] - 20)) * 10.0)
        # risk_flags: combined risk signals
        risk_flags = 0.0
        if r['num_derogatory'] >= 2:
            risk_flags += 0.3
        if r['utilization'] > 0.8:
            risk_flags += 0.2
        if r['dti_ratio'] > 0.4:
            risk_flags += 0.2
        if r['credit_score'] < 580:
            risk_flags += 0.3
        risk_flags = min(1.0, risk_flags)

        derived = [loan_to_income, debt_payment_ratio, 
                  credit_utilization_score, account_diversity, risk_flags]

        # 3. One-hot encoding for home_ownership
        home = row.get('home_ownership', 'rent')
        home_encoding = []
        for h in self.home_ownership_categories:
            home_encoding.append(1.0 if home == h else 0.0)

        # 4. Label encoding for loan_purpose
        purpose = row.get('loan_purpose', 'personal')
        purpose_encoded = float(self.purpose_encoding.get(purpose, 0))

        return normalized + derived + home_encoding + [purpose_encoded]

    def get_feature_names(self):
        """Return ordered list of feature names."""
        return list(self.feature_names) if self.feature_names else []

    def to_dict(self):
        """Serialize engineering params to dict for saving."""
        return {
            'norm_min': self.norm_min,
            'norm_max': self.norm_max,
            'medians': self.medians,
            'purpose_encoding': self.purpose_encoding,
            'feature_names': self.feature_names,
            'home_ownership_categories': self.home_ownership_categories,
        }

    @classmethod
    def from_dict(cls, d):
        """Load engineering params from dict."""
        eng = cls()
        eng._init_norm()  # Must call this to set cont_features
        eng.norm_min = d['norm_min']
        eng.norm_max = d['norm_max']
        eng.medians = d.get('medians', {})
        eng.purpose_encoding = d.get('purpose_encoding', {})
        eng.feature_names = d.get('feature_names')
        eng.home_ownership_categories = d.get(
            'home_ownership_categories', ['rent', 'mortgage', 'own'])
        eng.fitted = True
        return eng
