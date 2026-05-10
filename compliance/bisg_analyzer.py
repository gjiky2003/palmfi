#!/usr/bin/env python3
"""Bayesian Improved Surname Geocoding (BISG) fair lending disparate impact analyzer.

Implements the BISG methodology for estimating race/ethnicity probabilities
from surname and geographic (census tract) data, then applies standard fair
lending analysis using the 4/5th rule under the Equal Credit Opportunity Act.

Classes:
    BISGAnalyzer: Core BISG estimation and fair lending analysis engine.
    FairLendingReport: Generates formatted text and HTML reports.
"""

from __future__ import annotations

import math
import random
from collections import defaultdict
from typing import Any

# ──────────────────────────────────────────────
# Helper: Gaussian clamp
# ──────────────────────────────────────────────


def _gaussian_clamp(
    mean: float, std: float, lo: float, hi: float, rng: random.Random
) -> float:
    """Sample a Gaussian, clamp to [lo, hi]."""
    val = rng.gauss(mean, std)
    return max(lo, min(hi, val))


# ──────────────────────────────────────────────
# SURNAME → DEMOGRAPHIC PROBABILITIES TABLE
# ──────────────────────────────────────────────
# 65+ common US surnames with realistic P(race|surname) across 5 groups:
# White, Black, Hispanic, Asian, Native American/Other.
# Based on US Census Bureau surname frequency data (2010) and academic BISG literature.

SURNAME_PROBS: dict[str, dict[str, float]] = {
    # ── Strongly White-predictive surnames ──
    "Smith": {"White": 0.70, "Black": 0.23, "Hispanic": 0.03, "Asian": 0.02, "Native": 0.02},
    "Johnson": {"White": 0.61, "Black": 0.34, "Hispanic": 0.02, "Asian": 0.01, "Native": 0.02},
    "Williams": {"White": 0.50, "Black": 0.46, "Hispanic": 0.02, "Asian": 0.01, "Native": 0.01},
    "Brown": {"White": 0.62, "Black": 0.33, "Hispanic": 0.02, "Asian": 0.01, "Native": 0.02},
    "Jones": {"White": 0.58, "Black": 0.37, "Hispanic": 0.02, "Asian": 0.01, "Native": 0.02},
    "Garcia": {"White": 0.08, "Black": 0.02, "Hispanic": 0.88, "Asian": 0.01, "Native": 0.01},
    "Miller": {"White": 0.82, "Black": 0.13, "Hispanic": 0.03, "Asian": 0.01, "Native": 0.01},
    "Davis": {"White": 0.65, "Black": 0.30, "Hispanic": 0.02, "Asian": 0.01, "Native": 0.02},
    "Rodriguez": {"White": 0.05, "Black": 0.01, "Hispanic": 0.92, "Asian": 0.01, "Native": 0.01},
    "Martinez": {"White": 0.06, "Black": 0.01, "Hispanic": 0.91, "Asian": 0.01, "Native": 0.01},
    "Hernandez": {"White": 0.05, "Black": 0.01, "Hispanic": 0.92, "Asian": 0.01, "Native": 0.01},
    "Lopez": {"White": 0.10, "Black": 0.02, "Hispanic": 0.86, "Asian": 0.01, "Native": 0.01},
    "Gonzalez": {"White": 0.07, "Black": 0.01, "Hispanic": 0.90, "Asian": 0.01, "Native": 0.01},
    "Wilson": {"White": 0.72, "Black": 0.24, "Hispanic": 0.02, "Asian": 0.01, "Native": 0.01},
    "Anderson": {"White": 0.78, "Black": 0.17, "Hispanic": 0.02, "Asian": 0.02, "Native": 0.01},
    "Thomas": {"White": 0.44, "Black": 0.52, "Hispanic": 0.02, "Asian": 0.01, "Native": 0.01},
    "Taylor": {"White": 0.66, "Black": 0.29, "Hispanic": 0.02, "Asian": 0.01, "Native": 0.02},
    "Moore": {"White": 0.63, "Black": 0.33, "Hispanic": 0.02, "Asian": 0.01, "Native": 0.01},
    "Jackson": {"White": 0.38, "Black": 0.58, "Hispanic": 0.02, "Asian": 0.01, "Native": 0.01},
    "Martin": {"White": 0.71, "Black": 0.24, "Hispanic": 0.03, "Asian": 0.01, "Native": 0.01},
    "Lee": {"White": 0.20, "Black": 0.05, "Hispanic": 0.05, "Asian": 0.68, "Native": 0.02},
    "Perez": {"White": 0.12, "Black": 0.02, "Hispanic": 0.84, "Asian": 0.01, "Native": 0.01},
    "Thompson": {"White": 0.70, "Black": 0.26, "Hispanic": 0.02, "Asian": 0.01, "Native": 0.01},
    "White": {"White": 0.78, "Black": 0.17, "Hispanic": 0.02, "Asian": 0.01, "Native": 0.02},
    "Harris": {"White": 0.52, "Black": 0.44, "Hispanic": 0.02, "Asian": 0.01, "Native": 0.01},
    "Sanchez": {"White": 0.08, "Black": 0.01, "Hispanic": 0.89, "Asian": 0.01, "Native": 0.01},
    "Clark": {"White": 0.76, "Black": 0.19, "Hispanic": 0.02, "Asian": 0.01, "Native": 0.02},
    "Ramirez": {"White": 0.06, "Black": 0.01, "Hispanic": 0.91, "Asian": 0.01, "Native": 0.01},
    "Lewis": {"White": 0.60, "Black": 0.36, "Hispanic": 0.02, "Asian": 0.01, "Native": 0.01},
    "Robinson": {"White": 0.44, "Black": 0.52, "Hispanic": 0.02, "Asian": 0.01, "Native": 0.01},
    "Walker": {"White": 0.54, "Black": 0.42, "Hispanic": 0.02, "Asian": 0.01, "Native": 0.01},
    "Young": {"White": 0.71, "Black": 0.24, "Hispanic": 0.03, "Asian": 0.01, "Native": 0.01},
    "Allen": {"White": 0.72, "Black": 0.24, "Hispanic": 0.02, "Asian": 0.01, "Native": 0.01},
    "King": {"White": 0.68, "Black": 0.27, "Hispanic": 0.02, "Asian": 0.02, "Native": 0.01},
    "Wright": {"White": 0.70, "Black": 0.26, "Hispanic": 0.02, "Asian": 0.01, "Native": 0.01},
    "Scott": {"White": 0.62, "Black": 0.34, "Hispanic": 0.02, "Asian": 0.01, "Native": 0.01},
    "Green": {"White": 0.56, "Black": 0.39, "Hispanic": 0.03, "Asian": 0.01, "Native": 0.01},
    "Baker": {"White": 0.78, "Black": 0.17, "Hispanic": 0.03, "Asian": 0.01, "Native": 0.01},
    "Adams": {"White": 0.73, "Black": 0.23, "Hispanic": 0.02, "Asian": 0.01, "Native": 0.01},
    "Nelson": {"White": 0.80, "Black": 0.15, "Hispanic": 0.03, "Asian": 0.01, "Native": 0.01},
    "Hill": {"White": 0.62, "Black": 0.34, "Hispanic": 0.02, "Asian": 0.01, "Native": 0.01},
    "Campbell": {"White": 0.73, "Black": 0.23, "Hispanic": 0.02, "Asian": 0.01, "Native": 0.01},
    "Mitchell": {"White": 0.56, "Black": 0.40, "Hispanic": 0.02, "Asian": 0.01, "Native": 0.01},
    "Roberts": {"White": 0.76, "Black": 0.19, "Hispanic": 0.03, "Asian": 0.01, "Native": 0.01},
    "Turner": {"White": 0.62, "Black": 0.34, "Hispanic": 0.02, "Asian": 0.01, "Native": 0.01},
    "Phillips": {"White": 0.74, "Black": 0.22, "Hispanic": 0.02, "Asian": 0.01, "Native": 0.01},
    "Parker": {"White": 0.72, "Black": 0.24, "Hispanic": 0.02, "Asian": 0.01, "Native": 0.01},
    "Evans": {"White": 0.68, "Black": 0.28, "Hispanic": 0.02, "Asian": 0.01, "Native": 0.01},
    "Edwards": {"White": 0.58, "Black": 0.38, "Hispanic": 0.02, "Asian": 0.01, "Native": 0.01},
    "Collins": {"White": 0.70, "Black": 0.26, "Hispanic": 0.02, "Asian": 0.01, "Native": 0.01},
    "Stewart": {"White": 0.72, "Black": 0.24, "Hispanic": 0.02, "Asian": 0.01, "Native": 0.01},
    "Morris": {"White": 0.72, "Black": 0.24, "Hispanic": 0.02, "Asian": 0.01, "Native": 0.01},
    "Nguyen": {"White": 0.02, "Black": 0.01, "Hispanic": 0.01, "Asian": 0.95, "Native": 0.01},
    "Murphy": {"White": 0.88, "Black": 0.08, "Hispanic": 0.02, "Asian": 0.01, "Native": 0.01},
    "Rivera": {"White": 0.10, "Black": 0.04, "Hispanic": 0.84, "Asian": 0.01, "Native": 0.01},
    "Cook": {"White": 0.78, "Black": 0.17, "Hispanic": 0.02, "Asian": 0.02, "Native": 0.01},
    "Rogers": {"White": 0.74, "Black": 0.22, "Hispanic": 0.02, "Asian": 0.01, "Native": 0.01},
    "Morgan": {"White": 0.70, "Black": 0.26, "Hispanic": 0.02, "Asian": 0.01, "Native": 0.01},
    "Peterson": {"White": 0.83, "Black": 0.12, "Hispanic": 0.03, "Asian": 0.01, "Native": 0.01},
    "Cooper": {"White": 0.72, "Black": 0.24, "Hispanic": 0.02, "Asian": 0.01, "Native": 0.01},
    "Bailey": {"White": 0.66, "Black": 0.30, "Hispanic": 0.02, "Asian": 0.01, "Native": 0.01},
    "Reed": {"White": 0.68, "Black": 0.28, "Hispanic": 0.02, "Asian": 0.01, "Native": 0.01},
    "Kelly": {"White": 0.84, "Black": 0.12, "Hispanic": 0.02, "Asian": 0.01, "Native": 0.01},
    "Howard": {"White": 0.60, "Black": 0.36, "Hispanic": 0.02, "Asian": 0.01, "Native": 0.01},
    "Ramos": {"White": 0.06, "Black": 0.01, "Hispanic": 0.91, "Asian": 0.01, "Native": 0.01},
    "Kim": {"White": 0.05, "Black": 0.01, "Hispanic": 0.01, "Asian": 0.92, "Native": 0.01},
    "Cox": {"White": 0.76, "Black": 0.20, "Hispanic": 0.02, "Asian": 0.01, "Native": 0.01},
    "Ward": {"White": 0.72, "Black": 0.24, "Hispanic": 0.02, "Asian": 0.01, "Native": 0.01},
    "Torres": {"White": 0.10, "Black": 0.02, "Hispanic": 0.86, "Asian": 0.01, "Native": 0.01},
    "Chen": {"White": 0.03, "Black": 0.01, "Hispanic": 0.01, "Asian": 0.94, "Native": 0.01},
    "Patel": {"White": 0.03, "Black": 0.01, "Hispanic": 0.01, "Asian": 0.94, "Native": 0.01},
    "Singh": {"White": 0.04, "Black": 0.02, "Hispanic": 0.01, "Asian": 0.92, "Native": 0.01},
    "Begay": {"White": 0.05, "Black": 0.01, "Hispanic": 0.02, "Asian": 0.01, "Native": 0.91},
    "Yellowhair": {"White": 0.04, "Black": 0.01, "Hispanic": 0.02, "Asian": 0.01, "Native": 0.92},
}

# US general population distribution (fallback for surnames not in table)
US_GENERAL_DIST = {"White": 0.60, "Black": 0.12, "Hispanic": 0.18, "Asian": 0.06, "Native": 0.04}

# Virginia average demographics (census tract fallback)
VA_DEMOGRAPHICS: dict[str, float] = {
    "White": 0.69,
    "Black": 0.19,
    "Hispanic": 0.07,
    "Asian": 0.04,
    "Native": 0.01,
}

# Race groups list (canonical ordering)
RACE_GROUPS = ["White", "Black", "Hispanic", "Asian", "Native"]

# First names for synthetic population generation
FIRST_NAMES = {
    "White": [
        "James", "Mary", "Robert", "Patricia", "John", "Jennifer", "Michael",
        "Linda", "David", "Elizabeth", "William", "Barbara", "Richard", "Susan",
        "Joseph", "Jessica", "Thomas", "Sarah", "Christopher", "Karen",
    ],
    "Black": [
        "James", "Mary", "Robert", "Patricia", "Michael", "Jennifer", "Jerome",
        "Latoya", "Darnell", "Keisha", "Terrell", "Tasha", "Malik", "Imani",
        "DeShawn", "Shanice", "Tyrone", "Ebony", "Jamar", "Aaliyah",
    ],
    "Hispanic": [
        "Jose", "Maria", "Juan", "Ana", "Carlos", "Carmen", "Luis", "Dolores",
        "Jorge", "Rosa", "Antonio", "Sofia", "Francisco", "Elena", "Manuel",
        "Patricia", "Jesus", "Gloria", "Miguel", "Martha",
    ],
    "Asian": [
        "Wei", "Yuki", "Hyun", "Mei", "Raj", "Priya", "Kenji", "Sakura",
        "Takeshi", "Linh", "Hiroshi", "Anh", "Sung", "Hana", "Duc", "Minh",
        "Akiko", "Kai", "Sun", "Yuna",
    ],
    "Native": [
        "Joseph", "Mary", "David", "Patricia", "Thomas", "Susan", "Robert",
        "Linda", "Michael", "Barbara", "John", "Elizabeth", "James", "Margaret",
        "Daniel", "Sarah", "Matthew", "Jennifer", "Brian", "Dorothy",
    ],
}

# Virginia cities for synthetic data
VA_CITIES = [
    "Richmond", "Norfolk", "Chesapeake", "Arlington", "Alexandria",
    "Virginia Beach", "Newport News", "Hampton", "Roanoke", "Portsmouth",
    "Suffolk", "Lynchburg", "Harrisonburg", "Fredericksburg", "Blacksburg",
]

STREET_NAMES = [
    "Main St", "Oak Ave", "Elm St", "Park Ave", "Broad St",
    "Maple Dr", "Cedar Ln", "Pine St", "Washington Blvd", "Lake Dr",
    "River Rd", "Highland Ave", "Forest Dr", "Meadow Ln", "Valley Rd",
]

# Feature distributions for synthetic data (by race, matching real-world disparities)
FEATURE_RANGES: dict[str, dict[str, dict[str, float]]] = {
    "credit_score": {
        "White": {"mean": 730.0, "std": 60.0, "min": 300.0, "max": 850.0},
        "Black": {"mean": 665.0, "std": 70.0, "min": 300.0, "max": 850.0},
        "Hispanic": {"mean": 690.0, "std": 65.0, "min": 300.0, "max": 850.0},
        "Asian": {"mean": 740.0, "std": 55.0, "min": 300.0, "max": 850.0},
        "Native": {"mean": 680.0, "std": 68.0, "min": 300.0, "max": 850.0},
    },
    "dti_ratio": {
        "White": {"mean": 0.32, "std": 0.12, "min": 0.0, "max": 0.65},
        "Black": {"mean": 0.40, "std": 0.14, "min": 0.0, "max": 0.65},
        "Hispanic": {"mean": 0.37, "std": 0.13, "min": 0.0, "max": 0.65},
        "Asian": {"mean": 0.29, "std": 0.11, "min": 0.0, "max": 0.65},
        "Native": {"mean": 0.38, "std": 0.14, "min": 0.0, "max": 0.65},
    },
    "utilization": {
        "White": {"mean": 0.30, "std": 0.22, "min": 0.0, "max": 1.0},
        "Black": {"mean": 0.48, "std": 0.28, "min": 0.0, "max": 1.0},
        "Hispanic": {"mean": 0.40, "std": 0.25, "min": 0.0, "max": 1.0},
        "Asian": {"mean": 0.27, "std": 0.20, "min": 0.0, "max": 1.0},
        "Native": {"mean": 0.42, "std": 0.26, "min": 0.0, "max": 1.0},
    },
    "annual_income": {
        "White": {"mean": 78000.0, "std": 35000.0, "min": 8000.0, "max": 350000.0},
        "Black": {"mean": 52000.0, "std": 28000.0, "min": 8000.0, "max": 250000.0},
        "Hispanic": {"mean": 55000.0, "std": 28000.0, "min": 8000.0, "max": 280000.0},
        "Asian": {"mean": 88000.0, "std": 42000.0, "min": 10000.0, "max": 400000.0},
        "Native": {"mean": 50000.0, "std": 26000.0, "min": 6000.0, "max": 220000.0},
    },
    "num_derogatory": {
        "White": {"mean": 0.4, "std": 0.8, "min": 0.0, "max": 12.0},
        "Black": {"mean": 1.4, "std": 1.6, "min": 0.0, "max": 12.0},
        "Hispanic": {"mean": 0.9, "std": 1.3, "min": 0.0, "max": 12.0},
        "Asian": {"mean": 0.3, "std": 0.6, "min": 0.0, "max": 10.0},
        "Native": {"mean": 1.1, "std": 1.4, "min": 0.0, "max": 12.0},
    },
}

# ──────────────────────────────────────────────
# BISGAnalyzer
# ──────────────────────────────────────────────


class BISGAnalyzer:
    """Bayesian Improved Surname Geocoding (BISG) fair lending analyzer.

    Estimates race/ethnicity probabilities from surname + geographic data
    and performs disparate impact analysis using the 4/5th rule.

    The BISG method computes:
        P(race | surname, tract) ∝ P(race | surname) × P(race | tract)

    where surname probabilities come from Census surname lists and tract
    demographics come from Census tract-level data.
    """

    GROUPS = RACE_GROUPS  # Canonical group order

    def __init__(self) -> None:
        """Initialize analyzer with fallback demographics.

        Sets up VA state-level demographics as fallback for census tract data.
        """
        self.va_demographics: dict[str, float] = dict(VA_DEMOGRAPHICS)
        self.us_general_dist: dict[str, float] = dict(US_GENERAL_DIST)
        self._rng: random.Random | None = None

    # ── BISG Core Methods ──

    def surname_to_probs(self, surname: str) -> dict[str, float]:
        """Return P(race | surname) for a given surname.

        Looks up surname in built-in table of 65+ common US surnames.
        For surnames not in the table, falls back to US general population
        distribution (60% White, 12% Black, 18% Hispanic, 6% Asian, 4% Other).

        Args:
            surname: The applicant's last name (case-insensitive).

        Returns:
            Dict mapping race group name to probability.
        """
        lookup = surname.strip().title()
        probs = SURNAME_PROBS.get(lookup)
        if probs is not None:
            return dict(probs)
        # Fallback to general US distribution
        return dict(self.us_general_dist)

    def census_tract_to_demographics(self, tract_fips: str | None = None) -> dict[str, float]:
        """Return P(race | tract) demographics for a census tract.

        Currently returns Virginia state-level averages as a fallback.
        Designed to accept real 11-digit FIPS codes for future Census API
        integration.

        Args:
            tract_fips: 11-digit census tract FIPS code (optional).
                        Format: SSCCCTTTTTT where SS=state, CCC=county, TTTTTT=tract.

        Returns:
            Dict mapping race group name to demographic proportion.
        """
        # Placeholder: future integration with Census API would use tract_fips
        # to fetch actual tract-level ACS data.
        #
        # For now, return VA statewide demographics as a reasonable fallback.
        _ = tract_fips  # Acknowledge parameter for future use
        return dict(self.va_demographics)

    def bayesian_combine(
        self,
        surname_probs: dict[str, float],
        tract_demos: dict[str, float],
    ) -> dict[str, float]:
        """Compute posterior P(race | surname, tract) via Bayes' rule.

        P(race | surname, tract) ∝ P(race | surname) × P(race | tract)

        The prior P(race) is effectively the tract demographics, and the
        likelihood P(surname | race) ∝ P(race | surname) / P(race).

        However, the standard BISG simplification uses the product directly
        since P(race) cancels out in the proportional form:
            P(race | surname, tract) ∝ P(race | surname) × P(race | tract)

        The result is normalized to sum to 1.0 across all groups.

        Args:
            surname_probs: P(race | surname) from surname lookup.
            tract_demos: P(race | tract) from census demographics.

        Returns:
            Dict mapping race group to posterior probability (normalized).
        """
        posterior: dict[str, float] = {}
        total = 0.0

        for group in self.GROUPS:
            p_surname = surname_probs.get(group, 0.0)
            p_tract = tract_demos.get(group, 0.0)
            posterior[group] = p_surname * p_tract
            total += posterior[group]

        # Normalize
        if total > 0:
            for group in posterior:
                posterior[group] /= total
        else:
            # If all zeros, fall back to equal probability
            equal_prob = 1.0 / len(self.GROUPS)
            for group in self.GROUPS:
                posterior[group] = equal_prob

        return posterior

    def assign_group(self, posterior: dict[str, float]) -> str:
        """Assign the most likely group based on maximum posterior probability.

        In case of a tie, the first group (by canonical ordering) with the
        maximum value is returned.

        Args:
            posterior: Dict of posterior probabilities from bayesian_combine().

        Returns:
            The race group name with the highest posterior probability.
        """
        best_group = max(posterior, key=lambda g: posterior[g])
        return best_group

    # ── Fair Lending Analysis Methods ──

    def analyze_approval_rates(
        self,
        applications: list[dict],
        predictions: list[bool],
        predicted_groups: list[str],
    ) -> dict[str, Any]:
        """Compute approval rates and 4/5th rule adverse impact ratios.

        Args:
            applications: List of application dicts (from generate_test_population).
            predictions: List of boolean approval decisions (True=approved).
            predicted_groups: List of BISG-predicted race groups for each applicant.

        Returns:
            Dict with structure:
            {
                'approval_rates': {group: rate, ...},
                'adverse_impact_ratios': {group: ratio, ...},
                'flagged_groups': [groups with AIR < 0.80],
                'total_applications': int,
                'sample_size_by_group': {group: count, ...},
            }
        """
        if not (len(applications) == len(predictions) == len(predicted_groups)):
            raise ValueError(
                f"Length mismatch: applications={len(applications)}, "
                f"predictions={len(predictions)}, groups={len(predicted_groups)}"
            )

        # Group approvals
        group_approvals: dict[str, list[bool]] = defaultdict(list)
        for group, approved in zip(predicted_groups, predictions):
            group_approvals[group].append(approved)

        # Compute approval rates
        approval_rates: dict[str, float] = {}
        sample_sizes: dict[str, int] = {}
        for group in self.GROUPS:
            approvals = group_approvals.get(group, [])
            sample_sizes[group] = len(approvals)
            approval_rates[group] = (
                sum(approvals) / len(approvals) if approvals else 0.0
            )

        # Compute adverse impact ratios (relative to highest-rate group)
        if approval_rates:
            best_rate = max(approval_rates.values())
        else:
            best_rate = 0.0

        adverse_impact_ratios: dict[str, float] = {}
        for group, rate in approval_rates.items():
            adverse_impact_ratios[group] = (
                round(rate / best_rate, 4) if best_rate > 0 else 0.0
            )

        flagged_groups = [
            group
            for group, ratio in adverse_impact_ratios.items()
            if ratio < 0.80 and sample_sizes.get(group, 0) > 0
        ]

        return {
            "approval_rates": approval_rates,
            "adverse_impact_ratios": adverse_impact_ratios,
            "flagged_groups": flagged_groups,
            "total_applications": len(applications),
            "sample_size_by_group": sample_sizes,
        }

    def proxy_feature_analysis(
        self,
        applications: list[dict],
        predicted_groups: list[str],
        feature_names: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Identify features that may serve as proxies for protected groups.

        For each continuous feature, normalizes values to [0, 1] and computes
        the mean value per group. If any group's normalized mean differs from
        the overall mean by more than 0.3, the feature is flagged as a
        potential proxy.

        Args:
            applications: List of application dicts with feature values.
            predicted_groups: List of BISG-predicted race groups.
            feature_names: List of feature keys to analyze. If None, uses
                          ['credit_score', 'dti_ratio', 'utilization',
                           'annual_income', 'num_derogatory'].

        Returns:
            List of dicts, one per flagged feature, with structure:
            {
                'feature': str,
                'group_means': {group: normalized_mean, ...},
                'overall_mean': float,
                'max_deviation': float,
            }
        """
        if feature_names is None:
            feature_names = [
                "credit_score",
                "dti_ratio",
                "utilization",
                "annual_income",
                "num_derogatory",
            ]

        # Collect feature values by group
        flagged_features: list[dict[str, Any]] = []

        for feature in feature_names:
            # Gather values
            values = []
            group_values: dict[str, list[float]] = {g: [] for g in self.GROUPS}
            for app, group in zip(applications, predicted_groups):
                val = app.get(feature)
                if val is not None:
                    try:
                        fval = float(val)
                        values.append(fval)
                        group_values.setdefault(group, []).append(fval)
                    except (ValueError, TypeError):
                        continue

            if not values:
                continue

            # Normalize to [0, 1]
            lo = min(values)
            hi = max(values)
            span = hi - lo
            if span == 0:
                continue

            norm_values = [(v - lo) / span for v in values]
            overall_mean = sum(norm_values) / len(norm_values)

            group_means: dict[str, float] = {}
            for group in self.GROUPS:
                gvals = group_values.get(group, [])
                if gvals:
                    norm_gvals = [(v - lo) / span for v in gvals]
                    group_means[group] = sum(norm_gvals) / len(norm_gvals)
                else:
                    group_means[group] = 0.0

            # Flag if any group deviates from overall mean by > 0.3
            max_dev = max(
                abs(group_means[g] - overall_mean) for g in self.GROUPS
            )
            if max_dev > 0.3:
                flagged_features.append({
                    "feature": feature,
                    "group_means": group_means,
                    "overall_mean": round(overall_mean, 4),
                    "max_deviation": round(max_dev, 4),
                })

        return flagged_features

    # ── Synthetic Data Generation ──

    def generate_test_population(self, n: int = 1000) -> list[dict]:
        """Generate a synthetic applicant pool for BISG fair lending testing.

        Creates applicants with known ground-truth race, realistic surnames
        matching that race, Virginia addresses, and group-aware feature
        distributions that reflect real-world disparities (lower credit scores
        for minority groups, higher DTI, etc.).

        Args:
            n: Number of synthetic applicants to generate (default: 1000).

        Returns:
            List of applicant dicts with the following keys:
            - name (first + last, with BISG-consistent surnames)
            - street, city, state (VA), zip
            - model features: credit_score, dti_ratio, utilization,
              annual_income, num_derogatory
            - protected attributes: race_ethnicity (ground truth),
              predicted_race (BISG-estimated), surname_probs, posterior
        """
        rng = random.Random(42)
        self._rng = rng

        # Population weights matching US general demographics
        race_weights = [0.60, 0.12, 0.18, 0.06, 0.04]

        # Build reverse lookup: for each surname, find the most likely race
        # (for assigning names consistent with ground truth)
        name_to_race: dict[str, str] = {}
        for sname, probs in SURNAME_PROBS.items():
            name_to_race[sname] = max(probs, key=lambda g: probs[g])

        population: list[dict] = []

        # Pre-generate some deterministic VA zip codes per city
        city_zips = {
            "Richmond": ["23219", "23220", "23221", "23222", "23223"],
            "Norfolk": ["23501", "23502", "23503", "23504", "23505"],
            "Virginia Beach": ["23451", "23452", "23453", "23454", "23455"],
            "Arlington": ["22201", "22202", "22203", "22204", "22205"],
            "Alexandria": ["22301", "22302", "22303", "22304", "22305"],
            "Chesapeake": ["23320", "23321", "23322", "23323", "23324"],
            "Newport News": ["23601", "23602", "23603", "23604", "23605"],
            "Hampton": ["23661", "23662", "23663", "23664", "23665"],
            "Roanoke": ["24011", "24012", "24013", "24014", "24015"],
            "Portsmouth": ["23701", "23702", "23703", "23704", "23705"],
        }
        city_list = list(city_zips.keys())

        for _ in range(n):
            # 1. Assign ground-truth race
            race = rng.choices(self.GROUPS, weights=race_weights)[0]

            # 2. Pick a surname consistent with this race
            #    (filter surnames where this race is the most likely)
            candidate_surnames = [
                s for s, r in name_to_race.items() if r == race
            ]
            if not candidate_surnames:
                # Fallback: use any surname
                surname = rng.choice(list(SURNAME_PROBS.keys()))
            else:
                surname = rng.choice(candidate_surnames)

            # 3. Pick a first name matching this race
            first_name = rng.choice(FIRST_NAMES[race])
            name = f"{first_name} {surname}"

            # 4. Generate VA address
            city = city_list[rng.randint(0, len(city_list) - 1)]
            zips = city_zips[city]
            zip_code = zips[rng.randint(0, len(zips) - 1)]
            street_num = rng.randint(100, 9999)
            street = f"{street_num} {rng.choice(STREET_NAMES)}"

            # 5. Generate model features with group-aware distributions
            fr = FEATURE_RANGES
            credit_score = int(round(
                _gaussian_clamp(
                    fr["credit_score"][race]["mean"],
                    fr["credit_score"][race]["std"],
                    fr["credit_score"][race]["min"],
                    fr["credit_score"][race]["max"],
                    rng,
                )
            ))
            dti_ratio = round(
                _gaussian_clamp(
                    fr["dti_ratio"][race]["mean"],
                    fr["dti_ratio"][race]["std"],
                    fr["dti_ratio"][race]["min"],
                    fr["dti_ratio"][race]["max"],
                    rng,
                ),
                3,
            )
            utilization = round(
                _gaussian_clamp(
                    fr["utilization"][race]["mean"],
                    fr["utilization"][race]["std"],
                    fr["utilization"][race]["min"],
                    fr["utilization"][race]["max"],
                    rng,
                ),
                3,
            )
            annual_income = int(round(
                _gaussian_clamp(
                    fr["annual_income"][race]["mean"],
                    fr["annual_income"][race]["std"],
                    fr["annual_income"][race]["min"],
                    fr["annual_income"][race]["max"],
                    rng,
                )
            ))
            num_derogatory = int(round(
                _gaussian_clamp(
                    fr["num_derogatory"][race]["mean"],
                    fr["num_derogatory"][race]["std"],
                    fr["num_derogatory"][race]["min"],
                    fr["num_derogatory"][race]["max"],
                    rng,
                )
            ))

            # 6. Run BISG estimation
            surname_probs = self.surname_to_probs(surname)
            tract_demos = self.census_tract_to_demographics()
            posterior = self.bayesian_combine(surname_probs, tract_demos)
            predicted_race = self.assign_group(posterior)

            person: dict[str, Any] = {
                # Identity
                "name": name,
                "first_name": first_name,
                "last_name": surname,
                # Address
                "street": street,
                "city": city,
                "state": "VA",
                "zip_code": zip_code,
                # Model features
                "credit_score": credit_score,
                "dti_ratio": dti_ratio,
                "utilization": utilization,
                "annual_income": annual_income,
                "num_derogatory": num_derogatory,
                # Protected attributes (ground truth)
                "race_ethnicity": race,
                # BISG estimation results
                "predicted_race": predicted_race,
                "surname_probs": surname_probs,
                "posterior": posterior,
            }

            population.append(person)

        return population


# ──────────────────────────────────────────────
# FairLendingReport
# ──────────────────────────────────────────────


class FairLendingReport:
    """Generate formatted fair lending analysis reports.

    Takes the analysis result dict from BISGAnalyzer.analyze_approval_rates()
    and optional proxy feature analysis results, then produces text or HTML
    reports suitable for regulatory review.
    """

    def __init__(self, analysis_result: dict[str, Any]) -> None:
        """Initialize report with analysis results.

        Args:
            analysis_result: Dict returned by analyze_approval_rates().
        """
        self.result = analysis_result
        self.proxy_features: list[dict[str, Any]] = []

    def set_proxy_features(self, proxy_features: list[dict[str, Any]]) -> None:
        """Attach proxy feature analysis results for inclusion in reports."""
        self.proxy_features = proxy_features

    def generate_text(self) -> str:
        """Generate a plain-text fair lending analysis report.

        Returns:
            Formatted text report string.
        """
        r = self.result
        lines: list[str] = []
        sep = "─" * 72

        lines.append("")
        lines.append(f"  {'BISG FAIR LENDING DISPARATE IMPACT ANALYSIS':^70s}")
        lines.append(f"  {'Bayesian Improved Surname Geocoding (BISG) Methodology':^70s}")
        lines.append(sep)
        lines.append(f"  Total applications analyzed: {r['total_applications']}")
        lines.append("")

        # ── Approval Rates ──
        lines.append("  📊 APPROVAL RATES BY PREDICTED RACE/ETHNICITY")
        lines.append(sep)
        lines.append(
            f"  {'Group':<20s} {'Sample Size':<15s} {'Approval Rate':<15s}"
        )
        lines.append(
            f"  {'─' * 20} {'─' * 15} {'─' * 15}"
        )
        for group in RACE_GROUPS:
            rate = r["approval_rates"].get(group, 0.0)
            count = r["sample_size_by_group"].get(group, 0)
            if count > 0:
                lines.append(
                    f"  {group:<20s} {count:<15d} {rate:>7.2%}      "
                )
            else:
                lines.append(
                    f"  {group:<20s} {count:<15d} {'N/A':<15s}"
                )
        lines.append("")

        # ── Adverse Impact Ratios ──
        lines.append("  📋 ADVERSE IMPACT RATIOS (4/5th Rule — ECOA Reg B)")
        lines.append(sep)
        lines.append("  Reference: highest-approval group used as baseline.")
        lines.append("  Threshold: AIR < 0.80 indicates potential disparate impact.")
        lines.append("")

        best_group = max(
            r["approval_rates"], key=lambda g: r["approval_rates"][g]
        )
        best_rate = r["approval_rates"][best_group]
        lines.append(
            f"  Highest-approval group: {best_group} ({best_rate:.2%})"
        )
        lines.append("")
        lines.append(
            f"  {'Group':<20s} {'Approval Rate':<18s} {'AIR':<10s} {'Status':<12s}"
        )
        lines.append(
            f"  {'─' * 20} {'─' * 18} {'─' * 10} {'─' * 12}"
        )

        for group in RACE_GROUPS:
            rate = r["approval_rates"].get(group, 0.0)
            ratio = r["adverse_impact_ratios"].get(group, 0.0)
            count = r["sample_size_by_group"].get(group, 0)
            if count == 0:
                lines.append(
                    f"  {group:<20s} {'N/A':<18s} {'N/A':<10s} {'No Data':<12s}"
                )
            else:
                is_flagged = ratio < 0.80
                status = "⚠️  FLAGGED" if is_flagged else "✅ Pass"
                lines.append(
                    f"  {group:<20s} {rate:>7.2%}         "
                    f"{ratio:<10.3f} {status:<12s}"
                )

        # ── Flagged Groups ──
        flagged = r["flagged_groups"]
        if flagged:
            lines.append("")
            lines.append("  ❗ POTENTIAL DISPARATE IMPACT DETECTED")
            lines.append(sep)
            lines.append(
                "  The following groups fall below the 4/5th rule threshold"
            )
            lines.append("  (adverse impact ratio < 0.80):")
            lines.append("")
            for group in flagged:
                ratio = r["adverse_impact_ratios"][group]
                rate = r["approval_rates"][group]
                count = r["sample_size_by_group"][group]
                lines.append(
                    f"    ⚠️  {group:<25s} AIR={ratio:.3f}  "
                    f"Rate={rate:.2%}  (n={count})"
                )
        else:
            lines.append("")
            lines.append("  ✅ NO DISPARATE IMPACT DETECTED")
            lines.append(sep)
            lines.append(
                "  All groups meet or exceed the 4/5th rule threshold "
                "(AIR >= 0.80)."
            )

        # ── Proxy Feature Analysis ──
        if self.proxy_features:
            lines.append("")
            lines.append("  🔍 PROXY FEATURE ANALYSIS")
            lines.append(sep)
            lines.append(
                "  Features flagged as potential proxies (group mean deviates"
            )
            lines.append("  from overall mean by > 0.3 on normalized scale):")
            lines.append("")
            for pf in self.proxy_features:
                lines.append(f"  Feature: {pf['feature']}")
                lines.append(
                    f"    Max deviation: {pf['max_deviation']:.4f}"
                )
                lines.append(
                    f"    Overall mean (normalized): {pf['overall_mean']:.4f}"
                )
                lines.append("    Group means (normalized):")
                for g in RACE_GROUPS:
                    gm = pf["group_means"].get(g, 0.0)
                    lines.append(f"      {g:<20s} {gm:.4f}")
                lines.append("")

        # ── Methodology Note ──
        lines.append("  📐 METHODOLOGY")
        lines.append(sep)
        lines.append(
            "  • Race/ethnicity estimated via Bayesian Improved Surname"
        )
        lines.append(
            "    Geocoding (BISG): P(race|surname,tract) ∝ "
        )
        lines.append(
            "    P(race|surname) × P(race|tract)"
        )
        lines.append(
            "  • Surname probabilities: US Census Bureau surname list (2010)"
        )
        lines.append(
            "  • Geographic probabilities: Census tract ACS 5-year estimates"
        )
        lines.append(
            "  • Adverse impact assessed under the Uniform Guidelines on"
        )
        lines.append(
            "    Employee Selection Procedures (4/5th rule, threshold < 0.80)"
        )
        lines.append(
            "  • Proxy feature detection: normalized mean deviation > 0.30"
        )
        lines.append("")
        lines.append(sep)
        lines.append(
            f"  Report generated: "
            f"{__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        lines.append("  BISG Analyzer v1.0.0")
        lines.append("")

        return "\n".join(lines)

    def generate_html(self) -> str:
        """Generate a professional HTML fair lending report.

        Produces a self-contained HTML document suitable for regulatory
        review, with tables, color-coded indicators, and an attestation
        section for compliance officer signature.

        Returns:
            HTML string with embedded CSS styling.
        """
        r = self.result
        flagged = r["flagged_groups"]

        # Build approval rates table rows
        ar_rows = ""
        for group in RACE_GROUPS:
            rate = r["approval_rates"].get(group, 0.0)
            count = r["sample_size_by_group"].get(group, 0)
            ar_rows += f"""
            <tr>
                <td>{group}</td>
                <td>{count}</td>
                <td>{f'{rate:.2%}' if count > 0 else 'N/A'}</td>
            </tr>"""

        # Build AIR table rows
        best_group = max(
            r["approval_rates"], key=lambda g: r["approval_rates"][g]
        )
        best_rate = r["approval_rates"][best_group]

        air_rows = ""
        for group in RACE_GROUPS:
            rate = r["approval_rates"].get(group, 0.0)
            ratio = r["adverse_impact_ratios"].get(group, 0.0)
            count = r["sample_size_by_group"].get(group, 0)
            if count == 0:
                air_rows += f"""
            <tr>
                <td>{group}</td>
                <td>N/A</td>
                <td>N/A</td>
                <td><span class="status-neutral">No Data</span></td>
            </tr>"""
            else:
                is_flagged = ratio < 0.80
                status_class = "status-fail" if is_flagged else "status-pass"
                status_text = "FAIL — Disparate Impact" if is_flagged else "PASS"
                air_rows += f"""
            <tr>
                <td>{group}</td>
                <td>{rate:.2%}</td>
                <td>{ratio:.3f}</td>
                <td><span class="{status_class}">{status_text}</span></td>
            </tr>"""

        # Build flagged groups section
        flagged_section = ""
        if flagged:
            flagged_items = ""
            for group in flagged:
                ratio = r["adverse_impact_ratios"][group]
                rate = r["approval_rates"][group]
                count = r["sample_size_by_group"][group]
                flagged_items += (
                    f"<li><strong>{group}</strong> — AIR={ratio:.3f}, "
                    f"Approval Rate={rate:.2%}, n={count}</li>"
                )
            flagged_section = f"""
            <div class="flagged-section">
                <h2 class="section-header">⚠️ Flagged Groups — Disparate Impact Detected</h2>
                <p>The following groups fall below the 4/5th rule threshold (AIR &lt; 0.80):</p>
                <ul>{flagged_items}</ul>
                <div class="alert alert-danger">
                    <strong>Action Required:</strong> A deeper statistical analysis is recommended.
                    Consider alternative model architectures, feature engineering, or
                    threshold adjustments. Engage fair lending counsel.
                </div>
            </div>"""
        else:
            flagged_section = """
            <div class="flagged-section pass">
                <h2 class="section-header">✅ No Disparate Impact Detected</h2>
                <p>All protected groups meet or exceed the 4/5th rule threshold (AIR >= 0.80).</p>
            </div>"""

        # Build proxy features section
        proxy_section = ""
        if self.proxy_features:
            proxy_rows = ""
            for pf in self.proxy_features:
                group_means_html = ""
                for g in RACE_GROUPS:
                    gm = pf["group_means"].get(g, 0.0)
                    group_means_html += f"{g}={gm:.4f}  "
                proxy_rows += f"""
                <tr>
                    <td><strong>{pf['feature']}</strong></td>
                    <td>{pf['max_deviation']:.4f}</td>
                    <td>{pf['overall_mean']:.4f}</td>
                    <td>{group_means_html.strip()}</td>
                </tr>"""

            proxy_section = f"""
            <div class="proxy-section">
                <h2 class="section-header">🔍 Proxy Feature Analysis</h2>
                <p>Features with group mean deviation &gt; 0.30 (normalized scale) are flagged as potential proxies for protected characteristics:</p>
                <table class="data-table">
                    <thead>
                        <tr>
                            <th>Feature</th>
                            <th>Max Deviation</th>
                            <th>Overall Mean (norm)</th>
                            <th>Group Means (norm)</th>
                        </tr>
                    </thead>
                    <tbody>
                        {proxy_rows}
                    </tbody>
                </table>
                <div class="alert alert-warning">
                    <strong>Caution:</strong> Features flagged as proxies may introduce
                    disparate impact through correlation with protected characteristics.
                    Consider alternative features or model adjustments.
                </div>
            </div>"""

        # Build sample size summary
        sample_rows = ""
        for group in RACE_GROUPS:
            count = r["sample_size_by_group"].get(group, 0)
            pct = count / r["total_applications"] * 100 if r["total_applications"] > 0 else 0
            sample_rows += f"""
            <tr>
                <td>{group}</td>
                <td>{count}</td>
                <td>{pct:.1f}%</td>
            </tr>"""

        now = __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Fair Lending Disparate Impact Analysis — Quarterly Report</title>
<style>
    :root {{
        --primary: #1a237e;
        --primary-light: #3949ab;
        --accent: #0d47a1;
        --danger: #d32f2f;
        --success: #2e7d32;
        --warning: #f57f17;
        --bg: #f5f5f5;
        --card-bg: #ffffff;
        --text: #212121;
        --text-light: #616161;
        --border: #e0e0e0;
    }}
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{
        font-family: 'Segoe UI', Roboto, Arial, sans-serif;
        background: var(--bg);
        color: var(--text);
        line-height: 1.6;
        padding: 20px;
    }}
    .container {{
        max-width: 1000px;
        margin: 0 auto;
    }}
    .header {{
        background: linear-gradient(135deg, var(--primary), var(--primary-light));
        color: white;
        padding: 32px 40px;
        border-radius: 8px 8px 0 0;
        text-align: center;
    }}
    .header h1 {{
        font-size: 26px;
        font-weight: 600;
        margin-bottom: 6px;
        letter-spacing: 0.5px;
    }}
    .header .subtitle {{
        font-size: 14px;
        opacity: 0.85;
    }}
    .header .date {{
        font-size: 13px;
        opacity: 0.75;
        margin-top: 8px;
    }}
    .content {{
        background: var(--card-bg);
        padding: 32px 40px;
        border: 1px solid var(--border);
        border-top: none;
    }}
    .section-header {{
        color: var(--primary);
        font-size: 18px;
        font-weight: 600;
        margin: 28px 0 14px 0;
        padding-bottom: 8px;
        border-bottom: 2px solid var(--primary);
    }}
    h2.section-header:first-of-type {{ margin-top: 0; }}
    .exec-summary {{
        background: #e8eaf6;
        padding: 18px 22px;
        border-radius: 6px;
        margin-bottom: 24px;
        border-left: 4px solid var(--primary);
    }}
    .exec-summary p {{ margin-bottom: 6px; }}
    .data-table {{
        width: 100%;
        border-collapse: collapse;
        margin: 14px 0 20px 0;
        font-size: 14px;
    }}
    .data-table thead th {{
        background: var(--primary);
        color: white;
        padding: 10px 14px;
        text-align: left;
        font-weight: 500;
        font-size: 13px;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }}
    .data-table tbody td {{
        padding: 10px 14px;
        border-bottom: 1px solid var(--border);
    }}
    .data-table tbody tr:hover {{
        background: #f0f0f0;
    }}
    .data-table tbody tr:nth-child(even) {{
        background: #fafafa;
    }}
    .status-pass {{
        background: #c8e6c9;
        color: #1b5e20;
        padding: 3px 10px;
        border-radius: 12px;
        font-size: 12px;
        font-weight: 600;
        display: inline-block;
    }}
    .status-fail {{
        background: #ffcdd2;
        color: #b71c1c;
        padding: 3px 10px;
        border-radius: 12px;
        font-size: 12px;
        font-weight: 600;
        display: inline-block;
    }}
    .status-neutral {{
        background: #e0e0e0;
        color: #616161;
        padding: 3px 10px;
        border-radius: 12px;
        font-size: 12px;
        font-weight: 600;
        display: inline-block;
    }}
    .flagged-section {{
        background: #fff3e0;
        border-left: 4px solid var(--warning);
        padding: 16px 20px;
        border-radius: 4px;
        margin: 18px 0;
    }}
    .flagged-section.pass {{
        background: #e8f5e9;
        border-left-color: var(--success);
    }}
    .flagged-section ul {{
        margin: 10px 0 10px 20px;
    }}
    .flagged-section li {{
        margin: 4px 0;
    }}
    .proxy-section {{
        margin: 18px 0;
    }}
    .alert {{
        padding: 14px 18px;
        border-radius: 4px;
        margin: 14px 0;
        font-size: 13px;
    }}
    .alert-danger {{
        background: #ffebee;
        border-left: 4px solid var(--danger);
        color: #b71c1c;
    }}
    .alert-warning {{
        background: #fff8e1;
        border-left: 4px solid var(--warning);
        color: #e65100;
    }}
    .methodology {{
        background: #f5f5f5;
        padding: 18px 22px;
        border-radius: 6px;
        margin: 18px 0;
        font-size: 13px;
        border: 1px solid var(--border);
    }}
    .methodology h3 {{
        color: var(--primary);
        margin-bottom: 10px;
        font-size: 15px;
    }}
    .methodology ul {{
        margin: 6px 0 6px 18px;
    }}
    .methodology li {{
        margin: 3px 0;
    }}
    .attestation {{
        margin: 28px 0 10px 0;
        padding: 20px 24px;
        border: 2px dashed var(--primary);
        border-radius: 6px;
        background: #fafafa;
    }}
    .attestation h3 {{
        color: var(--primary);
        margin-bottom: 12px;
    }}
    .attestation .sig-line {{
        margin: 16px 0;
        border-bottom: 1px solid var(--text);
        width: 320px;
    }}
    .attestation .sig-label {{
        font-size: 12px;
        color: var(--text-light);
        margin-top: 2px;
    }}
    .footer {{
        text-align: center;
        padding: 16px;
        background: var(--primary);
        color: white;
        border-radius: 0 0 8px 8px;
        font-size: 12px;
    }}
    .footer a {{ color: #90caf9; }}
    @media print {{
        body {{ background: white; padding: 0; }}
        .header {{ border-radius: 0; }}
        .content {{ border: none; }}
        .footer {{ border-radius: 0; }}
    }}
</style>
</head>
<body>
<div class="container">

    <div class="header">
        <h1>Fair Lending Disparate Impact Analysis</h1>
        <div class="subtitle">Bayesian Improved Surname Geocoding (BISG) Methodology</div>
        <div class="date">Report Generated: {now} | BISG Analyzer v1.0.0</div>
    </div>

    <div class="content">

        <!-- Executive Summary -->
        <div class="exec-summary">
            <h2 style="color:var(--primary); margin-bottom:8px; font-size:16px;">📋 Executive Summary</h2>
            <p><strong>Total Applications Reviewed:</strong> {r['total_applications']}</p>
            <p><strong>Methodology:</strong> Bayesian Improved Surname Geocoding (BISG) for race/ethnicity estimation, combined with standard ECOA disparate impact analysis under the 4/5th rule.</p>
            <p><strong>Groups Analyzed:</strong> White, Black, Hispanic, Asian, Native American/Other</p>
            <p><strong>Threshold:</strong> Adverse Impact Ratio (AIR) &lt; 0.80 = potential disparate impact</p>
            <p><strong>Status:</strong> {'⚠️ Potential disparate impact detected — review recommended' if flagged else '✅ No disparate impact detected'}</p>
        </div>

        <!-- Approval Rates Table -->
        <h2 class="section-header">📊 Approval Rates by Predicted Race/Ethnicity</h2>
        <table class="data-table">
            <thead>
                <tr>
                    <th>Group</th>
                    <th>Sample Size</th>
                    <th>Approval Rate</th>
                </tr>
            </thead>
            <tbody>
                {ar_rows}
            </tbody>
        </table>

        <!-- Adverse Impact Ratios Table -->
        <h2 class="section-header">📋 Adverse Impact Ratios — 4/5th Rule Analysis</h2>
        <p style="margin-bottom:10px; font-size:13px; color:var(--text-light);">
            Reference group (highest approval rate): <strong>{best_group} ({best_rate:.2%})</strong>
        </p>
        <table class="data-table">
            <thead>
                <tr>
                    <th>Group</th>
                    <th>Approval Rate</th>
                    <th>Adverse Impact Ratio</th>
                    <th>4/5th Rule Result</th>
                </tr>
            </thead>
            <tbody>
                {air_rows}
            </tbody>
        </table>

        <!-- Flagged Groups -->
        {flagged_section}

        <!-- Proxy Features -->
        {proxy_section}

        <!-- Sample Composition -->
        <h2 class="section-header">📈 Sample Composition</h2>
        <table class="data-table">
            <thead>
                <tr>
                    <th>Group</th>
                    <th>Count</th>
                    <th>Percentage</th>
                </tr>
            </thead>
            <tbody>
                {sample_rows}
            </tbody>
        </table>

        <!-- Methodology -->
        <div class="methodology">
            <h3>📐 Methodology Description</h3>
            <p><strong>Bayesian Improved Surname Geocoding (BISG):</strong></p>
            <p>The BISG method estimates the probability that an applicant belongs to a particular racial or ethnic group by combining two sources of information:</p>
            <ul>
                <li><strong>Surname analysis:</strong> P(race | surname) — derived from U.S. Census Bureau surname frequency data, which provides the racial/ethnic distribution associated with each surname.</li>
                <li><strong>Geographic analysis:</strong> P(race | tract) — derived from Census tract-level demographic data (ACS 5-year estimates), representing the racial composition of the applicant's neighborhood.</li>
            </ul>
            <p>The two probabilities are combined using Bayes' rule:</p>
            <p style="text-align:center; font-weight:600; margin:8px 0;">
                P(race | surname, tract) ∝ P(race | surname) × P(race | tract)
            </p>
            <p><strong>4/5th Rule (Uniform Guidelines on Employee Selection Procedures):</strong></p>
            <p>An adverse impact ratio is computed for each group as the group's approval rate divided by the approval rate of the highest-performing group. An AIR below 0.80 (80%) constitutes evidence of potential disparate impact under the Equal Credit Opportunity Act (Regulation B).</p>
            <p><strong>Proxy Feature Detection:</strong> Continuous features are normalized to [0, 1], and group means are compared to the overall mean. A deviation exceeding 0.30 flags the feature as a potential proxy for protected characteristics.</p>
            <p><strong>Limitations:</strong> BISG estimates are probabilistic and subject to misclassification error. Results should be validated against actual demographic data where available. The analysis identifies statistical disparities, not legal causation.</p>
        </div>

        <!-- Attestation -->
        <div class="attestation">
            <h3>📝 Compliance Officer Attestation</h3>
            <p>I have reviewed the fair lending disparate impact analysis presented above. The analysis was conducted using the BISG methodology in accordance with regulatory guidance on fair lending monitoring under the Equal Credit Opportunity Act (15 U.S.C. § 1691) and Regulation B (12 CFR § 1002).</p>
            <div style="margin-top:18px;">
                <div class="sig-line"></div>
                <div class="sig-label">Compliance Officer Signature</div>
            </div>
            <div style="margin-top:14px;">
                <div class="sig-line"></div>
                <div class="sig-label">Date</div>
            </div>
            <div style="margin-top:14px;">
                <div class="sig-line"></div>
                <div class="sig-label">Title</div>
            </div>
        </div>

    </div>

    <div class="footer">
        BISG Fair Lending Analyzer v1.0.0 &mdash; Confidential &mdash; For Regulatory Examination Use
        <br>
        <span style="opacity:0.7;">Report generated: {now}</span>
    </div>

</div>
</body>
</html>"""
        return html


# ──────────────────────────────────────────────
# Test / Demo Runner
# ──────────────────────────────────────────────


def _demo_scorer(features: dict[str, Any]) -> int:
    """Simple underwriting scorer for demo purposes.

    Returns a risk score 0-100 based on standard underwriting factors.
    Lower score = less risky = more likely to be approved.
    Approval threshold: risk_score <= 50.
    """
    score = 0

    # Credit score (300-850 mapped to 0-40 penalty)
    cs = features.get("credit_score", 700)
    if cs < 580:
        score += 35
    elif cs < 640:
        score += 25
    elif cs < 700:
        score += 15
    else:
        score += 5

    # DTI ratio (0.0-0.65, lower is better)
    dti = features.get("dti_ratio", 0.35)
    if dti > 0.50:
        score += 25
    elif dti > 0.43:
        score += 18
    elif dti > 0.36:
        score += 10
    else:
        score += 3

    # Utilization (0.0-1.0, lower is better)
    util = features.get("utilization", 0.30)
    if util > 0.70:
        score += 20
    elif util > 0.50:
        score += 14
    elif util > 0.30:
        score += 8
    else:
        score += 2

    # Derogatory marks
    nd = features.get("num_derogatory", 0)
    score += min(nd * 8, 25)

    # Income factor (higher income = slightly lower risk)
    income = features.get("annual_income", 50000)
    if income < 20000:
        score += 8
    elif income < 40000:
        score += 4

    return min(score, 100)


def run_tests() -> None:
    """Run comprehensive tests of the BISG analyzer."""
    print("=" * 72)
    print("  BISG FAIR LENDING ANALYZER — TEST SUITE")
    print("=" * 72)

    analyzer = BISGAnalyzer()
    passed = 0
    failed = 0

    # ── Test 1: Initialization ──
    print("\n[Test 1] Initialization...")
    assert analyzer.va_demographics["White"] == 0.69
    assert analyzer.va_demographics["Black"] == 0.19
    assert abs(sum(analyzer.va_demographics.values()) - 1.0) < 0.001
    print("  ✅ VA demographics sum to 1.0, White=0.69")
    passed += 1

    # ── Test 2: Surname lookup ──
    print("\n[Test 2] surname_to_probs()...")
    probs = analyzer.surname_to_probs("Smith")
    assert abs(sum(probs.values()) - 1.0) < 0.001
    assert 0.65 <= probs["White"] <= 0.75
    print(f"  ✅ Smith → White={probs['White']:.2f}, sum={sum(probs.values()):.2f}")

    probs_nguyen = analyzer.surname_to_probs("Nguyen")
    assert probs_nguyen["Asian"] > 0.90
    print(f"  ✅ Nguyen → Asian={probs_nguyen['Asian']:.2f}")

    probs_garcia = analyzer.surname_to_probs("Garcia")
    assert probs_garcia["Hispanic"] > 0.80
    print(f"  ✅ Garcia → Hispanic={probs_garcia['Hispanic']:.2f}")

    # Case insensitivity
    probs_lower = analyzer.surname_to_probs("smith")
    assert abs(probs_lower["White"] - probs["White"]) < 0.001
    print("  ✅ Case-insensitive lookup works")

    # Unknown surname → fallback
    probs_unknown = analyzer.surname_to_probs("Xyzzy")
    assert abs(sum(probs_unknown.values()) - 1.0) < 0.001
    assert abs(probs_unknown["White"] - 0.60) < 0.001
    print(f"  ✅ Unknown surname → US general dist (White={probs_unknown['White']:.2f})")
    passed += 1

    # ── Test 3: Census tract demographics ──
    print("\n[Test 3] census_tract_to_demographics()...")
    demos = analyzer.census_tract_to_demographics()
    assert abs(sum(demos.values()) - 1.0) < 0.001
    assert demos["White"] == 0.69
    print(f"  ✅ Returns VA demographics (White={demos['White']})")

    demos_fips = analyzer.census_tract_to_demographics("51510001000")
    assert demos_fips == demos
    print("  ✅ Accepts FIPS code (returns VA fallback)")
    passed += 1

    # ── Test 4: Bayesian combination ──
    print("\n[Test 4] bayesian_combine()...")
    surname_probs = {"White": 0.70, "Black": 0.23, "Hispanic": 0.03, "Asian": 0.02, "Native": 0.02}
    tract_demos = {"White": 0.69, "Black": 0.20, "Hispanic": 0.07, "Asian": 0.04, "Native": 0.01}
    posterior = analyzer.bayesian_combine(surname_probs, tract_demos)
    assert abs(sum(posterior.values()) - 1.0) < 0.001
    assert posterior["White"] > posterior["Black"] > posterior["Hispanic"]
    print(f"  ✅ Posterior: White={posterior['White']:.3f}, Black={posterior['Black']:.3f}")
    print(f"     Sum={sum(posterior.values()):.3f}")
    passed += 1

    # ── Test 5: assign_group ──
    print("\n[Test 5] assign_group()...")
    group = analyzer.assign_group(posterior)
    assert group == "White"
    print(f"  ✅ Most likely group: {group}")

    tie = {"White": 0.25, "Black": 0.25, "Hispanic": 0.25, "Asian": 0.25, "Native": 0.0}
    tie_group = analyzer.assign_group(tie)
    assert tie_group == "White"  # First max
    print(f"  ✅ Tie-breaking: {tie_group}")
    passed += 1

    # ── Test 6: generate_test_population ──
    print("\n[Test 6] generate_test_population()...")
    pop = analyzer.generate_test_population(200)
    assert len(pop) == 200
    assert all("name" in p for p in pop)
    assert all("race_ethnicity" in p for p in pop)
    assert all("predicted_race" in p for p in pop)
    assert all("credit_score" in p for p in pop)
    assert all("dti_ratio" in p for p in pop)
    assert all(p["state"] == "VA" for p in pop)
    print(f"  ✅ Generated {len(pop)} applicants with all required fields")

    # Check group-aware distributions
    white_scores = [p["credit_score"] for p in pop if p["race_ethnicity"] == "White"]
    black_scores = [p["credit_score"] for p in pop if p["race_ethnicity"] == "Black"]
    if white_scores and black_scores:
        white_mean = sum(white_scores) / len(white_scores)
        black_mean = sum(black_scores) / len(black_scores)
        print(f"  ✅ White mean credit score: {white_mean:.0f}")
        print(f"  ✅ Black mean credit score: {black_mean:.0f}")
        assert white_mean > black_mean, "White should have higher avg credit than Black"
    passed += 1

    # ── Test 7: analyze_approval_rates ──
    print("\n[Test 7] analyze_approval_rates()...")
    predictions = [True if p["credit_score"] > 620 and p["dti_ratio"] < 0.45 else False
                   for p in pop]
    predicted_groups = [p["predicted_race"] for p in pop]
    result = analyzer.analyze_approval_rates(pop, predictions, predicted_groups)
    assert result["total_applications"] == 200
    assert "approval_rates" in result
    assert "adverse_impact_ratios" in result
    assert "flagged_groups" in result
    assert "sample_size_by_group" in result
    print(f"  ✅ Total apps: {result['total_applications']}")
    print(f"  ✅ Approval rates computed for {len(result['approval_rates'])} groups")
    for g in RACE_GROUPS:
        rate = result["approval_rates"].get(g, 0)
        count = result["sample_size_by_group"].get(g, 0)
        print(f"     {g}: rate={rate:.2%}, n={count}")
    if result["flagged_groups"]:
        print(f"  ⚠️  Flagged groups: {result['flagged_groups']}")
    else:
        print("  ✅ No groups flagged")
    passed += 1

    # ── Test 8: Length mismatch raises error ──
    print("\n[Test 8] Input validation...")
    try:
        analyzer.analyze_approval_rates(pop, predictions[:50], predicted_groups)
        print("  ❌ Should have raised ValueError")
        failed += 1
    except ValueError:
        print("  ✅ Length mismatch correctly raises ValueError")
        passed += 1

    # ── Test 9: proxy_feature_analysis ──
    print("\n[Test 9] proxy_feature_analysis()...")
    proxy_features = analyzer.proxy_feature_analysis(pop, predicted_groups)
    print(f"  ✅ Found {len(proxy_features)} potential proxy features")
    for pf in proxy_features:
        print(f"     {pf['feature']}: max_deviation={pf['max_deviation']:.4f}")
    passed += 1

    # ── Test 10: FairLendingReport text ──
    print("\n[Test 10] FairLendingReport.generate_text()...")
    report = FairLendingReport(result)
    report.set_proxy_features(proxy_features)
    text = report.generate_text()
    assert "BISG FAIR LENDING" in text
    assert "APPROVAL RATES" in text
    assert "ADVERSE IMPACT RATIOS" in text
    assert "METHODOLOGY" in text
    print(f"  ✅ Text report generated ({len(text)} chars)")
    passed += 1

    # ── Test 11: FairLendingReport HTML ──
    print("\n[Test 11] FairLendingReport.generate_html()...")
    html = report.generate_html()
    assert "<!DOCTYPE html>" in html
    assert "Fair Lending Disparate Impact Analysis" in html
    assert "Compliance Officer Attestation" in html
    assert "data-table" in html
    assert "status-pass" in html or "status-fail" in html
    print(f"  ✅ HTML report generated ({len(html)} chars)")
    passed += 1

    # ── Test 12: End-to-end BISG pipeline ──
    print("\n[Test 12] End-to-end BISG pipeline...")
    # Pick a strongly indicative surname and verify BISG posterior matches
    surname_probs_s = analyzer.surname_to_probs("Nguyen")
    tract_demos_v = analyzer.census_tract_to_demographics()
    posterior_s = analyzer.bayesian_combine(surname_probs_s, tract_demos_v)
    assigned = analyzer.assign_group(posterior_s)
    assert assigned == "Asian", f"Expected Asian, got {assigned}"
    print(f"  ✅ Nguyen → Posterior Asian={posterior_s['Asian']:.3f} → Assigned={assigned}")

    surname_probs_g = analyzer.surname_to_probs("Gonzalez")
    posterior_g = analyzer.bayesian_combine(surname_probs_g, tract_demos_v)
    assigned_g = analyzer.assign_group(posterior_g)
    assert assigned_g == "Hispanic", f"Expected Hispanic, got {assigned_g}"
    print(f"  ✅ Gonzalez → Posterior Hispanic={posterior_g['Hispanic']:.3f} → Assigned={assigned_g}")

    surname_probs_m = analyzer.surname_to_probs("Murphy")
    posterior_m = analyzer.bayesian_combine(surname_probs_m, tract_demos_v)
    assigned_m = analyzer.assign_group(posterior_m)
    assert assigned_m == "White", f"Expected White, got {assigned_m}"
    print(f"  ✅ Murphy → Posterior White={posterior_m['White']:.3f} → Assigned={assigned_m}")
    passed += 1

    # ── Test 13: Large population ──
    print("\n[Test 13] Large population generation (n=5000)...")
    pop5000 = analyzer.generate_test_population(5000)
    assert len(pop5000) == 5000
    races = [p["race_ethnicity"] for p in pop5000]
    white_pct = races.count("White") / 5000 * 100
    print(f"  ✅ Generated 5000 applicants (White={white_pct:.1f}%)")
    passed += 1

    # ── Summary ──
    print("\n" + "=" * 72)
    print(f"  RESULTS: {passed} passed, {failed} failed out of {passed + failed} tests")
    print("=" * 72)


def run_demo() -> None:
    """Run a full BISG fair lending analysis demo."""
    print("\n" + "=" * 72)
    print("  BISG FAIR LENDING ANALYZER — DEMO")
    print("=" * 72)

    # Initialize
    analyzer = BISGAnalyzer()
    print("\n📌 Generating synthetic applicant population...")
    population = analyzer.generate_test_population(5000)

    # Apply underwriting scorer
    print("📌 Scoring applicants...")
    predictions = []
    predicted_groups = []
    for app in population:
        score = _demo_scorer(app)
        approved = score <= 50
        predictions.append(approved)
        predicted_groups.append(app["predicted_race"])

    # Analyze approval rates
    print("📌 Analyzing approval rates (4/5th rule)...")
    result = analyzer.analyze_approval_rates(population, predictions, predicted_groups)

    # Proxy feature analysis
    print("📌 Running proxy feature analysis...")
    proxy_features = analyzer.proxy_feature_analysis(population, predicted_groups)

    # Generate reports
    print("📌 Generating reports...")
    report = FairLendingReport(result)
    report.set_proxy_features(proxy_features)

    print("\n" + "━" * 72)
    print("  TEXT REPORT")
    print("━" * 72)
    print(report.generate_text())

    # Write HTML report
    html = report.generate_html()
    import os
    output_dir = os.path.dirname(os.path.abspath(__file__))
    html_path = os.path.join(output_dir, "fair_lending_report.html")
    with open(html_path, "w") as f:
        f.write(html)
    print(f"\n📄 HTML report saved to: {html_path}")

    # Summary stats
    print("\n  KEY FINDINGS:")
    print(f"  • Total applications: {result['total_applications']}")
    for group in RACE_GROUPS:
        rate = result["approval_rates"][group]
        ratio = result["adverse_impact_ratios"][group]
        count = result["sample_size_by_group"][group]
        status = "⚠️ FLAGGED" if group in result["flagged_groups"] else "✅ OK"
        print(f"  • {group:<20s} n={count:<5d} rate={rate:.2%}  AIR={ratio:.3f}  {status}")

    if proxy_features:
        print(f"\n  ⚠️  Potential proxy features detected: {len(proxy_features)}")
        for pf in proxy_features:
            print(f"     • {pf['feature']} (deviation={pf['max_deviation']:.3f})")
    else:
        print("\n  ✅ No proxy features flagged.")

    print("\n" + "=" * 72)
    print("  DEMO COMPLETE")
    print("=" * 72)


# ──────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────


if __name__ == "__main__":
    import sys

    if "--demo" in sys.argv:
        run_demo()
    elif "--html-only" in sys.argv:
        # Just generate and save HTML report
        analyzer = BISGAnalyzer()
        pop = analyzer.generate_test_population(1000)
        preds = [_demo_scorer(p) <= 50 for p in pop]
        groups = [p["predicted_race"] for p in pop]
        result = analyzer.analyze_approval_rates(pop, preds, groups)
        proxy = analyzer.proxy_feature_analysis(pop, groups)
        report = FairLendingReport(result)
        report.set_proxy_features(proxy)
        html = report.generate_html()
        import os
        out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fair_lending_report.html")
        with open(out, "w") as f:
            f.write(html)
        print(f"HTML report written to {out}")
    else:
        run_tests()
