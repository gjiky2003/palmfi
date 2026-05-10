#!/usr/bin/env python3
"""LLM Document Extraction Pipeline for Self-Employed Applicant Documents.

Uses DeepSeek API (or mock mode for development) to extract structured cash flow
features from unstructured applicant documents including:

  - Bank statements (PDF text)
  - Schedule C (tax form text)
  - 1099 forms
  - Gig platform earnings reports (Uber, DoorDash, Upwork, etc.)

Two modes:
  MOCK mode — generates realistic mock extraction results for development/testing
  REAL mode — calls DeepSeek API (structure ready, API key needed for activation)

Output schema feeds into the underwriting scoring pipeline via get_score_boost()
to adjust rates for self-employed borrowers with strong cash flow documentation.
"""

from __future__ import annotations

import json
import math
import os
import random
from copy import deepcopy
from datetime import datetime, timedelta
from typing import Any

import numpy as np

# ── Constants ────────────────────────────────────────────────────────────────

# Self-employed occupation profiles with realistic financial characteristics
SE_PROFILES: dict[str, dict[str, Any]] = {
    "photographer": {
        "label": "Wedding/Portrait Photographer",
        "typical_annual_income_range": (35000, 95000),
        "income_volatility_range": (0.18, 0.40),
        "business_expense_ratio_range": (0.25, 0.50),
        "doc_types": ["bank_statement", "schedule_c", "contract_invoices"],
        "income_trend": "growing",
        "employer_tenure_months_range": (12, 84),
        "gig_platform_count": 2,
        "typical_anomalies": ["large_equipment_purchase", "seasonal_gap"],
    },
    "rideshare_driver": {
        "label": "Rideshare Driver (Uber/Lyft)",
        "typical_annual_income_range": (25000, 65000),
        "income_volatility_range": (0.15, 0.55),
        "business_expense_ratio_range": (0.20, 0.35),
        "doc_types": ["bank_statement", "1099_misc", "platform_summary"],
        "income_trend": "stable",
        "employer_tenure_months_range": (6, 60),
        "gig_platform_count": 2,
        "typical_anomalies": ["fuel_spike", "vehicle_maintenance_lump"],
    },
    "freelance_developer": {
        "label": "Freelance Software Developer",
        "typical_annual_income_range": (80000, 180000),
        "income_volatility_range": (0.20, 0.45),
        "business_expense_ratio_range": (0.05, 0.20),
        "doc_types": ["bank_statement", "schedule_c", "1099_misc", "invoice_summary"],
        "income_trend": "growing",
        "employer_tenure_months_range": (12, 120),
        "gig_platform_count": 3,
        "typical_anomalies": ["lumpy_payment", "month_with_zero_income"],
    },
    "contractor": {
        "label": "General Contractor / Trades",
        "typical_annual_income_range": (45000, 130000),
        "income_volatility_range": (0.22, 0.50),
        "business_expense_ratio_range": (0.30, 0.55),
        "doc_types": ["bank_statement", "schedule_c", "1099_misc"],
        "income_trend": "stable",
        "employer_tenure_months_range": (24, 180),
        "gig_platform_count": 1,
        "typical_anomalies": ["material_cost_spike", "seasonal_winter_dip"],
    },
}

# Prompt templates for different document types
PROMPT_TEMPLATES: dict[str, str] = {
    "bank_statement": """
You are a financial document analyzer for a lending underwriting system.
Extract cash flow features from this bank statement PDF text.

INSTRUCTIONS:
- Identify all deposits that appear to be income (recurring, from employers/clients/gig platforms)
- Calculate monthly income for each of the last 6-12 months
- Note any large deposits or withdrawals that appear unusual
- Flag any NSF (non-sufficient funds) events or overdrafts
- Identify expense patterns (business vs personal)
- Calculate the total deposits vs total income ratio

OUTPUT FORMAT (JSON):
{
    "monthly_income": [amount, amount, ...],
    "total_deposits_12mo": number,
    "expected_income_12mo": number,
    "stated_vs_deposit_ratio": float,
    "nsf_count": int,
    "overdraft_count": int,
    "large_unusual_deposits": [{"amount": number, "note": "description"}],
    "large_unusual_withdrawals": [{"amount": number, "note": "description"}],
    "business_expenses_reported": number,
    "personal_expenses_estimated": number,
    "income_sources_identified": ["source1", "source2"],
    "anomaly_flags": ["description"],
    "doc_quality_issues": ["issue"]
}

TEXT:
{document_text}
""",
    "schedule_c": """
You are a tax document analyzer for a lending underwriting system.
Extract financial features from this Schedule C (Form 1040) text.

INSTRUCTIONS:
- Identify gross revenue (Part I, Line 1 or 7)
- Identify total expenses (Part II, sum of expenses or line 28)
- Calculate net profit (line 31)
- Identify cost of goods sold if applicable (Part III)
- Note business code, principal business description
- Check if the business has inventory
- Flag any unusual deductions or patterns

OUTPUT FORMAT (JSON):
{
    "gross_revenue": number,
    "total_expenses": number,
    "net_profit": number,
    "cost_of_goods_sold": number | null,
    "business_code": string,
    "business_description": string,
    "has_inventory": bool,
    "vehicle_expenses": number | null,
    "home_office_deduction": number | null,
    "depreciation": number | null,
    "insurance": number | null,
    "tax_year": string,
    "anomaly_flags": ["description"],
    "expense_breakdown": {"category": amount},
    "doc_quality_issues": ["issue"]
}

TEXT:
{document_text}
""",
    "1099_form": """
You are a document analyzer for a lending underwriting system.
Extract compensation data from this 1099-NEC or 1099-MISC form text.

INSTRUCTIONS:
- Identify the payer name and payer EIN
- Extract nonemployee compensation (Box 1 for NEC, Box 7 for MISC)
- Note any federal income tax withheld (Box 4)
- Identify the tax year
- Flag if this is multiple 1099s combined

OUTPUT FORMAT (JSON):
{
    "payer_name": string,
    "payer_ein": string,
    "nonemployee_compensation": number,
    "federal_tax_withheld": number | null,
    "tax_year": string,
    "form_type": "1099-NEC" | "1099-MISC",
    "is_combined_document": bool,
    "anomaly_flags": ["description"],
    "doc_quality_issues": ["issue"]
}

TEXT:
{document_text}
""",
    "gig_platform_report": """
You are a document analyzer for a lending underwriting system.
Extract earnings data from a gig platform earnings report.

Platforms include: Uber, Lyft, DoorDash, Grubhub, Instacart, Upwork, Fiverr, etc.

INSTRUCTIONS:
- Identify the platform name
- Extract total earnings for the period
- Extract number of trips/gigs/projects completed
- Identify active months/weeks (period with activity)
- Extract any bonuses or incentives
- Calculate average per-trip/project earnings
- Identify any platform fees or commissions

OUTPUT FORMAT (JSON):
{
    "platform_name": string,
    "period_start": string,
    "period_end": string,
    "total_earnings": number,
    "num_transactions": number,
    "active_days": number,
    "avg_per_transaction": number,
    "bonuses_incentives": number | null,
    "platform_fees": number | null,
    "anomaly_flags": ["description"],
    "doc_quality_issues": ["issue"]
}

TEXT:
{document_text}
""",
}

# ── Anomaly Detection Reference ─────────────────────────────────────────────

ANOMALY_CATALOG: dict[str, dict[str, Any]] = {
    "income_decline": {
        "label": "Declining income trend",
        "severity": "high",
        "impact": -5.0,
        "flag": "declining_income_trend",
    },
    "income_volatility_high": {
        "label": "High income volatility (CV > 0.50)",
        "severity": "medium",
        "impact": -3.0,
        "flag": "high_income_volatility",
    },
    "nsf_overdraft": {
        "label": "NSF or overdraft events on bank statements",
        "severity": "high",
        "impact": -5.0,
        "flag": "nsf_overdraft_events",
    },
    "stated_deposit_mismatch": {
        "label": "Stated income > 130% of bank deposits",
        "severity": "high",
        "impact": -6.0,
        "flag": "stated_income_exceeds_deposits",
    },
    "large_unusual_deposit": {
        "label": "Large unusual deposits (>50% of monthly income)",
        "severity": "medium",
        "impact": -2.0,
        "flag": "large_unusual_deposit",
    },
    "expense_ratio_high": {
        "label": "Expense ratio > 60% suggests low profitability",
        "severity": "medium",
        "impact": -3.0,
        "flag": "high_expense_ratio",
    },
    "short_tenure": {
        "label": "Self-employment tenure < 12 months",
        "severity": "high",
        "impact": -5.0,
        "flag": "short_self_employed_tenure",
    },
    "zero_income_month": {
        "label": "Months with zero income reported",
        "severity": "medium",
        "impact": -2.0,
        "flag": "zero_income_months",
    },
    "doc_quality_low": {
        "label": "Document quality score < 0.5 (illegible/incomplete)",
        "severity": "high",
        "impact": -4.0,
        "flag": "poor_document_quality",
    },
    "missing_schedule_c": {
        "label": "Self-employed applicant without Schedule C for 2+ years",
        "severity": "medium",
        "impact": -3.0,
        "flag": "missing_schedule_c",
    },
    "gap_in_employment": {
        "label": "Gap in self-employment income > 90 days",
        "severity": "medium",
        "impact": -3.0,
        "flag": "employment_gap",
    },
    "inconsistent_platforms": {
        "label": "Multiple gig platforms with declining earnings on each",
        "severity": "low",
        "impact": -1.5,
        "flag": "declining_multi_platform",
    },
}

# ── Utility Functions ────────────────────────────────────────────────────────


def _cv(values: list[float]) -> float:
    """Coefficient of variation (std/mean)."""
    if not values or sum(values) == 0:
        return 0.0
    arr = np.array(values)
    return float(np.std(arr, ddof=1) / np.mean(arr)) if np.mean(arr) > 0 else 0.0


def _trend_label(values: list[float]) -> str:
    """Classify income trend as stable/growing/declining/erratic."""
    if len(values) < 3:
        return "stable"

    # Linear regression slope
    x = np.arange(len(values))
    y = np.array(values)
    if np.std(y) == 0:
        return "stable"

    slope, _ = np.polyfit(x, y, 1)
    cv = _cv(values)

    if cv > 0.50:
        return "erratic"
    if slope / np.mean(y) > 0.05:
        return "growing"
    if slope / np.mean(y) < -0.05:
        return "declining"
    return "stable"


def _rejection_risk_label(risk_score: float) -> str:
    """Convert numeric risk score to label."""
    if risk_score <= 0.25:
        return "low"
    if risk_score <= 0.60:
        return "medium"
    return "high"


# ═══════════════════════════════════════════════════════════════════════════════
#  LLM Doc Extractor
# ═══════════════════════════════════════════════════════════════════════════════


class LLMDocExtractor:
    """Extract structured cash flow features from self-employed applicant documents.

    Operates in two modes:
      - MOCK (default for development): generates realistic synthetic extractions
      - REAL: function structure ready for DeepSeek API calls

    Args:
        api_key: DeepSeek API key (optional, triggers real mode if provided)
        mock: Force mock mode even if api_key is provided

    Usage:
        extractor = LLMDocExtractor()
        result = extractor.mock_extract("rideshare_driver")
        boost = extractor.get_score_boost(result, app_data)

        # Real mode (when API key is configured):
        # result = extractor.extract(document_text, "bank_statement")
    """

    # ── Lifecycle ────────────────────────────────────────────────────────

    def __init__(self, api_key: str | None = None, mock: bool = True):
        self.api_key = api_key or os.environ.get("DEEPSEEK_API_KEY", "")
        self.mock = mock or not self.api_key
        self._cache: dict[str, dict[str, Any]] = {}

    # ── Primary Interface ────────────────────────────────────────────────

    def extract(
        self,
        doc_text: str,
        doc_type: str,
        profile_hint: str | None = None,
    ) -> dict[str, Any]:
        """Extract features from a single document.

        Args:
            doc_text: Raw text content of the document
            doc_type: Type of document — one of:
                "bank_statement", "schedule_c", "1099_form", "gig_platform_report"
            profile_hint: Hint for mock generation (ignored in real mode)

        Returns:
            Full extraction result dict.
        """
        if self.mock:
            return self.mock_extract(profile_hint or "average")

        # ── REAL MODE: DeepSeek API call (structure ready, not yet wired) ──
        prompt = PROMPT_TEMPLATES.get(doc_type, PROMPT_TEMPLATES["bank_statement"])
        filled_prompt = prompt.replace("{document_text}", doc_text[:8000])

        # TODO: Wire up actual DeepSeek API call via OpenAI-compatible client
        # from openai import OpenAI
        # client = OpenAI(
        #     api_key=self.api_key,
        #     base_url="https://api.deepseek.com/v1",
        # )
        # response = client.chat.completions.create(
        #     model="deepseek-chat",
        #     max_tokens=2000,
        #     messages=[
        #         {"role": "system", "content": "You are a precise financial document analyzer."},
        #         {"role": "user", "content": filled_prompt},
        #     ],
        # )
        # raw = json.loads(response.choices[0].message.content)

        # Stub: return mock until API is wired
        print(
            f"[LLMDocExtractor] REAL mode not yet wired — "
            f"returning mock for {doc_type} (profile_hint={profile_hint})"
        )
        return self.mock_extract(profile_hint or "average")

    # ── Mock Extraction ──────────────────────────────────────────────────

    def mock_extract(self, profile: str = "average") -> dict[str, Any]:
        """Generate a realistic mock extraction result for a self-employed profile.

        Args:
            profile: One of "photographer", "rideshare_driver",
                     "freelance_developer", "contractor", or "average"

        Returns:
            Complete extraction dict following the output schema.
        """
        rng = random.Random()
        rng.seed(os.urandom(4))

        # Resolve profile
        if profile == "average":
            profile = rng.choice(list(SE_PROFILES.keys()))
        elif profile not in SE_PROFILES:
            profile = rng.choice(list(SE_PROFILES.keys()))

        cfg = SE_PROFILES[profile]
        profile_seed = hash(profile) & 0xFFFFFFFF
        rng = random.Random(profile_seed)

        # ── Generate income parameters ───────────────────────────────
        annual_income = rng.randint(*cfg["typical_annual_income_range"])
        monthly_income = annual_income / 12.0

        # Generate 12 months of income data
        base_monthly = monthly_income
        volatility = rng.uniform(*cfg["income_volatility_range"])
        months = []
        for m in range(12):
            # Add some noise and trend
            trend_factor = 1.0 + (m - 5.5) * 0.005  # slight upward drift
            noise = rng.gauss(0, base_monthly * volatility * 0.5)
            val = max(base_monthly * trend_factor + noise, base_monthly * 0.3)
            months.append(round(val, 2))

        # Inject seasonality based on profile
        if profile == "photographer":
            # Summer/winter wedding season boost
            for m in [5, 6, 7, 8]:  # Jun-Sep
                months[m] = round(months[m] * rng.uniform(1.2, 1.6))
            for m in [0, 11]:  # Jan, Dec
                months[m] = round(months[m] * rng.uniform(0.5, 0.8))
        elif profile == "rideshare_driver":
            # Summer and holiday boost
            for m in [6, 7, 11]:  # Jul, Aug, Dec
                months[m] = round(months[m] * rng.uniform(1.1, 1.4))
        elif profile == "freelance_developer":
            # Tax season + Q4 push
            for m in [2, 3, 10, 11]:  # Mar-Apr, Nov-Dec
                months[m] = round(months[m] * rng.uniform(1.1, 1.3))
            # Random zero-income month (volatility)
            if rng.random() < 0.25:
                zero_month = rng.randint(0, 11)
                months[zero_month] = 0

        income_cv = _cv(months)
        income_trend = _trend_label(months)
        total_deposits = sum(months)

        # ── Expense ratio ────────────────────────────────────────────
        expense_ratio = rng.uniform(*cfg["business_expense_ratio_range"])
        total_expenses = round(total_deposits * expense_ratio)

        # ── Stated vs deposit ratio ──────────────────────────────────
        stated_vs_deposit = rng.uniform(0.75, 1.20)
        if rng.random() < 0.15:
            stated_vs_deposit = rng.uniform(1.25, 1.80)  # some overstatement

        # ── Tenure ───────────────────────────────────────────────────
        tenure_months = rng.randint(*cfg["employer_tenure_months_range"])

        # ── Document flags ───────────────────────────────────────────
        has_schedule_c = profile in ("photographer", "contractor") or rng.random() < 0.6
        has_1099 = profile in ("rideshare_driver", "freelance_developer") or rng.random() < 0.5
        gig_platform_count = cfg["gig_platform_count"]

        # ── Anomaly generation ───────────────────────────────────────
        anomaly_flags: list[str] = []
        # Add profile-typical anomalies
        for anomaly in cfg["typical_anomalies"]:
            if rng.random() < 0.35:
                anomaly_flags.append(anomaly)

        # Random general anomalies
        if income_cv > 0.45:
            anomaly_flags.append("high_income_volatility")
        if tenure_months < 12:
            anomaly_flags.append("short_self_employed_tenure")
        if stated_vs_deposit > 1.30:
            anomaly_flags.append("stated_income_exceeds_deposits")
        if expense_ratio > 0.60:
            anomaly_flags.append("high_expense_ratio")
        if rng.random() < 0.10:
            anomaly_flags.append("poor_document_quality")

        # Deduplicate
        anomaly_flags = list(dict.fromkeys(anomaly_flags))
        anomaly_count = len(anomaly_flags)

        # ── Document quality score ───────────────────────────────────
        doc_quality = rng.uniform(0.70, 0.99)
        if "poor_document_quality" in anomaly_flags:
            doc_quality = rng.uniform(0.20, 0.50)

        # ── Rejection risk ──────────────────────────────────────────
        risk_signals = 0
        if income_trend == "declining":
            risk_signals += 2
        if income_cv > 0.45:
            risk_signals += 1
        if stated_vs_deposit > 1.30:
            risk_signals += 2
        if tenure_months < 12:
            risk_signals += 2
        if expense_ratio > 0.60:
            risk_signals += 1
        if doc_quality < 0.5:
            risk_signals += 2
        if len(anomaly_flags) > 3:
            risk_signals += 1

        risk_score = min(risk_signals / 8.0, 1.0)
        rejection_risk = _rejection_risk_label(risk_score)

        # ── Recommended boost ────────────────────────────────────────
        # Boost starts at 15 for clean, strong self-employed docs
        max_boost = 15.0
        deductions = 0.0
        anomaly_penalties = {
            "declining_income_trend": 5.0,
            "high_income_volatility": 3.0,
            "nsf_overdraft_events": 5.0,
            "stated_income_exceeds_deposits": 6.0,
            "large_unusual_deposit": 2.0,
            "high_expense_ratio": 3.0,
            "short_self_employed_tenure": 5.0,
            "zero_income_months": 2.0,
            "poor_document_quality": 4.0,
            "missing_schedule_c": 3.0,
            "employment_gap": 3.0,
            "declining_multi_platform": 1.5,
        }
        for flag in anomaly_flags:
            # Fuzzy match flag to penalty key
            for key, penalty in anomaly_penalties.items():
                key_words = key.replace("_", " ").lower()
                if any(word in flag.lower() for word in key_words.split()):
                    deductions += penalty
                    break
            else:
                # Default penalty for unknown anomalies
                deductions += 2.0

        # Cap at max boost and ensure non-negative
        recommended_boost = max(round(max_boost - deductions, 1), 0.0)

        # ── Assemble result ──────────────────────────────────────────
        # Estimate final annual income as the robust central tendency
        income_gte = round(np.median(months) * 12)

        # Small chance of generating a lower bound (to show range)
        if rng.random() < 0.2:
            income_gte = round(income_gte * rng.uniform(0.7, 0.95))

        result: dict[str, Any] = {
            # Core income
            "income_gte": income_gte,
            "income_confidence": round(max(0.5, min(0.99, 1.0 - income_cv * 0.5)), 2),
            "income_trend": income_trend,
            "income_volatility": round(income_cv, 4),
            "stated_vs_deposit_ratio": round(stated_vs_deposit, 3),
            "business_expense_ratio": round(expense_ratio, 3),
            # Employment
            "employer_tenure_months": tenure_months,
            "has_schedule_c": has_schedule_c,
            "has_1099": has_1099,
            "gig_platform_count": gig_platform_count,
            # Risk & quality
            "anomaly_flags": anomaly_flags,
            "anomaly_count": anomaly_count,
            "doc_quality_score": round(doc_quality, 3),
            "recommended_boost": recommended_boost,
            "rejection_risk": rejection_risk,
            # Detailed breakdown (for debugging / explainability)
            "_monthly_breakdown": months,
            "_annualized_income": round(np.median(months) * 12, 2),
            "_profile_used": profile,
            "_mode": "mock",
        }

        return result

    # ── Score Boost Calculation ─────────────────────────────────────────

    def get_score_boost(
        self,
        extraction: dict[str, Any],
        app_data: dict[str, Any] | None = None,
    ) -> float:
        """Calculate the adjusted score boost based on extraction results and applicant data.

        The boost improves the borrower's credit score to account for strong cash flow
        that traditional credit scoring misses. Max boost is 15 points.

        Args:
            extraction: The output from extract() or mock_extract()
            app_data: Optional applicant data dict containing:
                - stated_income: float
                - self_employed: bool
                - years_self_employed: float (or tenure_months)
                - credit_score: int | None

        Returns:
            Adjusted boost value (0.0 to 15.0).
        """
        base_boost = extraction.get("recommended_boost", 10.0)
        if base_boost <= 0:
            return 0.0

        adjustment = 0.0

        # ── Penalize high volatility ─────────────────────────────────
        volatility = extraction.get("income_volatility", 0.0)
        if volatility > 0.40:
            adjustment -= base_boost * 0.15
        elif volatility > 0.30:
            adjustment -= base_boost * 0.05

        # ── Penalize high expense ratio ──────────────────────────────
        expense_ratio = extraction.get("business_expense_ratio", 0.0)
        if expense_ratio > 0.50:
            adjustment -= base_boost * 0.10
        elif expense_ratio > 0.60:
            adjustment -= base_boost * 0.20

        # ── Penalize stated vs deposit mismatch ──────────────────────
        stated_deposit = extraction.get("stated_vs_deposit_ratio", 1.0)
        if stated_deposit > 1.30:
            adjustment -= base_boost * 0.25
        elif stated_deposit < 0.60:
            # Way more in bank than stated — possible unreported income
            adjustment -= base_boost * 0.10

        # ── Adjust for income trend ──────────────────────────────────
        trend = extraction.get("income_trend", "stable")
        if trend == "growing":
            adjustment += base_boost * 0.10
        elif trend == "declining":
            adjustment -= base_boost * 0.20
        elif trend == "erratic":
            adjustment -= base_boost * 0.10

        # ── Tenure bonus ─────────────────────────────────────────────
        tenure = extraction.get("employer_tenure_months", 0)
        if tenure >= 36:
            adjustment += base_boost * 0.10
        elif tenure >= 60:
            adjustment += base_boost * 0.15

        # ── Document quality ─────────────────────────────────────────
        doc_quality = extraction.get("doc_quality_score", 0.7)
        if doc_quality >= 0.85:
            adjustment += base_boost * 0.10
        elif doc_quality < 0.50:
            adjustment -= base_boost * 0.15

        # ── Multi-platform diversification (good for gig workers) ────
        gig_count = extraction.get("gig_platform_count", 1)
        if gig_count >= 2:
            adjustment += base_boost * 0.05
        if gig_count >= 3:
            adjustment += base_boost * 0.03

        # ── Schedule C bonus (documents income honestly) ─────────────
        if extraction.get("has_schedule_c"):
            adjustment += base_boost * 0.08

        # ── Rejection risk override ──────────────────────────────────
        risk = extraction.get("rejection_risk", "low")
        if risk == "high":
            adjustment -= base_boost * 0.30
        elif risk == "medium":
            adjustment -= base_boost * 0.10

        # ── Apply app_data adjustments ───────────────────────────────
        if app_data:
            stated = app_data.get("stated_income", 0)
            extracted_income = extraction.get("income_gte", 0)
            if stated > 0 and extracted_income > 0:
                ratio = extracted_income / stated
                if ratio < 0.7:
                    # Extraction significantly below stated income
                    adjustment -= base_boost * 0.20
                elif ratio > 1.5:
                    # Extraction significantly above stated income
                    adjustment += base_boost * 0.05

            # Credit score overlap
            credit_score = app_data.get("credit_score")
            if credit_score is not None and credit_score >= 680:
                # Already has good credit; boost is less impactful
                adjustment -= base_boost * 0.15

        # ── Clamp ────────────────────────────────────────────────────
        adjusted = base_boost + adjustment
        return round(max(0.0, min(15.0, adjusted)), 1)

    # ── Anomaly Detection ───────────────────────────────────────────────

    def detect_anomalies(
        self,
        extraction: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Analyze extraction results and return a list of flagged anomalies with details.

        Each anomaly dict contains:
            - flag: machine-readable string
            - label: human-readable description
            - severity: "low" | "medium" | "high"
            - impact: numeric score impact (negative)

        Args:
            extraction: The output from extract() or mock_extract()

        Returns:
            List of anomaly dicts.
        """
        anomalies: list[dict[str, Any]] = []
        flags = extraction.get("anomaly_flags", [])
        seen_flags: set[str] = set()

        for flag in flags:
            # Match flag to catalog entry
            matched = False
            for cat_key, cat_entry in ANOMALY_CATALOG.items():
                catalog_flag = cat_entry["flag"]
                # Check if flag contains the catalog flag or vice-versa
                if flag.startswith(catalog_flag) or catalog_flag.startswith(flag) or flag in catalog_flag or catalog_flag in flag:
                    if catalog_flag not in seen_flags:
                        anomalies.append({
                            "flag": catalog_flag,
                            "label": cat_entry["label"],
                            "severity": cat_entry["severity"],
                            "impact": cat_entry["impact"],
                        })
                        seen_flags.add(catalog_flag)
                        matched = True
                    break

            if not matched:
                # Unknown anomaly — try a broader match
                for cat_key, cat_entry in ANOMALY_CATALOG.items():
                    if any(word in flag.lower() for word in cat_key.replace("_", " ").lower().split()):
                        if cat_entry["flag"] not in seen_flags:
                            anomalies.append({
                                "flag": cat_entry["flag"],
                                "label": cat_entry["label"],
                                "severity": cat_entry["severity"],
                                "impact": cat_entry["impact"],
                            })
                            seen_flags.add(cat_entry["flag"])
                        matched = True
                        break

            if not matched:
                # Generic entry for unmatched flags
                anomalies.append({
                    "flag": flag,
                    "label": flag.replace("_", " ").title(),
                    "severity": "medium",
                    "impact": -2.0,
                })

        # ── Compute additional anomalies from numeric fields ─────────
        volatility = extraction.get("income_volatility", 0.0)
        if volatility > 0.50 and "high_income_volatility" not in seen_flags:
            anomalies.append({
                "flag": "high_income_volatility",
                "label": "High income volatility (CV > 0.50)",
                "severity": "medium",
                "impact": -3.0,
            })

        expense_ratio = extraction.get("business_expense_ratio", 0.0)
        if expense_ratio > 0.60 and "high_expense_ratio" not in seen_flags:
            anomalies.append({
                "flag": "high_expense_ratio",
                "label": "Expense ratio > 60% suggests low profitability",
                "severity": "medium",
                "impact": -3.0,
            })

        stated_vs_deposit = extraction.get("stated_vs_deposit_ratio", 1.0)
        if stated_vs_deposit > 1.30 and "stated_income_exceeds_deposits" not in seen_flags:
            anomalies.append({
                "flag": "stated_income_exceeds_deposits",
                "label": "Stated income > 130% of bank deposits",
                "severity": "high",
                "impact": -6.0,
            })

        tenure = extraction.get("employer_tenure_months", 0)
        if 0 < tenure < 12 and "short_self_employed_tenure" not in seen_flags:
            anomalies.append({
                "flag": "short_self_employed_tenure",
                "label": "Self-employment tenure < 12 months",
                "severity": "high",
                "impact": -5.0,
            })

        return sorted(anomalies, key=lambda a: a["impact"])

    # ── Explainability ─────────────────────────────────────────────────

    def explain(self, extraction: dict[str, Any]) -> str:
        """Generate a human-readable explanation of the extraction results.

        Useful for loan officer dashboards and applicant-facing explanations.

        Args:
            extraction: The output from extract() or mock_extract()

        Returns:
            Plain-text explanation string.
        """
        lines: list[str] = []
        lines.append("── Document Extraction Summary ──")
        lines.append("")

        # Income
        income_gte = extraction.get("income_gte", 0)
        confidence = extraction.get("income_confidence", 0) * 100
        trend = extraction.get("income_trend", "N/A")
        volatility = extraction.get("income_volatility", 0) * 100
        lines.append(f"Estimated Annual Income: ${income_gte:,.0f}")
        lines.append(f"Confidence: {confidence:.0f}%")
        lines.append(f"Income Trend: {trend.title()}")
        lines.append(f"Income Volatility (CV): {volatility:.1f}%")

        # Ratios
        svd = extraction.get("stated_vs_deposit_ratio", 0)
        er = extraction.get("business_expense_ratio", 0) * 100
        lines.append(f"Stated vs Deposit Ratio: {svd:.2f}x")
        lines.append(f"Business Expense Ratio: {er:.1f}%")

        # Employment
        tenure = extraction.get("employer_tenure_months", 0)
        years = tenure / 12.0
        lines.append(f"Self-Employment Tenure: {years:.1f} years ({tenure} months)")

        doc_flags = []
        if extraction.get("has_schedule_c"):
            doc_flags.append("Schedule C ✓")
        if extraction.get("has_1099"):
            doc_flags.append("1099 ✓")
        gig_count = extraction.get("gig_platform_count", 0)
        lines.append(f"Documents: {' | '.join(doc_flags) if doc_flags else 'None'}")
        if gig_count > 0:
            lines.append(f"Gig Platforms: {gig_count}")

        # Quality
        dq = extraction.get("doc_quality_score", 0) * 100
        lines.append(f"Document Quality: {dq:.0f}%")

        # Anomalies
        anomalies = extraction.get("anomaly_flags", [])
        if anomalies:
            lines.append("")
            lines.append("⚠ Anomalies Detected:")
            for a in anomalies:
                lines.append(f"  • {a.replace('_', ' ').title()}")
        else:
            lines.append("")
            lines.append("✓ No anomalies detected.")

        # Risk and boost
        risk = extraction.get("rejection_risk", "N/A")
        boost = extraction.get("recommended_boost", 0)
        lines.append("")
        lines.append(f"Rejection Risk: {risk.upper()}")
        lines.append(f"Recommended Score Boost: {boost:.1f} points")

        return "\n".join(lines)

    # ── Cache Management ────────────────────────────────────────────────

    def clear_cache(self) -> None:
        """Clear the extraction cache."""
        self._cache.clear()


# ═══════════════════════════════════════════════════════════════════════════════
#  CLI / Self-Test
# ═══════════════════════════════════════════════════════════════════════════════

def _demo_all_profiles() -> None:
    """Run a demo showing extraction results for all self-employed profiles."""
    extractor = LLMDocExtractor()

    print("=" * 72)
    print("  LLM Doc Extractor — Self-Employed Profile Demo")
    print("=" * 72)

    for profile_name in sorted(SE_PROFILES.keys()):
        cfg = SE_PROFILES[profile_name]
        print(f"\n{'─' * 72}")
        print(f"  Profile: {cfg['label']} ({profile_name})")
        print(f"{'─' * 72}")

        result = extractor.mock_extract(profile_name)
        print(extractor.explain(result))

        # Show anomalies in detail
        anomalies = extractor.detect_anomalies(result)
        if anomalies:
            print("\n  Detailed Anomaly Breakdown:")
            for a in anomalies:
                print(
                    f"    [{a['severity'].upper()}] {a['label']} "
                    f"(impact: {a['impact']:.1f})"
                )

        # Score boost with sample app_data
        boost = extractor.get_score_boost(result)
        print(f"\n  Score Boost (base): {boost:.1f} / 15.0")

        # With app data
        app_data = {
            "stated_income": round(result["income_gte"] * random.uniform(0.8, 1.4)),
            "self_employed": True,
            "tenure_months": result["employer_tenure_months"],
            "credit_score": random.choice([None, 650, 700, 720, 680]),
        }
        boost_adjusted = extractor.get_score_boost(result, app_data)
        print(f"  Score Boost (with app data): {boost_adjusted:.1f} / 15.0")


def _demo_batch() -> None:
    """Run a batch of extractions and show aggregate statistics."""
    extractor = LLMDocExtractor()
    n = 100

    print(f"Batch demo: {n} random extractions...")
    results = [extractor.mock_extract("average") for _ in range(n)]

    incomes = [r["income_gte"] for r in results]
    boosts = [r["recommended_boost"] for r in results]
    risks = [r["rejection_risk"] for r in results]
    quality = [r["doc_quality_score"] for r in results]
    anomalies_count = [r["anomaly_count"] for r in results]

    print(f"\n{'─' * 50}")
    print(f"  Aggregate Statistics (n={n})")
    print(f"{'─' * 50}")
    print(f"  Income GTE:       ${np.mean(incomes):,.0f} ± ${np.std(incomes):,.0f}")
    print(f"  Score Boost:      {np.mean(boosts):.1f} ± {np.std(boosts):.1f}")
    print(f"  Doc Quality:      {np.mean(quality):.3f} ± {np.std(quality):.3f}")
    print(f"  Avg Anomalies:    {np.mean(anomalies_count):.1f}")
    print(f"  Rejection Risks:  "
          f"L={risks.count('low')} / M={risks.count('medium')} / H={risks.count('high')}")


if __name__ == "__main__":
    import sys

    if "--batch" in sys.argv:
        _demo_batch()
    elif "--profile" in sys.argv:
        idx = sys.argv.index("--profile")
        profile = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else "average"
        extractor = LLMDocExtractor()
        result = extractor.mock_extract(profile)
        print(extractor.explain(result))
        print(f"\nRaw result:\n{json.dumps(result, indent=2)}")
    else:
        _demo_all_profiles()
