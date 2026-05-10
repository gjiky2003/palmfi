#!/usr/bin/env python3
"""
Manual Review Assistant — Human-in-the-Loop Decision Support Tool
=================================================================

A structured decision-support tool for human underwriters reviewing
borderline loan applications. Takes the complete application profile
(application data + bureau + cash flow + gating rules + model scores)
and produces a structured review summary with suggestions.

Two modes:
    MOCK mode (development) — generates realistic structured review
        output based on mock profiles and input data.
    REAL mode — calls DeepSeek API with structured prompts to generate
        the review output (requires DEEPSEEK_API_KEY environment variable).

Intended for applications that fall into the "consideration" zone
after the two-stage underwriting pipeline and need a human eye.

Usage:
    from manual_review_assistant import ManualReviewAssistant

    assistant = ManualReviewAssistant(mock=True)
    result = assistant.review(review_input)
    print(assistant.summarize_for_human(result))
"""

from __future__ import annotations

import json
import os
import uuid
from copy import deepcopy
from typing import Any

__all__ = ["ManualReviewAssistant"]

# ═══════════════════════════════════════════════════════════════════════════════
# Constants & Mock Profiles
# ═══════════════════════════════════════════════════════════════════════════════

MOCK_REVIEW_ID_PREFIX = "MOCK-REVIEW-"

# ── Default input template ───────────────────────────────────────────────────

DEFAULT_REVIEW_INPUT: dict[str, Any] = {
    "app_data": {
        "age": 28,
        "annual_income": 45000,
        "employment_length": 1.5,
        "credit_score": 620,
        "dti_ratio": 0.40,
        "utilization": 0.65,
        "num_derogatory": 2,
        "num_credit_lines": 4,
        "home_ownership": "rent",
        "loan_amount": 3000,
        "loan_purpose": "debt_consolidation",
        "term_months": 18,
        "first_name": "Jane",
        "last_name": "Doe",
        "state": "VA",
        "employment_status": "full-time",
        "employer_name": "ABC Corp",
        "employer_tenure_months": 18,
    },
    "bureau_data": {
        "fico_score": 620,
        "dti_ratio": 0.40,
        "revolving_utilization": 0.65,
        "derogatory_count": 2,
        "open_trade_lines": 4,
        "risk_factors": ["High utilization", "Recent inquiries"],
        "first_credit_year": 2018,
        "total_balance": 15000,
    },
    "cash_flow_metrics": {
        "cash_flow_score": 65,
        "cash_flow_income": 4200,
        "income_volatility": 0.15,
        "overdraft_frequency": 1,
        "income_consistency": 0.7,
    },
    "model_result": {
        "risk_score": 58,
        "risk_tier": "C",
        "probability_of_default": 0.58,
    },
    "zones": {
        "original_zone": "consideration",
        "reconsideration_zone": None,
    },
    "gating_results": {
        "hard_cut_blocked": False,
        "suppression_flagged": True,
        "suppressions": [
            {
                "rule": "income_discrepancy",
                "reason": "Stated income vs bureau differs by 60%",
                "flagged": True,
            }
        ],
        "soft_override_applies": False,
    },
}

# ── Mock Review Profiles ─────────────────────────────────────────────────────

MOCK_PROFILES: dict[str, dict[str, Any]] = {
    "borderline_approve": {
        "label": "Borderline Approve",
        "description": "FICO 640, good cash flow, minor suppression flags",
        "input_overrides": {
            "app_data": {
                "annual_income": 52000,
                "employment_length": 3.0,
                "credit_score": 640,
                "dti_ratio": 0.32,
                "utilization": 0.40,
                "num_derogatory": 1,
                "num_credit_lines": 6,
                "home_ownership": "rent",
                "loan_amount": 4000,
                "loan_purpose": "debt_consolidation",
                "term_months": 24,
                "first_name": "Maria",
                "last_name": "Garcia",
                "state": "TX",
                "employment_status": "full-time",
                "employer_name": "TechServe Inc",
                "employer_tenure_months": 36,
            },
            "bureau_data": {
                "fico_score": 640,
                "dti_ratio": 0.32,
                "revolving_utilization": 0.40,
                "derogatory_count": 1,
                "open_trade_lines": 6,
                "risk_factors": ["Thin file (6 lines)", "Single 30-day late 2yr ago"],
                "first_credit_year": 2016,
                "total_balance": 12000,
            },
            "cash_flow_metrics": {
                "cash_flow_score": 78,
                "cash_flow_income": 4800,
                "income_volatility": 0.08,
                "overdraft_frequency": 0,
                "income_consistency": 0.88,
            },
            "model_result": {
                "risk_score": 52,
                "risk_tier": "C",
                "probability_of_default": 0.42,
            },
            "zones": {
                "original_zone": "consideration",
                "reconsideration_zone": "consideration",
            },
            "gating_results": {
                "hard_cut_blocked": False,
                "suppression_flagged": True,
                "suppressions": [
                    {
                        "rule": "employment_verification",
                        "reason": "Employer not in public database",
                        "flagged": True,
                    }
                ],
                "soft_override_applies": True,
            },
        },
    },
    "borderline_decline": {
        "label": "Borderline Decline",
        "description": "FICO 610, bad cash flow, income discrepancy",
        "input_overrides": {
            "app_data": {
                "annual_income": 32000,
                "employment_length": 0.5,
                "credit_score": 610,
                "dti_ratio": 0.48,
                "utilization": 0.78,
                "num_derogatory": 3,
                "num_credit_lines": 3,
                "home_ownership": "rent",
                "loan_amount": 5000,
                "loan_purpose": "debt_consolidation",
                "term_months": 36,
                "first_name": "Robert",
                "last_name": "Kim",
                "state": "NV",
                "employment_status": "part-time",
                "employer_name": "GigWorks LLC",
                "employer_tenure_months": 6,
            },
            "bureau_data": {
                "fico_score": 610,
                "dti_ratio": 0.48,
                "revolving_utilization": 0.78,
                "derogatory_count": 3,
                "open_trade_lines": 3,
                "risk_factors": [
                    "High revolving utilization",
                    "Multiple derogatory marks",
                    "Thin credit file",
                ],
                "first_credit_year": 2019,
                "total_balance": 22000,
            },
            "cash_flow_metrics": {
                "cash_flow_score": 32,
                "cash_flow_income": 2900,
                "income_volatility": 0.35,
                "overdraft_frequency": 4,
                "income_consistency": 0.35,
            },
            "model_result": {
                "risk_score": 72,
                "risk_tier": "D",
                "probability_of_default": 0.72,
            },
            "zones": {
                "original_zone": "decline",
                "reconsideration_zone": "decline",
            },
            "gating_results": {
                "hard_cut_blocked": False,
                "suppression_flagged": True,
                "suppressions": [
                    {
                        "rule": "income_discrepancy",
                        "reason": "Stated income vs bureau differs by 48%",
                        "flagged": True,
                    },
                    {
                        "rule": "employment_instability",
                        "reason": "Part-time employment with < 6 months tenure",
                        "flagged": True,
                    },
                ],
                "soft_override_applies": False,
            },
        },
    },
    "high_risk_approve": {
        "label": "High Risk / Strong Cash Flow",
        "description": "FICO 580 but great cash flow (gig worker with steady deposits)",
        "input_overrides": {
            "app_data": {
                "annual_income": 48000,
                "employment_length": 2.0,
                "credit_score": 580,
                "dti_ratio": 0.25,
                "utilization": 0.55,
                "num_derogatory": 4,
                "num_credit_lines": 2,
                "home_ownership": "rent",
                "loan_amount": 2500,
                "loan_purpose": "personal",
                "term_months": 12,
                "first_name": "Carlos",
                "last_name": "Mendez",
                "state": "FL",
                "employment_status": "self-employed",
                "employer_name": "Uber / DoorDash",
                "employer_tenure_months": 24,
            },
            "bureau_data": {
                "fico_score": 580,
                "dti_ratio": 0.25,
                "revolving_utilization": 0.55,
                "derogatory_count": 4,
                "open_trade_lines": 2,
                "risk_factors": [
                    "Thin file (2 trade lines)",
                    "Multiple derogatory marks",
                    "Sub-580 FICO",
                ],
                "first_credit_year": 2020,
                "total_balance": 8000,
            },
            "cash_flow_metrics": {
                "cash_flow_score": 88,
                "cash_flow_income": 5200,
                "income_volatility": 0.09,
                "overdraft_frequency": 0,
                "income_consistency": 0.92,
            },
            "model_result": {
                "risk_score": 65,
                "risk_tier": "D",
                "probability_of_default": 0.62,
            },
            "zones": {
                "original_zone": "decline",
                "reconsideration_zone": "consideration",
            },
            "gating_results": {
                "hard_cut_blocked": False,
                "suppression_flagged": False,
                "suppressions": [],
                "soft_override_applies": True,
            },
        },
    },
    "conditional": {
        "label": "Conditional Approve",
        "description": "FICO 660 but high loan-to-income ratio, needs conditions",
        "input_overrides": {
            "app_data": {
                "annual_income": 36000,
                "employment_length": 4.0,
                "credit_score": 660,
                "dti_ratio": 0.42,
                "utilization": 0.30,
                "num_derogatory": 0,
                "num_credit_lines": 8,
                "home_ownership": "mortgage",
                "loan_amount": 5000,
                "loan_purpose": "debt_consolidation",
                "term_months": 24,
                "first_name": "Aisha",
                "last_name": "Williams",
                "state": "GA",
                "employment_status": "full-time",
                "employer_name": "County School District",
                "employer_tenure_months": 48,
            },
            "bureau_data": {
                "fico_score": 660,
                "dti_ratio": 0.42,
                "revolving_utilization": 0.30,
                "derogatory_count": 0,
                "open_trade_lines": 8,
                "risk_factors": ["Elevated DTI", "Limited credit depth"],
                "first_credit_year": 2015,
                "total_balance": 18000,
            },
            "cash_flow_metrics": {
                "cash_flow_score": 70,
                "cash_flow_income": 3800,
                "income_volatility": 0.05,
                "overdraft_frequency": 1,
                "income_consistency": 0.85,
            },
            "model_result": {
                "risk_score": 55,
                "risk_tier": "C",
                "probability_of_default": 0.50,
            },
            "zones": {
                "original_zone": "consideration",
                "reconsideration_zone": "consideration",
            },
            "gating_results": {
                "hard_cut_blocked": False,
                "suppression_flagged": True,
                "suppressions": [
                    {
                        "rule": "high_lti",
                        "reason": "Loan-to-income ratio exceeds 40% threshold",
                        "flagged": True,
                    }
                ],
                "soft_override_applies": True,
            },
        },
    },
    "auto_approve_upgrade": {
        "label": "Auto-Approve / Rate Upgrade",
        "description": "FICO 700, low risk, considering rate improvement",
        "input_overrides": {
            "app_data": {
                "annual_income": 75000,
                "employment_length": 6.0,
                "credit_score": 700,
                "dti_ratio": 0.22,
                "utilization": 0.15,
                "num_derogatory": 0,
                "num_credit_lines": 12,
                "home_ownership": "mortgage",
                "loan_amount": 3000,
                "loan_purpose": "home_improvement",
                "term_months": 12,
                "first_name": "James",
                "last_name": "Chen",
                "state": "CA",
                "employment_status": "full-time",
                "employer_name": "Pacific Tech Corp",
                "employer_tenure_months": 72,
            },
            "bureau_data": {
                "fico_score": 700,
                "dti_ratio": 0.22,
                "revolving_utilization": 0.15,
                "derogatory_count": 0,
                "open_trade_lines": 12,
                "risk_factors": [],
                "first_credit_year": 2012,
                "total_balance": 25000,
            },
            "cash_flow_metrics": {
                "cash_flow_score": 92,
                "cash_flow_income": 6200,
                "income_volatility": 0.04,
                "overdraft_frequency": 0,
                "income_consistency": 0.95,
            },
            "model_result": {
                "risk_score": 28,
                "risk_tier": "A",
                "probability_of_default": 0.18,
            },
            "zones": {
                "original_zone": "auto_approve",
                "reconsideration_zone": None,
            },
            "gating_results": {
                "hard_cut_blocked": False,
                "suppression_flagged": False,
                "suppressions": [],
                "soft_override_applies": False,
            },
        },
    },
}

# ── Risk Factors Library ─────────────────────────────────────────────────────

SEVERITY_RANK = {"high": 3, "medium": 2, "low": 1}
SIGNIFICANCE_RANK = {"high": 3, "medium": 2, "low": 1}

RISK_FACTOR_TEMPLATES: list[dict[str, Any]] = [
    {
        "factor": "High credit utilization",
        "condition": lambda i: i["bureau_data"].get("revolving_utilization", 0) > 0.60,
        "detail_tmpl": "Revolving utilization at {util:.0%} — well above 50% threshold",
        "severity": "high",
        "mitigation_tmpl": "Paying down balances to ≤30% would improve score by 30-50 pts",
    },
    {
        "factor": "Elevated DTI ratio",
        "condition": lambda i: i["bureau_data"].get("dti_ratio", 0) > 0.40,
        "detail_tmpl": "DTI ratio of {dti:.0%} exceeds 40% guideline",
        "severity": "high",
        "mitigation_tmpl": "Debt consolidation purpose may reduce effective DTI if revolving debt is paid off",
    },
    {
        "factor": "Thin credit file",
        "condition": lambda i: i["bureau_data"].get("open_trade_lines", 99) < 4,
        "detail_tmpl": "Only {lines} open trade lines — limited credit history depth",
        "severity": "medium",
        "mitigation_tmpl": "Cash flow data can compensate for thin bureau file",
    },
    {
        "factor": "Recent derogatory marks",
        "condition": lambda i: i["bureau_data"].get("derogatory_count", 0) >= 2,
        "detail_tmpl": "{count} derogatory marks on credit report",
        "severity": "high",
        "mitigation_tmpl": "Verify if derogatory marks are related to medical debt or resolved",
    },
    {
        "factor": "Income instability",
        "condition": lambda i: (
            i.get("cash_flow_metrics")
            and i["cash_flow_metrics"].get("income_volatility", 0) > 0.20
        ),
        "detail_tmpl": "Income volatility of {vol:.0%} — inconsistent month-to-month earnings",
        "severity": "medium",
        "mitigation_tmpl": "Average income over 6 months may still support the payment",
    },
    {
        "factor": "Frequent overdrafts",
        "condition": lambda i: (
            i.get("cash_flow_metrics")
            and i["cash_flow_metrics"].get("overdraft_frequency", 0) >= 3
        ),
        "detail_tmpl": "{count} overdraft events in recent period",
        "severity": "high",
        "mitigation_tmpl": "Review root cause — could be timing issues rather than chronic shortfall",
    },
    {
        "factor": "Short employment tenure",
        "condition": lambda i: (
            i["app_data"].get("employer_tenure_months", 99) < 12
        ),
        "detail_tmpl": "Only {months} months at current employer",
        "severity": "low",
        "mitigation_tmpl": "Consider overall career stability and industry job-hopping norms",
    },
    {
        "factor": "Low FICO score",
        "condition": lambda i: i["bureau_data"].get("fico_score", 999) < 600,
        "detail_tmpl": "FICO score of {fico} — below 600 threshold",
        "severity": "high",
        "mitigation_tmpl": "Cash flow score of {cf_score} partially offsets credit risk",
    },
    {
        "factor": "Income discrepancy",
        "condition": lambda i: any(
            s.get("rule") == "income_discrepancy"
            for s in i["gating_results"].get("suppressions", [])
        ),
        "detail_tmpl": "Stated income differs significantly from bureau-reported income",
        "severity": "high",
        "mitigation_tmpl": "Request recent pay stubs or tax returns to verify actual income",
    },
    {
        "factor": "High loan-to-income ratio",
        "condition": lambda i: (
            i["app_data"]["loan_amount"] / max(i["app_data"]["annual_income"], 1)
        ) > 0.10,
        "detail_tmpl": "Loan amount of ${loan:,} represents {lti:.1%} of annual income",
        "severity": "medium",
        "mitigation_tmpl": "Shorter term increases monthly payment but reduces total interest",
    },
    {
        "factor": "Low income consistency",
        "condition": lambda i: (
            i.get("cash_flow_metrics")
            and i["cash_flow_metrics"].get("income_consistency", 1) < 0.50
        ),
        "detail_tmpl": "Income consistency score of {cons:.0%} — irregular deposit patterns",
        "severity": "medium",
        "mitigation_tmpl": "Self-employed borrowers may have legitimate irregular income patterns",
    },
    {
        "factor": "Employment verification needed",
        "condition": lambda i: any(
            s.get("rule") == "employment_verification"
            for s in i["gating_results"].get("suppressions", [])
        ),
        "detail_tmpl": "Employer not found in verification databases",
        "severity": "medium",
        "mitigation_tmpl": "Request W-2 or 1099 forms to verify employment",
    },
]

STRENGTH_FACTOR_TEMPLATES: list[dict[str, Any]] = [
    {
        "factor": "Strong cash flow",
        "condition": lambda i: (
            i.get("cash_flow_metrics")
            and i["cash_flow_metrics"].get("cash_flow_score", 0) >= 75
        ),
        "detail_tmpl": "Cash flow score of {score} — consistent deposits with low volatility",
        "significance": "high",
    },
    {
        "factor": "Low credit utilization",
        "condition": lambda i: i["bureau_data"].get("revolving_utilization", 1) < 0.30,
        "detail_tmpl": "Revolving utilization at {util:.0%} — well-managed credit",
        "significance": "high",
    },
    {
        "factor": "Clean credit history",
        "condition": lambda i: i["bureau_data"].get("derogatory_count", 99) == 0,
        "detail_tmpl": "No derogatory marks on credit report",
        "significance": "high",
    },
    {
        "factor": "Homeowner stability",
        "condition": lambda i: i["app_data"].get("home_ownership") in ("mortgage", "own"),
        "detail_tmpl": "Homeowner with {'mortgage' if i['app_data']['home_ownership'] == 'mortgage' else 'owned'} property",
        "significance": "medium",
    },
    {
        "factor": "Long employment tenure",
        "condition": lambda i: i["app_data"].get("employer_tenure_months", 0) >= 36,
        "detail_tmpl": "{months} months at current employer — strong job stability",
        "significance": "high",
    },
    {
        "factor": "Established credit history",
        "condition": lambda i: (
            i["bureau_data"].get("first_credit_year")
            and (2025 - i["bureau_data"]["first_credit_year"]) >= 5
        ),
        "detail_tmpl": "Credit history established since {year} ({age} years)",
        "significance": "medium",
    },
    {
        "factor": "Multiple open trade lines",
        "condition": lambda i: i["bureau_data"].get("open_trade_lines", 0) >= 8,
        "detail_tmpl": "{lines} open trade lines — diverse credit experience",
        "significance": "medium",
    },
    {
        "factor": "Low DTI ratio",
        "condition": lambda i: i["bureau_data"].get("dti_ratio", 1) < 0.25,
        "detail_tmpl": "DTI ratio of {dti:.0%} — strong debt management",
        "significance": "high",
    },
    {
        "factor": "Low cash flow volatility",
        "condition": lambda i: (
            i.get("cash_flow_metrics")
            and i["cash_flow_metrics"].get("income_volatility", 1) < 0.10
        ),
        "detail_tmpl": "Income volatility of {vol:.0%} — consistent deposit patterns",
        "significance": "medium",
    },
    {
        "factor": "Debt consolidation purpose",
        "condition": lambda i: i["app_data"].get("loan_purpose") == "debt_consolidation",
        "detail_tmpl": "Loan purpose is debt consolidation — likely improves overall financial health",
        "significance": "low",
    },
]

# ── Prompt Templates (for REAL mode with DeepSeek API) ────────────────────────

SYSTEM_PROMPT = """You are a senior loan underwriting advisor at a fintech lending company.
Your role is to review borderline loan applications and provide structured,
unbiased decision support to human underwriters.

You analyze consumer loan applications for amounts between $500-$5,000 with
terms of 6-24 months. You consider credit bureau data, cash flow data from
linked bank accounts, application form data, and model scores.

Your assessment should be:
1. **Balanced** — Identify both risk factors AND strengths
2. **Actionable** — Give specific, useful guidance for the human reviewer
3. **Calibrated** — Use the probability of default and risk scores appropriately
4. **Fair** — Avoid bias; focus on financial indicators, not demographics
5. **Compliant** — Follow fair lending principles in all recommendations

When in doubt, recommend escalation or conditions rather than outright
approval or decline. The final decision rests with the human underwriter."""

STRUCTURED_OUTPUT_INSTRUCTIONS = """You MUST respond with a valid JSON object matching this exact schema:
{
    "review_summary": "2-3 sentence summary of applicant profile",
    "risk_assessment": {
        "overall_risk": "low|medium|high|very_high",
        "credit_quality": "Description of credit profile",
        "cash_flow_quality": "Description of cash flow profile",
        "stability": "Description of employment/housing stability"
    },
    "risk_factors": [{"factor": "...", "detail": "...", "severity": "high|medium|low", "mitigation": "..."}],
    "strength_factors": [{"factor": "...", "detail": "...", "significance": "high|medium|low"}],
    "recommendation": {
        "decision": "approve|decline|escalate|conditional_approve",
        "confidence": "high|medium|low",
        "recommended_amount": 0,
        "recommended_rate_adjustment": 0.0,
        "conditions": [...],
        "rationale": "Full supporting rationale paragraph"
    },
    "red_flags": [{"flag": "...", "action_required": "...", "priority": "high|medium|low"}],
    "questions_for_borrower": [...],
    "estimated_fraud_probability": 0.0
}
"""

RISK_ANALYSIS_PROMPT = """Analyze the following loan application for manual underwriting review.

Provide a structured risk assessment covering:
1. Credit quality (FICO, trade lines, derogatories, utilization)
2. Cash flow quality (income consistency, volatility, overdrafts)
3. Employment and income stability
4. Capacity to repay (DTI, loan-to-income ratio)
5. Gating rule flags and suppressions
6. Model output and risk score context

Consider how these factors interact. For example:
- A low FICO with strong cash flow is less concerning than low FICO with weak cash flow
- Income discrepancies need investigation but may have legitimate explanations
- Thin files can be compensated by stable cash flow patterns
- Self-employed borrowers need different evaluation criteria than W-2 employees

APPLICATION DATA:
{app_data_json}

BUREAU DATA:
{bureau_data_json}

CASH FLOW METRICS:
{cash_flow_json}

MODEL RESULTS:
{model_result_json}

DECISION ZONES:
{zones_json}

GATING RULE RESULTS:
{gating_json}

Generate your structured review following the output schema exactly."""


# ═══════════════════════════════════════════════════════════════════════════════
# Assistant Implementation
# ═══════════════════════════════════════════════════════════════════════════════


class ManualReviewAssistant:
    """Human-in-the-loop decision support tool for underwriters.

    Takes a complete application profile and produces a structured review
    summary with risk factors, strengths, recommendations, and actionable
    questions for the borrower.

    Parameters
    ----------
    mock : bool
        If ``True`` (default), generates mock structured reviews using
        rule-based logic. If ``False``, uses DeepSeek API (requires
        ``DEEPSEEK_API_KEY`` environment variable).
    api_key : str or None, optional
        DeepSeek API key for REAL mode. Falls back to environment variable
        ``DEEPSEEK_API_KEY`` if not provided.
    model : str
        DeepSeek model identifier (default ``"deepseek-chat"``).

    Examples
    --------
    >>> assistant = ManualReviewAssistant(mock=True)
    >>> result = assistant.review(DEFAULT_REVIEW_INPUT)
    >>> result["recommendation"]["decision"] in ("approve", "decline", "conditional_approve", "escalate")
    True
    >>> "review_summary" in result
    True
    """

    # Collection of prompt templates accessible for inspection
    PROMPT_TEMPLATES: dict[str, str] = {
        "system_prompt": SYSTEM_PROMPT,
        "structured_output_instructions": STRUCTURED_OUTPUT_INSTRUCTIONS,
        "risk_analysis_prompt": RISK_ANALYSIS_PROMPT,
    }

    def __init__(
        self,
        mock: bool = True,
        api_key: str | None = None,
        model: str = "deepseek-chat",
    ) -> None:
        self.mock = mock
        self.api_key = api_key or os.environ.get("DEEPSEEK_API_KEY")
        self.model = model
        self._client: Any = None

        # Lazy-load OpenAI client only when needed for REAL mode
        if not mock:
            self._init_real_client()

    # ── Initialization ──────────────────────────────────────────────────────

    def _init_real_client(self) -> None:
        """Initialize the DeepSeek (OpenAI-compatible) client for REAL mode."""
        try:
            from openai import OpenAI

            if not self.api_key:
                raise ValueError(
                    "DEEPSEEK_API_KEY not found. Set the environment variable or "
                    "pass api_key to constructor."
                )
            self._client = OpenAI(
                api_key=self.api_key,
                base_url="https://api.deepseek.com/v1",
            )
        except ImportError:
            raise ImportError(
                "The 'openai' package is required for REAL mode. "
                "Install it with: pip install openai"
            )

    # ── Public API ──────────────────────────────────────────────────────────

    def review(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """Complete the review for a loan application.

        Parameters
        ----------
        input_data : dict
            The full application review input with keys:
            ``app_data``, ``bureau_data``, ``cash_flow_metrics`` (or ``None``),
            ``model_result``, ``zones``, and ``gating_results``.

        Returns
        -------
        dict
            Structured review output with risk assessment, recommendations,
            red flags, and questions for the borrower.
        """
        if self.mock:
            return self.mock_review(input_data)
        return self._real_review(input_data)

    def mock_review(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """Generate a realistic mock review using rule-based logic.

        Parameters
        ----------
        input_data : dict
            The full application review input.

        Returns
        -------
        dict
            Structured mock review output.
        """
        # Merge with defaults for any missing fields
        data = self._merge_with_defaults(input_data)

        # Core analysis
        risk_factors = self._assess_risk_factors(data)
        strength_factors = self._assess_strengths(data)
        red_flags = self._assess_red_flags(data)

        # Overall risk level
        overall_risk = self._compute_overall_risk(risk_factors, data)

        # Credit & cash flow quality descriptions
        credit_quality = self._describe_credit_quality(data)
        cash_flow_quality = self._describe_cash_flow_quality(data)
        stability = self._describe_stability(data)

        # Recommendation
        recommendation = self._generate_recommendation(
            overall_risk, risk_factors, strength_factors, data
        )

        # Fraud probability estimate
        fraud_prob = self._estimate_fraud_probability(data)

        # Questions for borrower
        questions = self._generate_questions(data, risk_factors, red_flags)

        # Summary
        review_summary = self._generate_summary(data, overall_risk, recommendation)

        return {
            "review_id": f"{MOCK_REVIEW_ID_PREFIX}{uuid.uuid4().hex[:12].upper()}",
            "review_summary": review_summary,
            "risk_assessment": {
                "overall_risk": overall_risk,
                "credit_quality": credit_quality,
                "cash_flow_quality": cash_flow_quality,
                "stability": stability,
            },
            "risk_factors": risk_factors[:5],
            "strength_factors": strength_factors[:5],
            "recommendation": recommendation,
            "red_flags": red_flags,
            "questions_for_borrower": questions,
            "estimated_fraud_probability": round(fraud_prob, 2),
        }

    def mock_review_for_dashboard(self) -> list[dict[str, Any]]:
        """Generate a set of mock reviews for admin dashboard demo.

        Returns
        -------
        list[dict]
            A list of structured review dicts representing different
            applicant profiles commonly seen in a review queue.
        """
        reviews = []
        for profile_key in [
            "borderline_approve",
            "borderline_decline",
            "high_risk_approve",
            "conditional",
            "auto_approve_upgrade",
        ]:
            # Create input from profile overrides
            profile = MOCK_PROFILES[profile_key]
            input_data = deepcopy(DEFAULT_REVIEW_INPUT)
            self._apply_overrides(input_data, profile["input_overrides"])

            # Generate review
            review = self.mock_review(input_data)
            review["_profile_label"] = profile["label"]
            review["_profile_description"] = profile["description"]
            reviews.append(review)

        return reviews

    def summarize_for_human(self, output: dict[str, Any]) -> str:
        """Return a short human-readable summary of the review output.

        Suitable for display in a review queue UI, email notification,
        or dashboard widget.

        Parameters
        ----------
        output : dict
            The structured review output from :meth:`review`.

        Returns
        -------
        str
            Condensed HTML/text summary.
        """
        rec = output["recommendation"]
        risk = output["risk_assessment"]

        # Decision badge
        decision_icons = {
            "approve": "✅ APPROVE",
            "decline": "❌ DECLINE",
            "escalate": "⚠️ ESCALATE",
            "conditional_approve": "🟡 CONDITIONAL APPROVE",
        }
        decision_tag = decision_icons.get(rec["decision"], f"❓ {rec['decision'].upper()}")

        # Risk level badge
        risk_icons = {"low": "🟢", "medium": "🟡", "high": "🟠", "very_high": "🔴"}
        risk_tag = f"{risk_icons.get(risk['overall_risk'], '⚪')} {risk['overall_risk'].upper()}"

        # Top 3 risk factors
        risk_lines = ""
        for rf in output["risk_factors"][:3]:
            severity_icon = {"high": "🔴", "medium": "🟡", "low": "🟢"}
            risk_lines += f"\n  {severity_icon[rf['severity']]} **{rf['factor']}** — {rf['detail']}"

        # Top 3 strengths
        strength_lines = ""
        for sf in output["strength_factors"][:3]:
            sig_icon = {"high": "⭐", "medium": "✦", "low": "•"}
            strength_lines += f"\n  {sig_icon[sf['significance']]} **{sf['factor']}** — {sf['detail']}"

        # Conditions
        conditions_str = ""
        if rec.get("conditions"):
            conditions_str = "\n\n📋 **Conditions:**"
            for c in rec["conditions"]:
                conditions_str += f"\n  • {c}"

        # Red flags
        red_flag_str = ""
        if output.get("red_flags"):
            priority_icons = {"high": "🚨", "medium": "⚠️", "low": "ℹ️"}
            for rf in output["red_flags"][:3]:
                red_flag_str += f"\n  {priority_icons[rf['priority']]} **{rf['flag']}** — {rf['action_required']}"

        # Fraud
        fraud_str = ""
        if output.get("estimated_fraud_probability", 0) > 0.3:
            fraud_str = f"\n\n🚩 **Fraud risk:** {output['estimated_fraud_probability']:.0%}"

        return (
            f"**Manual Review #{output.get('review_id', 'N/A')}**\n"
            f"{decision_tag}  |  {risk_tag}  |  "
            f"Confidence: {rec['confidence'].upper()}\n\n"
            f"📝 {output.get('review_summary', '')}\n"
            f"\n---\n"
            f"🔻 **Risk Factors:**{risk_lines}"
            f"\n\n🔺 **Strengths:**{strength_lines}"
            f"{conditions_str}"
            f"{red_flag_str}"
            f"{fraud_str}"
            f"\n\n💰 **Recommended amount:** ${rec.get('recommended_amount', 0):,}"
            f"  |  **Rate adjustment:** {rec.get('recommended_rate_adjustment', 0):+.1f}%"
        )

    # ══════════════════════════════════════════════════════════════════════════
    # REAL mode (DeepSeek API)
    # ══════════════════════════════════════════════════════════════════════════

    def _real_review(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """Call DeepSeek API to generate a structured review.

        Parameters
        ----------
        input_data : dict
            The full application review input.

        Returns
        -------
        dict
            Structured review output from the LLM.
        """
        if not self._client:
            self._init_real_client()

        # Prepare the prompt with actual data
        prompt = RISK_ANALYSIS_PROMPT.format(
            app_data_json=json.dumps(input_data.get("app_data", {}), indent=2),
            bureau_data_json=json.dumps(input_data.get("bureau_data", {}), indent=2),
            cash_flow_json=json.dumps(
                input_data.get("cash_flow_metrics") or {}, indent=2
            ),
            model_result_json=json.dumps(input_data.get("model_result", {}), indent=2),
            zones_json=json.dumps(input_data.get("zones", {}), indent=2),
            gating_json=json.dumps(input_data.get("gating_results", {}), indent=2),
        )

        # Make the API call
        response = self._client.chat.completions.create(
            model=self.model,
            max_tokens=2000,
            messages=[
                {
                    "role": "system",
                    "content": SYSTEM_PROMPT + "\n\n" + STRUCTURED_OUTPUT_INSTRUCTIONS,
                },
                {"role": "user", "content": prompt},
            ],
        )

        # Parse structured JSON response
        try:
            result = json.loads(response.choices[0].message.content)
        except (json.JSONDecodeError, IndexError, KeyError, AttributeError) as e:
            raise ValueError(
                f"Failed to parse DeepSeek response as JSON: {e}\n"
                f"Raw response: {response.choices[0].message.content[:500]}"
            )

        # Ensure required fields
        result.setdefault("review_id", f"REAL-{uuid.uuid4().hex[:12].upper()}")
        result.setdefault("estimated_fraud_probability", 0.0)
        result.setdefault("questions_for_borrower", [])

        return result

    # ══════════════════════════════════════════════════════════════════════════
    # Mock Analysis Helpers
    # ══════════════════════════════════════════════════════════════════════════

    @staticmethod
    def _merge_with_defaults(data: dict[str, Any]) -> dict[str, Any]:
        """Fill in missing top-level keys from the default input."""
        merged = deepcopy(DEFAULT_REVIEW_INPUT)
        for key in merged:
            if key in data:
                value = data[key]
                if value is None:
                    merged[key] = None
                elif isinstance(merged[key], dict) and isinstance(value, dict):
                    merged[key].update(value)
                else:
                    merged[key] = value
        return merged

    @staticmethod
    def _apply_overrides(
        base: dict[str, Any], overrides: dict[str, Any]
    ) -> None:
        """Apply profile overrides to a base input dict (in-place)."""
        for section, section_overrides in overrides.items():
            if section in base and isinstance(base[section], dict):
                base[section].update(section_overrides)
            else:
                base[section] = section_overrides

    def _assess_risk_factors(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        """Evaluate all risk factor templates against the input data."""
        factors = []
        for template in RISK_FACTOR_TEMPLATES:
            try:
                if template["condition"](data):
                    detail = self._format_detail(template, data)
                    mitigation = self._format_mitigation(template, data)
                    factors.append(
                        {
                            "factor": template["factor"],
                            "detail": detail,
                            "severity": template["severity"],
                            "mitigation": mitigation,
                        }
                    )
            except (KeyError, TypeError, ZeroDivisionError):
                # Gracefully skip factors that can't be evaluated
                continue

        # Sort by severity (high → medium → low), then by factor name
        factors.sort(
            key=lambda f: (
                -SEVERITY_RANK.get(f["severity"], 0),
                f["factor"],
            )
        )
        return factors

    def _assess_strengths(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        """Evaluate all strength factor templates against the input data."""
        strengths = []
        for template in STRENGTH_FACTOR_TEMPLATES:
            try:
                if template["condition"](data):
                    detail = self._format_detail(template, data)
                    strengths.append(
                        {
                            "factor": template["factor"],
                            "detail": detail,
                            "significance": template["significance"],
                        }
                    )
            except (KeyError, TypeError, ZeroDivisionError):
                continue

        strengths.sort(
            key=lambda s: (
                -SIGNIFICANCE_RANK.get(s["significance"], 0),
                s["factor"],
            )
        )
        return strengths

    def _assess_red_flags(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        """Identify items needing human attention."""
        flags: list[dict[str, Any]] = []
        app = data["app_data"]
        bureau = data["bureau_data"]
        cash = data.get("cash_flow_metrics") or {}
        gating = data["gating_results"]
        zones = data["zones"]

        # Suppression flags from gating rules
        for suppression in gating.get("suppressions", []):
            if suppression.get("flagged"):
                flags.append(
                    {
                        "flag": f"Gating rule triggered: {suppression['rule']}",
                        "action_required": suppression.get(
                            "reason",
                            "Review suppression details in gating results",
                        ),
                        "priority": "high",
                    }
                )

        # Hard cut block
        if gating.get("hard_cut_blocked"):
            flags.append(
                {
                    "flag": "Hard cut rule blocked the application",
                    "action_required": "Override required for any approval — review hard cut policy",
                    "priority": "high",
                }
            )

        # Income discrepancy
        income_discrepancy = any(
            s.get("rule") == "income_discrepancy"
            for s in gating.get("suppressions", [])
        )
        if income_discrepancy:
            flags.append(
                {
                    "flag": "Income verification required",
                    "action_required": "Verify stated income with pay stubs, tax returns, or employer contact",
                    "priority": "high",
                }
            )

        # Cash flow mismatch with stated income
        if cash:
            cash_income = cash.get("cash_flow_income", 0)
            stated_income = app.get("annual_income", 0) / 12
            if stated_income > 0 and cash_income > 0:
                ratio = abs(cash_income - stated_income) / max(stated_income, cash_income)
                if ratio > 0.35:
                    flags.append(
                        {
                            "flag": f"Cash flow income (${cash_income:.0f}/mo) differs from stated "
                            f"income (${stated_income:.0f}/mo) by {ratio:.0%}",
                            "action_required": "Reconcile income sources — check for multiple income streams",
                            "priority": "high",
                        }
                    )

        # Reconsideration zone changed to decline
        if zones.get("reconsideration_zone") == "decline":
            flags.append(
                {
                    "flag": "Application declined after reconsideration",
                    "action_required": (
                        "Second look with cash flow did not improve the decision — "
                        "final human override available"
                    ),
                    "priority": "medium",
                }
            )

        # High probability of default
        pod = data["model_result"].get("probability_of_default", 0)
        if pod > 0.65:
            flags.append(
                {
                    "flag": f"Model predicts {pod:.0%} probability of default",
                    "action_required": (
                        "Only approve with strong compensating factors or additional collateral"
                    ),
                    "priority": "high",
                }
            )

        # High fraud estimate from model
        risk_score = data["model_result"].get("risk_score", 0)
        if risk_score > 75:
            flags.append(
                {
                    "flag": f"Elevated risk score ({risk_score}) from underwriting model",
                    "action_required": "Review application for potential fraud indicators",
                    "priority": "medium",
                }
            )

        # Employment stability
        if app.get("employer_tenure_months", 99) < 6 and app.get("employment_length", 0) < 1:
            flags.append(
                {
                    "flag": "Very short employment history",
                    "action_required": "Verify income stability through bank statements or employer reference",
                    "priority": "medium",
                }
            )

        flags.sort(
            key=lambda f: (
                -({"high": 3, "medium": 2, "low": 1}.get(f["priority"], 0)),
                f["flag"],
            )
        )
        return flags

    def _compute_overall_risk(
        self,
        risk_factors: list[dict[str, Any]],
        data: dict[str, Any],
    ) -> str:
        """Compute an overall risk tier from factors + data."""
        # Base score from credit data
        fico = data["bureau_data"].get("fico_score", 700)
        dti = data["bureau_data"].get("dti_ratio", 0.30)
        derog = data["bureau_data"].get("derogatory_count", 0)

        # Cash flow (if available)
        cash_score = None
        if data.get("cash_flow_metrics"):
            cash_score = data["cash_flow_metrics"].get("cash_flow_score", 50)

        # Model score
        model_score = data["model_result"].get("risk_score", 50)

        # Count high/medium risk factors
        high_count = sum(
            1 for f in risk_factors if f["severity"] == "high"
        )
        medium_count = sum(
            1 for f in risk_factors if f["severity"] == "medium"
        )

        # Decision logic
        if high_count >= 3 or (fico < 580 and not cash_score):
            return "very_high"
        elif high_count >= 2 or (fico < 600 and cash_score and cash_score < 50) or model_score > 70:
            return "high"
        elif high_count >= 1 or medium_count >= 3 or (fico < 620) or model_score > 55:
            return "medium"

        return "low"

    def _describe_credit_quality(self, data: dict[str, Any]) -> str:
        """Generate a concise credit quality description."""
        fico = data["bureau_data"].get("fico_score", 700)
        derog = data["bureau_data"].get("derogatory_count", 0)
        lines = data["bureau_data"].get("open_trade_lines", 0)
        util = data["bureau_data"].get("revolving_utilization", 0)

        fico_bucket = (
            "Excellent" if fico >= 740
            else "Good" if fico >= 680
            else "Fair" if fico >= 620
            else "Poor"
        )

        parts = [f"{fico_bucket} — FICO {fico}"]

        if lines < 4:
            parts.append("thin file")
        elif lines >= 8:
            parts.append("established file")

        if derog >= 3:
            parts.append(f"{derog} derogatory marks")
        elif derog == 1:
            parts.append("1 derogatory mark")
        elif derog == 2:
            parts.append("moderate derogatory")

        if util > 0.60:
            parts.append("high utilization")
        elif util < 0.30:
            parts.append("low utilization")

        return " — ".join(parts).capitalize()

    def _describe_cash_flow_quality(self, data: dict[str, Any]) -> str:
        """Generate a concise cash flow quality description."""
        cash = data.get("cash_flow_metrics")
        if not cash:
            return "Not available — no bank account linked"

        score = cash.get("cash_flow_score", 50)
        volatility = cash.get("income_volatility", 0.50)
        overdrafts = cash.get("overdraft_frequency", 0)
        consistency = cash.get("income_consistency", 0.5)

        if score >= 80:
            quality = "Excellent"
        elif score >= 65:
            quality = "Good"
        elif score >= 45:
            quality = "Fair"
        else:
            quality = "Poor"

        parts = [f"{quality} — score {score}"]

        if volatility < 0.10:
            parts.append("stable income")
        elif volatility > 0.25:
            parts.append("volatile income")

        if overdrafts >= 3:
            parts.append(f"{overdrafts} overdrafts")
        elif overdrafts == 0:
            parts.append("no overdrafts")

        if consistency < 0.50:
            parts.append("irregular deposits")

        return " — ".join(parts).capitalize()

    def _describe_stability(self, data: dict[str, Any]) -> str:
        """Generate a stability description from employment + housing."""
        app = data["app_data"]
        tenure = app.get("employer_tenure_months", 0)
        emp_length = app.get("employment_length", 0)
        home = app.get("home_ownership", "rent")
        status = app.get("employment_status", "unknown")

        # Employment stability
        if status == "self-employed":
            emp_desc = f"Self-employed ({tenure} months)"
        elif tenure >= 36:
            emp_desc = f"Strong — {tenure} months at current employer"
        elif tenure >= 12:
            emp_desc = f"Moderate — {tenure} months at current employer"
        else:
            emp_desc = f"Weak — only {tenure} months at current employer"

        # Housing stability
        if home in ("mortgage", "own"):
            home_desc = "Homeowner"
        else:
            home_desc = "Renter"

        # Overall
        if tenure >= 36 and home in ("mortgage", "own"):
            return f"High — {emp_desc}, {home_desc}"
        elif tenure >= 12:
            return f"Moderate — {emp_desc}, {home_desc}"
        return f"Low — {emp_desc}, {home_desc}"

    def _generate_recommendation(
        self,
        overall_risk: str,
        risk_factors: list[dict[str, Any]],
        strength_factors: list[dict[str, Any]],
        data: dict[str, Any],
    ) -> dict[str, Any]:
        """Generate the final recommendation based on all analysis."""
        app = data["app_data"]
        cash = data.get("cash_flow_metrics") or {}
        gating = data["gating_results"]
        zones = data["zones"]
        model = data["model_result"]

        loan_amount = app.get("loan_amount", 3000)
        has_strong_cf = cash.get("cash_flow_score", 0) >= 75 if cash else False
        has_weak_cf = cash.get("cash_flow_score", 0) < 45 if cash else False
        has_suppressions = len(gating.get("suppressions", [])) > 0
        hard_blocked = gating.get("hard_cut_blocked", False)
        reconsideration_decline = zones.get("reconsideration_zone") == "decline"
        pod = model.get("probability_of_default", 0.5)

        # ── Decision logic ──────────────────────────────────────────────

        conditions: list[str] = []
        decision: str
        confidence: str
        recommended_amount: int
        rate_adj: float
        rationale_parts: list[str] = []

        if hard_blocked:
            decision = "decline"
            confidence = "high"
            recommended_amount = 0
            rate_adj = 0.0
            rationale_parts.append(
                "Hard cut rules block this application. "
                "No manual override available without policy exception."
            )

        elif overall_risk == "very_high" and not has_strong_cf:
            decision = "decline"
            confidence = "high"
            recommended_amount = 0
            rate_adj = 0.0
            rationale_parts.append(
                f"Applicant presents {overall_risk} risk profile with {len(risk_factors)} "
                f"risk factors. "
                f"Probability of default ({pod:.0%}) exceeds acceptable threshold."
            )

        elif overall_risk == "high" and has_weak_cf:
            decision = "decline"
            confidence = "medium"
            recommended_amount = 0
            rate_adj = 0.0
            rationale_parts.append(
                f"High risk profile combined with weak cash flow "
                f"(score: {cash.get('cash_flow_score', 'N/A')}). "
                f"Insufficient compensating factors for approval."
            )

        elif overall_risk == "high" and has_strong_cf:
            decision = "conditional_approve"
            confidence = "medium"
            conditions.append("Reduce loan amount by 25-50% to limit exposure")
            conditions.append("Verify income with 3 months of bank statements")
            recommended_amount = min(loan_amount, int(loan_amount * 0.60))
            rate_adj = 2.0  # higher rate for higher risk
            rationale_parts.append(
                f"High bureau risk offset by strong cash flow score "
                f"({cash.get('cash_flow_score', 'N/A')}). "
                f"Conditional approval recommended with reduced amount "
                f"and income verification."
            )

        elif overall_risk == "medium":
            if reconsideration_decline:
                decision = "decline"
                confidence = "medium"
                recommended_amount = 0
                rate_adj = 0.0
                rationale_parts.append(
                    "Medium risk profile but cash flow review resulted in decline. "
                    "Manual override possible with additional documentation."
                )
            elif has_suppressions:
                decision = "conditional_approve"
                confidence = "low"
                for sup in gating.get("suppressions", []):
                    conditions.append(
                        f"Resolve {sup['rule']}: {sup.get('reason', 'Review details')}"
                    )
                conditions.append("Standard income verification required")
                recommended_amount = loan_amount
                rate_adj = 1.0
                rationale_parts.append(
                    f"Medium risk profile with gating rule flags. "
                    f"Conditional approval subject to resolution of "
                    f"{len(gating['suppressions'])} suppression(s)."
                )
            else:
                decision = "approve"
                confidence = "low"
                recommended_amount = loan_amount
                rate_adj = 0.5
                rationale_parts.append(
                    "Medium risk profile with no unresolved flags. "
                    "Standard approval with slight rate premium for risk tier."
                )

        elif overall_risk == "low":
            decision = "approve"
            confidence = "high"
            recommended_amount = loan_amount
            rate_adj = -1.0  # better rate for low risk
            rationale_parts.append(
                f"Low risk profile with strong credit and/or cash flow. "
                f"Recommended for standard approval with competitive rate."
            )

        else:
            # Fallback
            decision = "escalate"
            confidence = "low"
            recommended_amount = 0
            rate_adj = 0.0
            conditions.append("Escalate to senior underwriter for review")
            rationale_parts.append(
                "Unable to determine recommendation with available data — "
                "escalate for senior review."
            )

        # Add conditions from red flags
        if data.get("cash_flow_metrics") and cash.get("overdraft_frequency", 0) >= 3:
            conditions.append("Review overdraft root cause with borrower")

        if cash and cash.get("cash_flow_score", 50) < 50:
            conditions.append("Request 3 months of additional bank statements")

        # Deduplicate conditions
        conditions = list(dict.fromkeys(conditions))

        # Build final rationale
        rationale = (
            " ".join(rationale_parts)
            + f" Loan purpose: {app.get('loan_purpose', 'N/A')}. "
            + f"Employment: {app.get('employment_status', 'N/A')} "
            + f"({app.get('employer_tenure_months', 'N/A')} months). "
        )

        return {
            "decision": decision,
            "confidence": confidence,
            "recommended_amount": recommended_amount,
            "recommended_rate_adjustment": rate_adj,
            "conditions": conditions,
            "rationale": rationale,
        }

    def _estimate_fraud_probability(self, data: dict[str, Any]) -> float:
        """Estimate fraud probability from available signals.

        Returns a float between 0 and 1.
        """
        score = 0.0
        app = data["app_data"]
        bureau = data["bureau_data"]
        cash = data.get("cash_flow_metrics") or {}
        gating = data["gating_results"]

        # Income discrepancy
        if any(
            s.get("rule") == "income_discrepancy"
            for s in gating.get("suppressions", [])
        ):
            score += 0.20

        # Cash flow / stated income mismatch
        if cash:
            cash_income = cash.get("cash_flow_income", 0)
            stated_monthly = app.get("annual_income", 0) / 12
            if stated_monthly > 0 and cash_income > 0:
                ratio = abs(cash_income - stated_monthly) / max(stated_monthly, cash_income)
                if ratio > 0.50:
                    score += 0.25
                elif ratio > 0.30:
                    score += 0.10

        # Employment verification failed
        if any(
            s.get("rule") == "employment_verification"
            for s in gating.get("suppressions", [])
        ):
            score += 0.15

        # New credit (thin + new)
        if bureau.get("open_trade_lines", 10) < 3:
            first_year = bureau.get("first_credit_year", 2025)
            if first_year >= 2023:
                score += 0.10

        # Inconsistent state/employment info
        if app.get("employment_length", 10) < 1 and app.get("loan_amount", 0) > 4000:
            score += 0.10

        # Multiple recent inquiries
        recent_inquiries = any(
            "inquir" in f.lower() for f in bureau.get("risk_factors", [])
        )
        if recent_inquiries and bureau.get("open_trade_lines", 5) < 4:
            score += 0.10

        return min(score, 1.0)

    def _generate_questions(
        self,
        data: dict[str, Any],
        risk_factors: list[dict[str, Any]],
        red_flags: list[dict[str, Any]],
    ) -> list[str]:
        """Generate targeted questions for the borrower."""
        questions: list[str] = []
        app = data["app_data"]
        bureau = data["bureau_data"]
        cash = data.get("cash_flow_metrics") or {}
        gating = data["gating_results"]

        # Income discrepancy
        if any(
            s.get("rule") == "income_discrepancy"
            for s in gating.get("suppressions", [])
        ):
            questions.append(
                "Can you provide recent pay stubs (last 2-3 months) or tax returns "
                "to verify your stated income of "
                f"${app.get('annual_income', 0):,.0f}/year?"
            )

        # Employment verification
        if any(
            s.get("rule") == "employment_verification"
            for s in gating.get("suppressions", [])
        ):
            questions.append(
                f"Can you provide a W-2 or 1099 from {app.get('employer_name', 'your employer')} "
                "to confirm your employment?"
            )

        # Cash flow mismatch
        if cash:
            cash_income = cash.get("cash_flow_income", 0)
            stated_monthly = app.get("annual_income", 0) / 12
            if stated_monthly > 0 and cash_income > 0:
                ratio = abs(cash_income - stated_monthly) / max(stated_monthly, cash_income)
                if ratio > 0.25:
                    questions.append(
                        f"We noticed your bank account shows about "
                        f"${cash_income:.0f}/month in deposits, but you stated "
                        f"${stated_monthly:.0f}/month income. "
                        "Do you have additional income sources not reflected in "
                        "this account?"
                    )

        # High utilization
        util = bureau.get("revolving_utilization", 0)
        if util > 0.70:
            questions.append(
                f"Your credit utilization is at {util:.0%}. "
                "Do you have a plan to pay down these balances?"
            )

        # Overdrafts
        if cash and cash.get("overdraft_frequency", 0) >= 2:
            questions.append(
                "We noticed some overdraft activity on your account. "
                "Can you explain what caused these?"
            )

        # Derogatory marks
        derog = bureau.get("derogatory_count", 0)
        if derog >= 2:
            questions.append(
                f"There are {derog} derogatory marks on your credit report. "
                "Can you tell us about them? Are any related to medical debt?"
            )

        # Self-employed income documentation
        if app.get("employment_status") == "self-employed" and not cash:
            questions.append(
                "As a self-employed applicant, can you provide "
                "6 months of bank statements or a recent tax return "
                "to verify your income?"
            )

        # High loan amount relative to income
        lti = app.get("loan_amount", 0) / max(app.get("annual_income", 1), 1)
        if lti > 0.15:
            questions.append(
                f"Your requested loan of ${app.get('loan_amount', 0):,} represents "
                f"{lti:.1%} of your annual income. "
                "Are you comfortable with the monthly payment amount?"
            )

        return questions

    def _generate_summary(
        self,
        data: dict[str, Any],
        overall_risk: str,
        recommendation: dict[str, Any],
    ) -> str:
        """Generate a 2-3 sentence summary of the applicant profile."""
        app = data["app_data"]
        bureau = data["bureau_data"]
        cash = data.get("cash_flow_metrics")
        zones = data["zones"]

        name = f"{app.get('first_name', 'Applicant')} {app.get('last_name', '')}"
        fico = bureau.get("fico_score", "N/A")
        amount = app.get("loan_amount", 0)
        purpose = app.get("loan_purpose", "N/A").replace("_", " ")
        risk_tier = data["model_result"].get("risk_tier", "N/A")

        # Income description
        income_desc = f"${app.get('annual_income', 0):,}/yr "
        if app.get("employment_status") == "self-employed":
            income_desc += "(self-employed)"
        elif app.get("employment_status"):
            income_desc += f"({app['employment_status']})"

        # Cash flow description
        cf_desc = ""
        if cash:
            cf_score = cash.get("cash_flow_score", "N/A")
            cf_desc = f" CF score: {cf_score}."
        else:
            cf_desc = " No bank data linked."

        # Zone description
        zone = zones.get("original_zone", "N/A")
        reconsidered = zones.get("reconsideration_zone")
        zone_desc = f"Zone: {zone}"
        if reconsidered:
            zone_desc += f" → {reconsidered}"

        return (
            f"{name}, FICO {fico}, {income_desc}. "
            f"Requesting ${amount:,} for {purpose} ({app.get('term_months', 'N/A')}mo). "
            f"Risk tier: {risk_tier}.{cf_desc} "
            f"{zone_desc}. "
            f"Overall risk: {overall_risk}. "
            f"Recommendation: {recommendation['decision'].replace('_', ' ')}."
        )

    @staticmethod
    def _format_detail(
        template: dict[str, Any], data: dict[str, Any]
    ) -> str:
        """Format a detail template string with values from the input data."""
        tmpl = template.get("detail_tmpl", template["factor"])
        return tmpl.format(
            fico=data["bureau_data"].get("fico_score", 0),
            util=data["bureau_data"].get("revolving_utilization", 0),
            dti=data["bureau_data"].get("dti_ratio", 0),
            lines=data["bureau_data"].get("open_trade_lines", 0),
            count=data["bureau_data"].get("derogatory_count", 0),
            score=data.get("cash_flow_metrics", {}).get("cash_flow_score", 0)
            if data.get("cash_flow_metrics")
            else 0,
            vol=data.get("cash_flow_metrics", {}).get("income_volatility", 0)
            if data.get("cash_flow_metrics")
            else 0,
            cons=data.get("cash_flow_metrics", {}).get("income_consistency", 0)
            if data.get("cash_flow_metrics")
            else 0,
            months=data["app_data"].get("employer_tenure_months", 0),
            loan=data["app_data"].get("loan_amount", 0),
            lti=data["app_data"]["loan_amount"]
            / max(data["app_data"]["annual_income"], 1),
            year=data["bureau_data"].get("first_credit_year", 2025),
            age=2025 - data["bureau_data"].get("first_credit_year", 2025),
            cf_score=data.get("cash_flow_metrics", {}).get("cash_flow_score", 0)
            if data.get("cash_flow_metrics")
            else 0,
        )

    @staticmethod
    def _format_mitigation(
        template: dict[str, Any], data: dict[str, Any]
    ) -> str:
        """Format a mitigation template string with values from the input data."""
        tmpl = template.get("mitigation_tmpl", "")
        if not tmpl:
            return "Standard review process applies"
        return tmpl.format(
            fico=data["bureau_data"].get("fico_score", 0),
            util=data["bureau_data"].get("revolving_utilization", 0),
            dti=data["bureau_data"].get("dti_ratio", 0),
            lines=data["bureau_data"].get("open_trade_lines", 0),
            count=data["bureau_data"].get("derogatory_count", 0),
            score=data.get("cash_flow_metrics", {}).get("cash_flow_score", 0)
            if data.get("cash_flow_metrics")
            else 0,
            vol=data.get("cash_flow_metrics", {}).get("income_volatility", 0)
            if data.get("cash_flow_metrics")
            else 0,
            cons=data.get("cash_flow_metrics", {}).get("income_consistency", 0)
            if data.get("cash_flow_metrics")
            else 0,
            months=data["app_data"].get("employer_tenure_months", 0),
            loan=data["app_data"].get("loan_amount", 0),
            lti=data["app_data"]["loan_amount"]
            / max(data["app_data"]["annual_income"], 1),
            cf_score=data.get("cash_flow_metrics", {}).get("cash_flow_score", 0)
            if data.get("cash_flow_metrics")
            else 0,
        )


# ═══════════════════════════════════════════════════════════════════════════════
# CLI Entry Point
# ═══════════════════════════════════════════════════════════════════════════════

def _print_json(obj: Any) -> None:
    """Pretty-print a JSON object."""
    print(json.dumps(obj, indent=2, default=str))


def main() -> None:
    """Run the manual review assistant in demo mode.

    Generates mock reviews for each profile and prints the results,
    followed by human-readable summaries.
    """
    import argparse

    parser = argparse.ArgumentParser(
        description="Manual Review Assistant — Human-in-the-Loop Decision Support"
    )
    parser.add_argument(
        "--profile",
        choices=list(MOCK_PROFILES.keys()) + ["all"],
        default="all",
        help="Mock profile to review (default: all)",
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Show human-readable summary instead of full JSON",
    )
    parser.add_argument(
        "--real",
        action="store_true",
        help="Use REAL mode (DeepSeek API) instead of mock",
    )

    args = parser.parse_args()

    assistant = ManualReviewAssistant(mock=not args.real)

    if args.profile == "all":
        reviews = assistant.mock_review_for_dashboard()
        for review in reviews:
            label = review.pop("_profile_label", "Unknown")
            desc = review.pop("_profile_description", "")
            print(f"\n{'='*72}")
            print(f"  📋 {label}")
            print(f"  {desc}")
            print(f"{'='*72}")
            if args.summary:
                print(assistant.summarize_for_human(review))
            else:
                _print_json(review)
    else:
        profile = MOCK_PROFILES[args.profile]
        input_data = deepcopy(DEFAULT_REVIEW_INPUT)
        ManualReviewAssistant._apply_overrides(input_data, profile["input_overrides"])
        result = assistant.review(input_data)
        if args.summary:
            print(assistant.summarize_for_human(result))
        else:
            _print_json(result)


if __name__ == "__main__":
    main()
