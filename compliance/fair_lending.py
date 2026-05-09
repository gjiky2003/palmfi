#!/usr/bin/env python3
"""Fair lending disparate impact analysis tool.

Provides the FairLendingAnalyzer class for evaluating whether an underwriting
model produces disparate impact across protected attribute groups under the
Equal Credit Opportunity Act (Reg B) and the 4/5th rule.
"""

from __future__ import annotations

import random
from collections import defaultdict
from typing import Any, Callable

import numpy as np


class FairLendingAnalyzer:
    """Analyze an underwriting scorer for fair lending disparate impact.

    Generates synthetic applicant populations with known protected attributes
    and analyzes approval rate disparities. Uses the 4/5th rule (adverse impact
    ratio < 0.80) to flag potential disparate impact.

    Args:
        scorer_fn: A callable that accepts a features dict and returns a
            risk_score (int, 0-100, higher = riskier). The scorer may also
            return a dict with a "risk_score" key.
    """

    # Protected attribute categories
    RACE_ETHNICITY = ["white", "black", "hispanic", "asian", "other"]
    GENDER = ["male", "female"]
    AGE_BRACKETS = ["under_25", "25_40", "40_62", "over_62"]

    # Feature ranges for realistic synthetic data (based on US consumer data)
    _FEATURE_RANGES = {
        "credit_score": {
            "white": {"mean": 730, "std": 60, "min": 300, "max": 850},
            "black": {"mean": 670, "std": 70, "min": 300, "max": 850},
            "hispanic": {"mean": 695, "std": 65, "min": 300, "max": 850},
            "asian": {"mean": 740, "std": 55, "min": 300, "max": 850},
            "other": {"mean": 700, "std": 65, "min": 300, "max": 850},
        },
        "annual_income": {
            "white": {"mean": 75000, "std": 35000, "min": 10000, "max": 300000},
            "black": {"mean": 55000, "std": 28000, "min": 8000, "max": 250000},
            "hispanic": {"mean": 58000, "std": 28000, "min": 8000, "max": 280000},
            "asian": {"mean": 85000, "std": 40000, "min": 10000, "max": 350000},
            "other": {"mean": 65000, "std": 32000, "min": 8000, "max": 300000},
        },
        "dti_ratio": {
            "white": {"mean": 0.30, "std": 0.12, "min": 0.0, "max": 0.60},
            "black": {"mean": 0.38, "std": 0.13, "min": 0.0, "max": 0.65},
            "hispanic": {"mean": 0.35, "std": 0.13, "min": 0.0, "max": 0.65},
            "asian": {"mean": 0.28, "std": 0.11, "min": 0.0, "max": 0.60},
            "other": {"mean": 0.32, "std": 0.12, "min": 0.0, "max": 0.60},
        },
        "utilization": {
            "white": {"mean": 0.30, "std": 0.22, "min": 0.0, "max": 1.0},
            "black": {"mean": 0.45, "std": 0.28, "min": 0.0, "max": 1.0},
            "hispanic": {"mean": 0.38, "std": 0.25, "min": 0.0, "max": 1.0},
            "asian": {"mean": 0.28, "std": 0.20, "min": 0.0, "max": 1.0},
            "other": {"mean": 0.33, "std": 0.23, "min": 0.0, "max": 1.0},
        },
        "num_derogatory": {
            "white": {"mean": 0.4, "std": 0.8, "min": 0, "max": 10},
            "black": {"mean": 1.2, "std": 1.5, "min": 0, "max": 12},
            "hispanic": {"mean": 0.8, "std": 1.2, "min": 0, "max": 10},
            "asian": {"mean": 0.3, "std": 0.6, "min": 0, "max": 8},
            "other": {"mean": 0.5, "std": 0.9, "min": 0, "max": 10},
        },
        "num_credit_lines": {
            "white": {"mean": 8, "std": 4, "min": 0, "max": 30},
            "black": {"mean": 6, "std": 4, "min": 0, "max": 25},
            "hispanic": {"mean": 6, "std": 3.5, "min": 0, "max": 25},
            "asian": {"mean": 7, "std": 4, "min": 0, "max": 30},
            "other": {"mean": 7, "std": 4, "min": 0, "max": 28},
        },
        "employment_length": {
            "under_25": {"mean": 1.5, "std": 1.2, "min": 0, "max": 8},
            "25_40": {"mean": 6, "std": 4, "min": 0, "max": 20},
            "40_62": {"mean": 12, "std": 7, "min": 0, "max": 40},
            "over_62": {"mean": 15, "std": 10, "min": 0, "max": 50},
        },
    }

    def __init__(self, scorer_fn: Callable):
        self.scorer_fn = scorer_fn
        self.population: list[dict] = []
        self.results: list[dict] = []
        self.approval_rates: dict[str, dict[str, float]] = {}
        self.adverse_impact_ratios: dict[str, dict[str, float]] = {}
        self.proxy_correlations: dict[str, dict[str, float]] = {}
        self._rng: random.Random | None = None

    def _clamp(self, value: float, lo: float, hi: float) -> float:
        return max(lo, min(hi, value))

    def _gaussian_clamp(
        self, mean: float, std: float, lo: float, hi: float, rng: random.Random
    ) -> float:
        val = rng.gauss(mean, std)
        return self._clamp(val, lo, hi)

    def generate_synthetic_population(
        self, n: int = 1000, seed: int = 42
    ) -> list[dict]:
        """Generate a diverse synthetic applicant population.

        Creates applicants with known protected attributes and realistic
        feature distributions drawn from US consumer finance data patterns.

        Args:
            n: Number of synthetic applicants to generate.
            seed: Random seed for reproducibility.

        Returns:
            List of applicant feature dicts with protected attributes.
        """
        rng = random.Random(seed)
        self._rng = rng
        np.random.seed(seed)

        self.population = []
        race_weights = [0.60, 0.12, 0.18, 0.06, 0.04]  # US population approx

        for _ in range(n):
            # Assign protected attributes
            race = rng.choices(self.RACE_ETHNICITY, weights=race_weights)[0]
            gender = rng.choice(self.GENDER)
            age_bracket = rng.choice(self.AGE_BRACKETS)

            # Generate features based on distributions
            cr = self._FEATURE_RANGES["credit_score"][race]
            credit_score = int(
                round(self._gaussian_clamp(cr["mean"], cr["std"], cr["min"], cr["max"], rng))
            )

            ai = self._FEATURE_RANGES["annual_income"][race]
            annual_income = int(
                round(self._gaussian_clamp(ai["mean"], ai["std"], ai["min"], ai["max"], rng))
            )

            dr = self._FEATURE_RANGES["dti_ratio"][race]
            dti_ratio = round(
                self._gaussian_clamp(dr["mean"], dr["std"], dr["min"], dr["max"], rng), 3
            )

            ul = self._FEATURE_RANGES["utilization"][race]
            utilization = round(
                self._gaussian_clamp(ul["mean"], ul["std"], ul["min"], ul["max"], rng), 3
            )

            nd = self._FEATURE_RANGES["num_derogatory"][race]
            num_derogatory = int(
                round(self._gaussian_clamp(nd["mean"], nd["std"], nd["min"], nd["max"], rng))
            )

            nc = self._FEATURE_RANGES["num_credit_lines"][race]
            num_credit_lines = int(
                round(self._gaussian_clamp(nc["mean"], nc["std"], nc["min"], nc["max"], rng))
            )

            el = self._FEATURE_RANGES["employment_length"][age_bracket]
            employment_length = int(
                round(self._gaussian_clamp(el["mean"], el["std"], el["min"], el["max"], rng))
            )

            # Age derived from bracket
            age_map = {
                "under_25": (20, 24),
                "25_40": (25, 40),
                "40_62": (41, 61),
                "over_62": (62, 75),
            }
            age_lo, age_hi = age_map[age_bracket]
            age = rng.randint(age_lo, age_hi)

            # Home ownership correlated with age and income
            home_weights = {
                "under_25": {"rent": 0.75, "mortgage": 0.15, "own": 0.10},
                "25_40": {"rent": 0.40, "mortgage": 0.45, "own": 0.15},
                "40_62": {"rent": 0.20, "mortgage": 0.45, "own": 0.35},
                "over_62": {"rent": 0.15, "mortgage": 0.30, "own": 0.55},
            }
            hw = home_weights[age_bracket]
            home_ownership = rng.choices(
                ["rent", "mortgage", "own"], weights=[hw["rent"], hw["mortgage"], hw["own"]]
            )[0]

            # Loan amount correlated with income
            loan_amount = int(
                round(
                    self._clamp(
                        rng.gauss(annual_income * 0.15, 5000),
                        500,
                        50000,
                    )
                )
            )

            # Term months
            term_months = rng.choice([12, 24, 36, 48, 60])

            # Loan purpose
            loan_purpose = rng.choice(
                ["personal", "debt_consolidation", "medical", "auto", "business", "education"]
            )

            person: dict[str, Any] = {
                # Protected attributes
                "race_ethnicity": race,
                "gender": gender,
                "age_bracket": age_bracket,
                # Features
                "age": age,
                "credit_score": credit_score,
                "annual_income": annual_income,
                "dti_ratio": dti_ratio,
                "utilization": utilization,
                "num_derogatory": num_derogatory,
                "num_credit_lines": num_credit_lines,
                "employment_length": employment_length,
                "home_ownership": home_ownership,
                "loan_amount": loan_amount,
                "term_months": term_months,
                "loan_purpose": loan_purpose,
            }

            self.population.append(person)

        return self.population

    def run_analysis(self) -> dict[str, dict[str, float]]:
        """Score every synthetic applicant and compute approval rates by group.

        Uses the scorer function to evaluate each applicant. An applicant is
        considered approved if the risk_score (from scorer) is <= 75, matching
        the production approval threshold.

        Returns:
            Dict mapping protected attribute dimension to {group: approval_rate}.
        """
        if not self.population:
            raise ValueError(
                "No population generated. Call generate_synthetic_population() first."
            )

        self.results = []

        for person in self.population:
            # Build features dict for scorer (strip protected attributes)
            feature_dict = {
                "age": person["age"],
                "annual_income": person["annual_income"],
                "employment_length": person["employment_length"],
                "credit_score": person["credit_score"],
                "dti_ratio": person["dti_ratio"],
                "utilization": person["utilization"],
                "num_derogatory": person["num_derogatory"],
                "num_credit_lines": person["num_credit_lines"],
                "home_ownership": person["home_ownership"],
                "loan_amount": person["loan_amount"],
                "term_months": person["term_months"],
                "loan_purpose": person["loan_purpose"],
            }

            try:
                score_result = self.scorer_fn(feature_dict)
                if isinstance(score_result, dict):
                    risk_score = score_result.get("risk_score", 50)
                    approved = score_result.get("approved", risk_score <= 75)
                else:
                    risk_score = int(score_result)
                    approved = risk_score <= 75
            except Exception as e:
                # If scorer fails, mark as not approved
                risk_score = 100
                approved = False

            self.results.append(
                {
                    **person,
                    "risk_score": risk_score,
                    "approved": approved,
                }
            )

        # Compute approval rates by each protected attribute
        self.approval_rates = {}
        for dim in ["race_ethnicity", "gender", "age_bracket"]:
            groups: dict[str, list[bool]] = defaultdict(list)
            for r in self.results:
                groups[r[dim]].append(r["approved"])
            rates: dict[str, float] = {}
            for group, approvals in groups.items():
                rates[group] = sum(approvals) / len(approvals) if approvals else 0.0
            self.approval_rates[dim] = rates

        return self.approval_rates

    def adverse_impact_ratio(self) -> dict[str, dict[str, float]]:
        """Compute adverse impact ratios for each protected group.

        The adverse impact ratio is the group's approval rate divided by the
        approval rate of the highest-approval group in that dimension.
        Under the 4/5th rule (Uniform Guidelines on Employee Selection
        Procedures), a ratio < 0.80 flags potential disparate impact.

        Returns:
            Dict mapping dimension to {group: adverse_impact_ratio}.
        """
        if not self.approval_rates:
            self.run_analysis()

        self.adverse_impact_ratios = {}
        for dim, rates in self.approval_rates.items():
            if not rates:
                continue
            best_rate = max(rates.values())
            ratios: dict[str, float] = {}
            for group, rate in rates.items():
                ratios[group] = round(rate / best_rate, 4) if best_rate > 0 else 0.0
            self.adverse_impact_ratios[dim] = ratios

        return self.adverse_impact_ratios

    def proxy_feature_analysis(self) -> dict[str, dict[str, float]]:
        """Check which model features correlate with protected attributes.

        For continuous features, reports the mean value by protected group.
        A large spread between groups may indicate proxy discrimination risk.

        Returns:
            Dict mapping feature name to {group: mean_value}.
        """
        if not self.results:
            self.run_analysis()

        continuous_features = [
            "credit_score",
            "annual_income",
            "dti_ratio",
            "utilization",
            "num_derogatory",
            "num_credit_lines",
            "employment_length",
            "loan_amount",
        ]

        self.proxy_correlations = {}

        for feat in continuous_features:
            # Compute mean by race_ethnicity
            by_race: dict[str, list[float]] = defaultdict(list)
            for r in self.results:
                by_race[r["race_ethnicity"]].append(r[feat])
            race_means: dict[str, float] = {}
            for group, vals in by_race.items():
                race_means[group] = round(sum(vals) / len(vals), 2) if vals else 0.0

            # Compute mean by age_bracket
            by_age: dict[str, list[float]] = defaultdict(list)
            for r in self.results:
                by_age[r["age_bracket"]].append(r[feat])
            age_means: dict[str, float] = {}
            for group, vals in by_age.items():
                age_means[group] = round(sum(vals) / len(vals), 2) if vals else 0.0

            # Compute mean by gender
            by_gender: dict[str, list[float]] = defaultdict(list)
            for r in self.results:
                by_gender[r["gender"]].append(r[feat])
            gender_means: dict[str, float] = {}
            for group, vals in by_gender.items():
                gender_means[group] = round(sum(vals) / len(vals), 2) if vals else 0.0

            self.proxy_correlations[feat] = {
                "by_race": race_means,
                "by_age": age_means,
                "by_gender": gender_means,
            }

        return self.proxy_correlations

    def generate_report(self, format: str = "text") -> str:
        """Generate a formatted fair lending analysis report.

        Args:
            format: Output format ('text' for human-readable report).

        Returns:
            Formatted report string.
        """
        if not self.adverse_impact_ratios:
            self.adverse_impact_ratio()

        if not self.proxy_correlations:
            self.proxy_feature_analysis()

        lines: list[str] = []
        _sep = "─" * 72

        lines.append("")
        lines.append(f"  {'PALMFI FAIR LENDING ANALYSIS REPORT':^70s}")
        lines.append(f"  {'Equal Credit Opportunity Act — Disparate Impact Screening':^70s}")
        lines.append(_sep)
        lines.append(f"  Population size: {len(self.population)}")
        if self._rng is not None:
            lines.append(f"  Random seed:     {self._rng.seed if hasattr(self._rng, 'seed') else 'N/A'}")
        lines.append("")

        # ── Approval Rates by Protected Attribute ──
        lines.append("  📊 APPROVAL RATES BY PROTECTED ATTRIBUTE")
        lines.append(_sep)

        for dim, rates in self.approval_rates.items():
            dim_label = dim.replace("_", " ").title()
            lines.append(f"")
            lines.append(f"  {dim_label}:")
            for group, rate in sorted(rates.items()):
                lines.append(f"    {group:<20s}  {rate:>6.1%}")

        lines.append("")
        lines.append("  📋 ADVERSE IMPACT RATIOS (4/5th Rule)")
        lines.append(_sep)

        flagged_groups: list[str] = []

        for dim, ratios in self.adverse_impact_ratios.items():
            dim_label = dim.replace("_", " ").title()
            best_group = max(
                self.approval_rates[dim], key=lambda g: self.approval_rates[dim][g]
            )
            lines.append(f"")
            lines.append(f"  {dim_label} (highest: {best_group} @ {self.approval_rates[dim][best_group]:.1%}):")
            for group, ratio in sorted(ratios.items()):
                flag = " ⚠️  FLAGGED" if ratio < 0.80 else ""
                if ratio < 0.80:
                    flagged_groups.append(f"{dim}={group} (ratio={ratio:.3f})")
                lines.append(f"    {group:<20s}  ratio={ratio:.3f}{flag}")

        if flagged_groups:
            lines.append("")
            lines.append("  ❗ POTENTIAL DISPARATE IMPACT DETECTED")
            lines.append(f"  The following groups fall below the 4/5th threshold (ratio < 0.80):")
            for fg in flagged_groups:
                lines.append(f"    ⚠️  {fg}")
        else:
            lines.append("")
            lines.append("  ✅ No groups fall below the 4/5th rule threshold (ratio >= 0.80 for all).")

        # ── Proxy Feature Analysis ──
        lines.append("")
        lines.append("  🔍 PROXY FEATURE CORRELATION ANALYSIS")
        lines.append(_sep)
        lines.append("  Mean feature values by protected group:")
        lines.append("")

        for feat, corr in self.proxy_correlations.items():
            feat_label = feat.replace("_", " ").title()
            lines.append(f"  {feat_label}:")

            # By race
            race_vals = corr["by_race"]
            race_max = max(race_vals.values()) if race_vals else 0
            race_min = min(race_vals.values()) if race_vals else 0
            race_spread = race_max - race_min
            lines.append(
                f"    By Race/Ethnicity:  max={race_max:.1f}  min={race_min:.1f}  "
                f"spread={race_spread:.1f}"
            )

            # By age
            age_vals = corr["by_age"]
            age_max = max(age_vals.values()) if age_vals else 0
            age_min = min(age_vals.values()) if age_vals else 0
            age_spread = age_max - age_min
            lines.append(
                f"    By Age Bracket:     max={age_max:.1f}  min={age_min:.1f}  "
                f"spread={age_spread:.1f}"
            )

            # By gender
            gender_vals = corr["by_gender"]
            gender_max = max(gender_vals.values()) if gender_vals else 0
            gender_min = min(gender_vals.values()) if gender_vals else 0
            gender_spread = gender_max - gender_min
            lines.append(
                f"    By Gender:          max={gender_max:.1f}  min={gender_min:.1f}  "
                f"spread={gender_spread:.1f}"
            )

            # Proxy risk assessment
            pct_spread_race = (race_spread / max(1, race_max)) * 100
            proxy_risk = "HIGH" if pct_spread_race > 30 else "MODERATE" if pct_spread_race > 15 else "LOW"
            lines.append(f"    Proxy Risk (Race):  {proxy_risk}  (spread={race_spread:.1f}, {pct_spread_race:.1f}%)")
            lines.append("")

        # ── Recommendations ──
        lines.append("  📌 RECOMMENDATIONS")
        lines.append(_sep)

        if flagged_groups:
            lines.append("  IMMEDIATE ACTIONS:")
            lines.append("  • Review underwriting model for potential bias against flagged groups.")
            lines.append("  • Conduct a deeper statistical analysis with actual applicant data.")
            lines.append("  • Consider alternative model architectures or feature engineering.")
            lines.append("  • Engage fair lending counsel for legal review of the findings.")
            lines.append("")

        lines.append("  ONGOING MONITORING:")
        lines.append("  • Run this analysis monthly on new applicant data.")
        lines.append("  • Track adverse impact ratios over time for trend analysis.")
        lines.append("  • Review feature importance to ensure no proxy features dominate decisions.")
        lines.append("  • Document all fair lending analyses for regulatory examination readiness.")
        lines.append("")
        lines.append("  MODEL GOVERNANCE:")
        lines.append("  • Include fair lending results in model validation reports.")
        lines.append("  • Establish a threshold for model retraining based on adverse impact.")
        lines.append("  • Maintain version history of all fair lending analyses.")
        lines.append("")
        lines.append(_sep)
        lines.append(f"  Report generated: {__import__('datetime').datetime.now().isoformat()}")
        lines.append("")

        return "\n".join(lines)
