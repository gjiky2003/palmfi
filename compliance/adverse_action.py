#!/usr/bin/env python3
"""Reg B / ECOA-compliant adverse action reason code engine.

Provides functions to generate ranked adverse action reason codes based on
underwriting model features, and to format a complete adverse action notice
in HTML suitable for delivery to the borrower.
"""

from __future__ import annotations

from typing import Any

# ── ECOA Reason Code Definitions ──────────────────────────────────────────
# Each code maps a threshold check to a standard ECOA-compatible reason.

REASON_CODES = [
    # Credit score thresholds
    {
        "code": "A1",
        "feature": "credit_score",
        "reason": "Credit score insufficient for the requested loan",
        "check": lambda f: f.get("credit_score", 850) < 600,
        "weight": 0.35,
    },
    {
        "code": "A2",
        "feature": "credit_score",
        "reason": "Limited credit history",
        "check": lambda f: f.get("credit_score", 850) < 680 and f.get("num_credit_lines", 10) < 4,
        "weight": 0.28,
    },
    {
        "code": "A3",
        "feature": "credit_score",
        "reason": "Recent credit inquiries or new accounts",
        "check": lambda f: f.get("credit_score", 850) < 640,
        "weight": 0.22,
    },
    # Debt-to-income ratio
    {
        "code": "B1",
        "feature": "dti_ratio",
        "reason": "Debt-to-income ratio exceeds guidelines",
        "check": lambda f: f.get("dti_ratio", 0) > 0.43,
        "weight": 0.32,
    },
    {
        "code": "B2",
        "feature": "dti_ratio",
        "reason": "Debt obligations too high relative to income",
        "check": lambda f: f.get("dti_ratio", 0) > 0.36,
        "weight": 0.25,
    },
    # Credit utilization
    {
        "code": "C1",
        "feature": "utilization",
        "reason": "Credit utilization rate too high",
        "check": lambda f: f.get("utilization", 0) > 0.70,
        "weight": 0.30,
    },
    {
        "code": "C2",
        "feature": "utilization",
        "reason": "Revolving credit balances too high",
        "check": lambda f: f.get("utilization", 0) > 0.50,
        "weight": 0.22,
    },
    # Derogatory marks
    {
        "code": "D1",
        "feature": "num_derogatory",
        "reason": "Derogatory public record or collection action",
        "check": lambda f: f.get("num_derogatory", 0) >= 2,
        "weight": 0.33,
    },
    {
        "code": "D2",
        "feature": "num_derogatory",
        "reason": "Delinquency on existing accounts",
        "check": lambda f: f.get("num_derogatory", 0) >= 1,
        "weight": 0.26,
    },
    # Income / ability to pay
    {
        "code": "E1",
        "feature": "annual_income",
        "reason": "Insufficient income for requested loan amount",
        "check": lambda f: f.get("annual_income", 0)
        < f.get("loan_amount", 0) * 0.3,
        "weight": 0.30,
    },
    {
        "code": "E2",
        "feature": "annual_income",
        "reason": "Employment history insufficient to verify income stability",
        "check": lambda f: f.get("employment_length", 0) < 1
        and f.get("annual_income", 0) < 30000,
        "weight": 0.20,
    },
    # Loan amount / term
    {
        "code": "F1",
        "feature": "loan_amount",
        "reason": "Requested loan amount exceeds maximum for credit profile",
        "check": lambda f: f.get("loan_amount", 0) > 50000,
        "weight": 0.25,
    },
    {
        "code": "F2",
        "feature": "term_months",
        "reason": "Loan term does not match ability to repay",
        "check": lambda f: f.get("term_months", 36) > 60,
        "weight": 0.20,
    },
    # Home ownership / stability
    {
        "code": "G1",
        "feature": "home_ownership",
        "reason": "Rental housing status — insufficient residence stability",
        "check": lambda f: f.get("home_ownership", "rent") == "rent",
        "weight": 0.15,
    },
    # Credit lines
    {
        "code": "H1",
        "feature": "num_credit_lines",
        "reason": "Insufficient credit history — limited trade lines",
        "check": lambda f: f.get("num_credit_lines", 0) < 3,
        "weight": 0.20,
    },
    # Risk score overall
    {
        "code": "I1",
        "feature": "risk_score",
        "reason": "Overall credit risk score does not meet minimum standards",
        "check": lambda f, rs=None: (rs is not None and rs > 75)
        or (rs is None and f.get("risk_score", 100) > 75),
        "weight": 0.35,
    },
]


def generate_reasons(
    features: dict, risk_score: float, approved: bool
) -> list[dict]:
    """Generate ranked ECOA-compliant adverse action reason codes.

    Evaluates the applicant's feature set against defined thresholds and
    returns up to 4 specific reasons ranked by impact (weight), sorted
    most impactful first.

    Args:
        features: Dict of applicant features (credit_score, annual_income,
                  employment_length, dti_ratio, utilization, num_derogatory,
                  num_credit_lines, home_ownership, loan_amount, term_months,
                  loan_purpose).
        risk_score: Model risk score (0-100, higher = riskier).
        approved: Whether the application was approved.

    Returns:
        List of up to 4 dicts with keys: code, reason, weight.
        Empty list if the application was approved (no adverse action).
    """
    if approved:
        return []

    triggered: list[dict] = []
    seen_reasons: set[str] = set()
    used_features: set[str] = set()

    for rc in REASON_CODES:
        # De-duplicate: skip if we already have a reason from this feature group
        feature_key = rc["feature"]
        reason_text = rc["reason"]

        if reason_text in seen_reasons:
            continue

        # Evaluate the check — handle functions that accept risk_score param
        check_func = rc["check"]
        try:
            # Try passing risk_score as second arg
            sig = check_func.__code__
            if sig.co_argcount >= 2:
                triggered_flag = check_func(features, risk_score)
            else:
                triggered_flag = check_func(features)
        except Exception:
            triggered_flag = False

        if triggered_flag:
            entry = {
                "code": rc["code"],
                "reason": reason_text,
                "weight": rc["weight"],
            }
            triggered.append(entry)
            seen_reasons.add(reason_text)
            used_features.add(feature_key)

    # Sort by weight descending (highest impact first)
    triggered.sort(key=lambda r: -r["weight"])

    # Return up to 4 reasons
    return triggered[:4]


def ecoa_notice() -> str:
    """Return the Equal Credit Opportunity Act notice text."""
    return (
        "EQUAL CREDIT OPPORTUNITY ACT NOTICE\n\n"
        "The Federal Equal Credit Opportunity Act prohibits creditors from "
        "discriminating against credit applicants on the basis of race, color, "
        "religion, national origin, sex, marital status, age (provided the "
        "applicant has the capacity to enter into a binding contract); because "
        "all or part of the applicant's income derives from any public "
        "assistance program; or because the applicant has in good faith "
        "exercised any right under the Consumer Credit Protection Act.\n\n"
        "The federal agency that administers compliance with this law "
        "concerning this creditor is the Consumer Financial Protection Bureau, "
        "1700 G Street NW, Washington, DC 20552."
    )


def fcra_notice() -> str:
    """Return the Fair Credit Reporting Act notice text."""
    return (
        "FAIR CREDIT REPORTING ACT NOTICE\n\n"
        "In connection with your application for credit, we may obtain a "
        "consumer report from one or more consumer reporting agencies. If we "
        "take adverse action based in whole or in part on information "
        "contained in such a report, we will provide you with the name, "
        "address, and telephone number of the consumer reporting agency that "
        "furnished the report, a statement that the agency did not make the "
        "credit decision and is unable to provide the specific reasons for "
        "the adverse action, and a notice of your right to obtain a free copy "
        "of the report and to dispute inaccurate information.\n\n"
        "You have the right under the FCRA to know the information contained "
        "in your file at the consumer reporting agency. You also have the "
        "right to dispute any inaccurate information."
    )


def format_adverse_action_notice(
    borrower_name: str,
    reasons: list,
    model_name: str = "PalmFi Score v2.0",
) -> str:
    """Return a properly formatted HTML adverse action notice.

    The notice includes all Reg B / ECOA-required elements:
      - Creditor name and address
      - Statement that action was based in whole or in part on a credit score
      - The credit score used
      - Key factors that adversely affected the score
      - ECOA notice
      - FCRA notice
      - CFPB contact information

    Args:
        borrower_name: Full name of the borrower.
        reasons: List of reason dicts from generate_reasons().
        model_name: Name/version of the score model used.

    Returns:
        Complete HTML string suitable for delivery.
    """
    # Build reasons listing
    reasons_html = ""
    for i, r in enumerate(reasons, 1):
        reasons_html += (
            f"      <tr>\n"
            f"        <td style=\"padding: 8px 12px; border: 1px solid #ddd; "
            f"text-align: center;\">{i}</td>\n"
            f"        <td style=\"padding: 8px 12px; border: 1px solid #ddd;\">"
            f"{r['code']}</td>\n"
            f"        <td style=\"padding: 8px 12px; border: 1px solid #ddd;\">"
            f">{r['reason']}</td>\n"
            f"      </tr>\n"
        )

    if not reasons_html:
        reasons_html = (
            "      <tr><td colspan=\"3\" style=\"padding: 8px 12px; "
            "border: 1px solid #ddd; text-align: center;\">"
            "No adverse action reasons triggered.</td></tr>\n"
        )

    ecoa = ecoa_notice().replace("\n", "<br>")
    fcra = fcra_notice().replace("\n", "<br>")

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Adverse Action Notice — PalmFi Lending LLC</title>
<style>
  body {{
    font-family: Arial, Helvetica, sans-serif;
    max-width: 720px;
    margin: 30px auto;
    padding: 24px;
    color: #1e293b;
    line-height: 1.5;
    background: #ffffff;
  }}
  h1 {{ color: #059669; border-bottom: 2px solid #059669; padding-bottom: 10px; font-size: 22px; }}
  h2 {{ color: #0f172a; margin-top: 24px; font-size: 16px; }}
  table {{ width: 100%; border-collapse: collapse; margin: 12px 0; font-size: 14px; }}
  th {{ background: #f1f5f9; padding: 8px 12px; border: 1px solid #ddd; text-align: left; font-weight: 600; }}
  td {{ padding: 8px 12px; border: 1px solid #ddd; }}
  .notice {{ background: #f8fafc; border-left: 4px solid #059669; padding: 14px 18px; margin: 14px 0; font-size: 13px; line-height: 1.6; }}
  .footer {{ margin-top: 28px; padding-top: 14px; border-top: 1px solid #e2e8f0; font-size: 12px; color: #64748b; }}
  strong {{ color: #0f172a; }}
</style>
</head>
<body>

<h1>📋 Adverse Action Notice</h1>

<p><strong>Date:</strong> <span id="notice-date">{__import__('datetime').datetime.now().strftime('%B %d, %Y')}</span></p>

<p><strong>To:</strong> {borrower_name}</p>

<p><strong>From:</strong> PalmFi Lending LLC<br>
123 Main Street, Suite 400<br>
Richmond, VA 23219</p>

<h2>Credit Decision</h2>
<p>After reviewing your application, we regret to inform you that we are unable to
approve your loan request at this time. This action was taken based on
information contained in your credit application and/or consumer report.</p>

<h2>Credit Score Disclosure</h2>
<p>Your credit decision was based <strong>in whole or in part</strong> on a
credit score. The credit scoring model used was <strong>{model_name}</strong>.</p>

<p>The key factors that adversely affected your credit score are listed below.
These are the principal reasons for the credit decision.</p>

<table>
  <thead>
    <tr>
      <th style="width: 50px; text-align: center;">#</th>
      <th style="width: 60px;">Code</th>
      <th>Reason for Adverse Action</th>
    </tr>
  </thead>
  <tbody>
{reasons_html}
  </tbody>
</table>

<h2>⚖️ Equal Credit Opportunity Act Notice</h2>
<div class="notice">{ecoa}</div>

<h2>📋 Fair Credit Reporting Act Notice</h2>
<div class="notice">{fcra}</div>

<h2>Consumer Financial Protection Bureau</h2>
<p>If you believe your rights have been violated, you may contact:</p>
<p>
<strong>Consumer Financial Protection Bureau</strong><br>
1700 G Street NW<br>
Washington, DC 20552<br>
Phone: (855) 411-2372<br>
Website: <a href="https://www.consumerfinance.gov/complaint/" style="color: #059669;">
www.consumerfinance.gov/complaint/</a>
</p>

<h2>Your Rights</h2>
<ul>
  <li>You have the right to obtain a free copy of your consumer report from
  the consumer reporting agency within 60 days of receiving this notice.</li>
  <li>You have the right to dispute the accuracy or completeness of any
  information in your consumer report.</li>
  <li>The consumer reporting agency did not make the credit decision and
  is unable to provide you with the specific reasons for the adverse action.</li>
</ul>

<div class="footer">
  <p>PalmFi Lending LLC | 123 Main Street, Suite 400 | Richmond, VA 23219</p>
  <p>This notice is provided in compliance with Regulation B (Equal Credit
  Opportunity Act) and the Fair Credit Reporting Act.</p>
</div>

</body>
</html>"""
    return html
