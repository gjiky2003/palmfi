#!/usr/bin/env python3
"""SHAP-based adverse action engine with ECOA / Reg B-compliant HTML notices.

Uses SHAP feature contributions dynamically to rank adverse action reasons,
replacing the static threshold-based approach in :mod:`compliance.adverse_action`.

Usage
-----
    from compliance.shap_adverse_action import ShapAdverseAction

    # Feature names must match model training order
    FEATURES = [
        'credit_score', 'dti_ratio', 'utilization', 'num_derogatory',
        'num_credit_lines', 'age', 'log_income', 'employment_length',
        'log_loan_amount', 'home_rent', 'home_mortgage', 'home_own',
    ]
    engine = ShapAdverseAction(FEATURES)

    reasons = engine.generate(
        shap_values_dict={'base_value': ..., 'values': [...], 'prediction': ...},
        app_data={'credit_score': 580, 'dti_ratio': 0.45, ...},
        risk_score=82,
        approved=False,
    )

    html = generate_adverse_action_notice(
        borrower_name='Jane Doe',
        reasons=reasons,
        credit_score=580,
    )
"""

from __future__ import annotations

import datetime
from typing import Any, Optional

# ── ECOA reason code mapping ────────────────────────────────────────────────
# Maps model feature names to ECOA-compatible reason strings.
# Features mapped to None are excluded from adverse action reporting per ECOA:
#   - 'age'            : Prohibited (ECOA § 701(b) — age discrimination for 62+)
#   - 'home_mortgage'  : Neutral/most common — not adverse
#   - 'home_own'       : Positive signal — not adverse

FEATURE_TO_REASON: dict[str, str | None] = {
    "credit_score": "Credit score insufficient for requested loan amount",
    "dti_ratio": "Debt-to-income ratio exceeds guidelines",
    "utilization": "Credit utilization rate too high",
    "num_derogatory": "Derogatory public record or collection action",
    "num_credit_lines": "Insufficient number of active credit accounts",
    "age": None,  # Excluded — ECOA prohibits age discrimination for 62+
    "log_income": "Income insufficient for requested loan amount",
    "employment_length": "Employment history insufficient",
    "log_loan_amount": "Loan amount requested exceeds guidelines",
    "home_rent": "Stability of residence not established",
    "home_mortgage": None,  # Neutral (most common)
    "home_own": None,  # Positive signal
}

# Reason codes for reportable features
FEATURE_CODE: dict[str, str] = {
    "credit_score": "A1",
    "dti_ratio": "B1",
    "utilization": "C1",
    "num_derogatory": "D1",
    "num_credit_lines": "H1",
    "log_income": "E1",
    "employment_length": "E2",
    "log_loan_amount": "F1",
    "home_rent": "G1",
}

# Default relative importance weights (used as tiebreaker when SHAP values
# are extremely close; also normalised into the output).
FEATURE_WEIGHT: dict[str, float] = {
    "credit_score": 0.35,
    "dti_ratio": 0.32,
    "utilization": 0.30,
    "num_derogatory": 0.33,
    "num_credit_lines": 0.20,
    "log_income": 0.30,
    "employment_length": 0.20,
    "log_loan_amount": 0.25,
    "home_rent": 0.15,
}


class ShapAdverseAction:
    """SHAP-driven adverse action reason engine.

    Uses SHAP feature contributions to identify the features that most
    strongly pushed a declined application toward default, then maps them
    to ECOA-compliant reason codes.

    Parameters
    ----------
    feature_names : list of str
        Ordered list of feature names matching the model's training order.
    """

    def __init__(self, feature_names: list[str]) -> None:
        self.feature_names = list(feature_names)
        # Pre-build a lookup of feature name → index
        self._feature_index: dict[str, int] = {
            name: i for i, name in enumerate(feature_names)
        }

    # ── Public API ──────────────────────────────────────────────────────────

    def generate(
        self,
        shap_values_dict: dict[str, Any],
        app_data: dict[str, Any],
        risk_score: float,
        approved: bool,
    ) -> list[dict[str, Any]]:
        """Generate up to 4 ranked adverse action reasons from SHAP values.

        For **declined** applications, features with *high positive* SHAP
        values (pushing the prediction toward default) are ranked. The top
        four are mapped to ECOA reason codes.

        For **approved** applications an empty list is returned (no adverse
        action required).

        Parameters
        ----------
        shap_values_dict : dict
            Output from a SHAP explainer. Expected keys:
            - ``'values'`` : list of dicts with keys ``feature``, ``value``,
              ``shap_value``.
            - ``'base_value'`` : float (log-odds baseline).
            - ``'prediction'`` : float (probability of default, 0-1).

        app_data : dict
            Raw application data dict containing feature values. Feature
            keys should match model feature names (e.g. ``credit_score``,
            ``dti_ratio``, ``annual_income``).

        risk_score : float
            Model risk score (0-100, higher = riskier).

        approved : bool
            Whether the application was approved.

        Returns
        -------
        list of dict
            Up to 4 reason dicts, each with:
            - ``code`` : str — ECOA reason code (e.g. ``'A1'``)
            - ``feature`` : str — model feature name
            - ``reason`` : str — human-readable ECOA reason
            - ``shap_value`` : float — SHAP contribution value
            - ``actual_value`` : float — the applicant's feature value
            - ``weight`` : float — normalised relative importance (0-1)
        """
        if approved:
            return []

        values_list: list[dict[str, Any]] = shap_values_dict.get("values", [])

        # Filter to reportable features with positive SHAP (push toward default)
        candidates: list[dict[str, Any]] = []
        for entry in values_list:
            feature = entry["feature"]
            reason_text = FEATURE_TO_REASON.get(feature)

            # Skip excluded/neutral features
            if reason_text is None:
                continue

            shap_val = entry["shap_value"]

            # Only features pushing *toward* default (positive SHAP for
            # probability-of-default model)
            if shap_val <= 0.0:
                continue

            actual = self._resolve_actual_value(feature, app_data)

            candidates.append(
                {
                    "code": FEATURE_CODE.get(feature, "Z1"),
                    "feature": feature,
                    "reason": reason_text,
                    "shap_value": shap_val,
                    "actual_value": actual,
                    "weight": FEATURE_WEIGHT.get(feature, 0.10),
                }
            )

        # Sort by SHAP value descending (highest contribution first)
        candidates.sort(key=lambda r: -r["shap_value"])

        # Take top 4
        top = candidates[:4]

        # Normalise weights within the selected set
        total_weight = sum(r["weight"] for r in top)
        if total_weight > 0:
            for r in top:
                r["weight"] = round(r["weight"] / total_weight, 4)

        return top

    # ── Internals ───────────────────────────────────────────────────────────

    def _resolve_actual_value(
        self, feature: str, app_data: dict[str, Any]
    ) -> float | str | None:
        """Resolve the raw applicant value for a given feature.

        Handles:
        - Direct key matches (``credit_score``, ``dti_ratio``, etc.)
        - Derived log features (``log_income`` → ``annual_income``)
        - One-hot encoded booleans (``home_rent``, ``home_mortgage``,
          ``home_own``)
        """
        # Direct key match
        if feature in app_data:
            val = app_data[feature]
            return float(val) if isinstance(val, (int, float)) else val

        # Log-derived features
        if feature == "log_income":
            income = app_data.get("annual_income", 0)
            return float(income)
        if feature == "log_loan_amount":
            loan = app_data.get("loan_amount", 0)
            return float(loan)

        # Home ownership one-hot -> original categorical
        if feature in ("home_rent", "home_mortgage", "home_own"):
            raw = app_data.get("home_ownership", "")
            return raw or feature

        return None


# ═══════════════════════════════════════════════════════════════════════════════
#  ECOA / FCRA notice text
# ═══════════════════════════════════════════════════════════════════════════════

def ecoa_notice() -> str:
    """Return the Equal Credit Opportunity Act notice text (Reg B)."""
    return (
        "The federal Equal Credit Opportunity Act prohibits creditors from "
        "discriminating against credit applicants on the basis of race, color, "
        "religion, national origin, sex, marital status, age (provided the "
        "applicant has the capacity to enter into a binding contract); because "
        "all or part of the applicant's income derives from any public "
        "assistance program; or because the applicant has in good faith "
        "exercised any right under the Consumer Credit Protection Act."
    )


def fcra_notice() -> str:
    """Return the Fair Credit Reporting Act notice text."""
    return (
        "The federal Fair Credit Reporting Act requires us to tell you that "
        "we obtained information from a consumer reporting agency in connection "
        "with your application. If we take adverse action based in whole or in "
        "part on information from a consumer report, you have the right to: "
        "(1) obtain a free copy of your consumer report from the agency within "
        "60 days of receiving this notice; and (2) dispute the accuracy or "
        "completeness of any information in the report. The consumer reporting "
        "agency did not make the credit decision and is unable to provide you "
        "with the specific reasons for the adverse action."
    )


# ═══════════════════════════════════════════════════════════════════════════════
#  HTML Notice Generation
# ═══════════════════════════════════════════════════════════════════════════════

def generate_adverse_action_notice(
    borrower_name: str,
    reasons: list[dict[str, Any]],
    credit_score: int,
    model_name: str = "PalmFi v2.0",
    date: str | None = None,
) -> str:
    """Generate a complete Reg B / ECOA-compliant adverse action notice in HTML.

    The notice includes all elements required by 12 CFR § 1002.9:

    - Creditor name and address
    - Statement of adverse action
    - Specific reasons for the action (up to 4)
    - Credit score disclosure (score, date, range, key factors)
    - ECOA notice
    - FCRA notice
    - CFPB contact information
    - Regulatory citation

    Parameters
    ----------
    borrower_name : str
        Full name of the borrower.
    reasons : list of dict
        Reasons generated by :meth:`ShapAdverseAction.generate`.
    credit_score : int
        The borrower's credit score (300-850).
    model_name : str
        Name/version of the credit scoring model.
    date : str, optional
        Notice date string (default: today's date).

    Returns
    -------
    str
        Complete HTML document.
    """
    if date is None:
        date = datetime.datetime.now().strftime("%B %d, %Y")

    # ── Reasons table rows ──
    reasons_rows = ""
    if reasons:
        for i, r in enumerate(reasons, 1):
            actual = r.get("actual_value", "")
            shap_str = f"{r['shap_value']:.4f}" if isinstance(r.get('shap_value'), (int, float)) else "—"
            reasons_rows += f"""\
      <tr>
        <td style="padding:8px 12px;border:1px solid #ddd;text-align:center;vertical-align:top;">{i}</td>
        <td style="padding:8px 12px;border:1px solid #ddd;vertical-align:top;">
          <span class="reason-code">{r['code']}</span>
        </td>
        <td style="padding:8px 12px;border:1px solid #ddd;vertical-align:top;">
          <strong>{r['reason']}</strong>
          <div class="reason-detail">(Value: <code>{actual}</code> &middot; Impact: {shap_str})</div>
        </td>
      </tr>
"""
    else:
        reasons_rows = """\
      <tr>
        <td colspan="3" style="padding:12px;border:1px solid #ddd;text-align:center;color:#64748b;">
          No adverse action reasons required.
        </td>
      </tr>
"""

    # ── Credit score key factors ──
    score_key_factors = ""
    for r in reasons:
        fname = r.get("feature", "")
        if fname in ("credit_score",):
            continue  # don't list credit_score itself as a "key factor" in the score box
        code = r.get("code", "")
        reason_text = r.get("reason", "")
        score_key_factors += (
            f"      <li><strong>{code}</strong> — {reason_text}</li>\n"
        )
    if not score_key_factors:
        score_key_factors = "      <li>Credit score insufficient</li>\n"

    # ── Assemble HTML ──
    ecoa_body = ecoa_notice()
    fcra_body = fcra_notice()

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Adverse Action Notice — PalmFi Lending LLC</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: Georgia, 'Times New Roman', Times, serif;
    max-width: 750px;
    margin: 0 auto;
    padding: 0;
    color: #1e293b;
    background: #f8fafc;
    line-height: 1.6;
  }}
  .container {{
    background: #ffffff;
    margin: 24px 16px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.12), 0 1px 2px rgba(0,0,0,0.08);
    border-radius: 4px;
    overflow: hidden;
  }}
  .header {{
    background: #1a365d;
    color: #ffffff;
    padding: 28px 32px 20px 32px;
    border-bottom: 4px solid #2b6cb0;
  }}
  .header h1 {{
    font-size: 22px;
    font-weight: 700;
    letter-spacing: 0.5px;
    margin-bottom: 4px;
  }}
  .header .subtitle {{
    font-size: 13px;
    opacity: 0.85;
    margin-top: 2px;
  }}
  .header .creditor-info {{
    font-size: 13px;
    opacity: 0.80;
    margin-top: 6px;
  }}
  .content {{
    padding: 28px 32px;
  }}
  h2 {{
    font-size: 18px;
    color: #1a365d;
    margin-top: 24px;
    margin-bottom: 10px;
    padding-bottom: 6px;
    border-bottom: 1px solid #e2e8f0;
  }}
  h2:first-of-type {{ margin-top: 0; }}
  h3 {{
    font-size: 15px;
    color: #2d3748;
    margin-top: 18px;
    margin-bottom: 8px;
  }}
  p {{ margin-bottom: 10px; }}
  table {{
    width: 100%;
    border-collapse: collapse;
    margin: 12px 0 16px 0;
    font-size: 14px;
  }}
  th {{
    background: #edf2f7;
    padding: 10px 12px;
    border: 1px solid #cbd5e1;
    text-align: left;
    font-weight: 600;
    font-size: 13px;
    color: #1a365d;
  }}
  td {{
    padding: 10px 12px;
    border: 1px solid #cbd5e1;
    font-size: 14px;
  }}
  .reason-code {{
    display: inline-block;
    background: #1a365d;
    color: #ffffff;
    font-size: 11px;
    font-weight: 700;
    padding: 2px 8px;
    border-radius: 3px;
    font-family: Arial, Helvetica, sans-serif;
  }}
  .reason-detail {{
    font-size: 12px;
    color: #64748b;
    margin-top: 4px;
  }}
  .reason-detail code {{
    background: #f1f5f9;
    padding: 1px 5px;
    border-radius: 2px;
    font-size: 12px;
  }}
  .score-box {{
    background: #f7fafc;
    border: 1px solid #cbd5e1;
    border-radius: 4px;
    padding: 16px 20px;
    margin: 12px 0 16px 0;
  }}
  .score-box table {{
    margin: 0;
  }}
  .score-box th {{
    background: transparent;
    border: none;
    padding: 4px 8px 4px 0;
    font-weight: 600;
    width: 180px;
    color: #475569;
  }}
  .score-box td {{
    border: none;
    padding: 4px 0;
  }}
  .score-value {{
    font-size: 28px;
    font-weight: 700;
    color: #1a365d;
  }}
  .notice-box {{
    background: #f7fafc;
    border-left: 4px solid #2b6cb0;
    padding: 14px 18px;
    margin: 12px 0;
    font-size: 13px;
    line-height: 1.7;
    color: #334155;
  }}
  .notice-box strong {{
    color: #1a365d;
  }}
  .cfpb-info {{
    background: #f0f4f8;
    padding: 14px 18px;
    margin: 12px 0;
    border-radius: 4px;
    font-size: 13px;
  }}
  .cfpb-info a {{
    color: #2b6cb0;
    text-decoration: underline;
  }}
  .footer {{
    margin-top: 24px;
    padding: 16px 32px;
    border-top: 1px solid #e2e8f0;
    font-size: 11px;
    color: #64748b;
    line-height: 1.6;
    text-align: center;
  }}
  .footer strong {{
    color: #475569;
  }}
  ul, ol {{
    margin-left: 20px;
    margin-bottom: 12px;
  }}
  li {{ margin-bottom: 4px; font-size: 14px; }}
  .reg-citation {{
    font-size: 12px;
    color: #64748b;
    font-style: italic;
    margin-top: 16px;
    padding-top: 12px;
    border-top: 1px solid #e2e8f0;
  }}
</style>
</head>
<body>

<div class="container">

  <!-- HEADER -->
  <div class="header">
    <h1>NOTICE OF ADVERSE ACTION</h1>
    <div class="subtitle">PalmFi Lending LLC &mdash; Regulation B &sect; 1002.9</div>
    <div class="creditor-info">
      123 Main Street, Suite 400 &middot; Richmond, VA 23219<br>
      (800) 555-0199 &middot; www.palmfi.com
    </div>
  </div>

  <!-- CONTENT -->
  <div class="content">

    <p><strong>Date:</strong> {date}</p>
    <p><strong>To:</strong> {borrower_name}</p>

    <h2>Notice of Adverse Action</h2>
    <p>
      We are unable to approve your application for the following reason(s):
    </p>

    <!-- REASONS TABLE -->
    <table>
      <thead>
        <tr>
          <th style="width:40px;text-align:center;">#</th>
          <th style="width:70px;">Code</th>
          <th>Reason</th>
        </tr>
      </thead>
      <tbody>
{reasons_rows}
      </tbody>
    </table>

    <!-- CREDIT SCORE DISCLOSURE -->
    <h2>Credit Score Disclosure</h2>
    <p>
      Your credit decision was based <strong>in whole or in part</strong> on a
      credit score. The credit scoring model used was <strong>{model_name}</strong>.
    </p>

    <div class="score-box">
      <table>
        <tr>
          <th>Credit Score</th>
          <td><span class="score-value">{credit_score}</span></td>
        </tr>
        <tr>
          <th>Date</th>
          <td>{date}</td>
        </tr>
        <tr>
          <th>Score Range</th>
          <td>300 – 850</td>
        </tr>
        <tr>
          <th style="vertical-align:top;">Key Factors</th>
          <td>
            <ol style="margin:0;padding-left:18px;">
{score_key_factors}            </ol>
          </td>
        </tr>
      </table>
    </div>

    <!-- ECOA NOTICE -->
    <h2>Equal Credit Opportunity Act Notice</h2>
    <div class="notice-box">
      <strong>ECOA:</strong> {ecoa_body}
    </div>

    <!-- FCRA NOTICE -->
    <h2>Fair Credit Reporting Act Notice</h2>
    <div class="notice-box">
      <strong>FCRA:</strong> {fcra_body}
    </div>

    <!-- CFPB -->
    <h2>Consumer Financial Protection Bureau</h2>
    <div class="cfpb-info">
      <p>If you believe your rights have been violated, you may contact:</p>
      <p>
        <strong>Consumer Financial Protection Bureau</strong><br>
        1700 G Street NW &middot; Washington, DC 20552<br>
        Phone: <strong>(855) 411-2372</strong><br>
        Website: <a href="https://www.consumerfinance.gov/complaint/">
          www.consumerfinance.gov/complaint/</a>
      </p>
    </div>

    <!-- YOUR RIGHTS -->
    <h2>Your Rights Under the FCRA</h2>
    <ul>
      <li>You have the right to obtain a <strong>free copy</strong> of your
        consumer report from the consumer reporting agency within 60 days of
        receiving this notice.</li>
      <li>You have the right to <strong>dispute</strong> the accuracy or
        completeness of any information in your consumer report.</li>
      <li>The consumer reporting agency did not make the credit decision and
        is unable to provide you with the specific reasons for the adverse
        action.</li>
    </ul>

    <div class="reg-citation">
      This notice is an adverse action notice under Regulation B
      (12 CFR &sect; 1002.9) implementing the Equal Credit Opportunity Act
      (15 U.S.C. &sect; 1691 &ndash; 1691f).
    </div>

  </div>

  <!-- FOOTER -->
  <div class="footer">
    <strong>PalmFi Lending LLC</strong> &nbsp;|&nbsp;
    123 Main Street, Suite 400, Richmond, VA 23219 &nbsp;|&nbsp;
    (800) 555-0199<br>
    NMLS #1234567 &nbsp;|&nbsp;
    &copy; {datetime.datetime.now().year} PalmFi Lending LLC. All rights reserved.
  </div>

</div>

</body>
</html>"""
    return html


# ═══════════════════════════════════════════════════════════════════════════════
#  Decision HTML formatter
# ═══════════════════════════════════════════════════════════════════════════════

def format_decision_html(decision: dict[str, Any]) -> str:
    """Format a full underwriting decision dict as HTML-friendly output.

    Parameters
    ----------
    decision : dict
        Decision dict from an underwriting scorer (e.g.
        :meth:`XGBoostScorer.score_application`). Expected keys include
        ``approved``, ``risk_score``, ``risk_tier``, ``risk_label``,
        ``interest_rate``, ``monthly_payment``, ``probability_of_default``,
        ``explanation``, ``max_loan_amount``, ``recommended_term_months``,
        ``cash_flow_adjusted``.

    Returns
    -------
    str
        HTML snippet suitable for embedding in a dashboard or notification.
    """
    approved = decision.get("approved", False)
    status_icon = "&#9989;" if approved else "&#10060;"
    status_label = "APPROVED" if approved else "DECLINED"
    status_color = "#16a34a" if approved else "#dc2626"

    # Risk tier badge colour
    tier_colors = {
        "A": "#16a34a",
        "B": "#22c55e",
        "C": "#eab308",
        "D": "#f97316",
        "E": "#dc2626",
    }
    risk_tier = decision.get("risk_tier", "E")
    tier_color = tier_colors.get(risk_tier, "#64748b")

    interest = decision.get("interest_rate", 0)
    monthly = decision.get("monthly_payment", 0)
    prob_def = decision.get("probability_of_default", 0)
    max_loan = decision.get("max_loan_amount", 0)
    recommended_term = decision.get("recommended_term_months", 36)
    cash_flow_adj = decision.get("cash_flow_adjusted", False)

    # Explanation factors
    explanation = decision.get("explanation", {})
    factors = explanation.get("top_factors", [])
    summary = explanation.get("summary", "")

    factors_html = ""
    for f in factors:
        icon = {"positive": "&#9650;", "neutral": "&#9644;", "negative": "&#9660;"}.get(
            f.get("impact", "neutral"), "&#9644;"
        )
        color = {
            "positive": "#16a34a",
            "neutral": "#eab308",
            "negative": "#dc2626",
        }.get(f.get("impact", "neutral"), "#64748b")
        factors_html += (
            f'      <tr>\n'
            f'        <td style="padding:6px 10px;border:1px solid #e2e8f0;'
            f'font-size:13px;">{f.get("factor", "")}</td>\n'
            f'        <td style="padding:6px 10px;border:1px solid #e2e8f0;'
            f'font-size:13px;color:{color};">{icon} {f.get("impact", "")}</td>\n'
            f'        <td style="padding:6px 10px;border:1px solid #e2e8f0;'
            f'font-size:13px;">{f.get("description", "")}</td>\n'
            f'      </tr>\n'
        )

    html = f"""\
<div style="font-family:Georgia,'Times New Roman',Times,serif;max-width:680px;
            margin:0 auto;background:#ffffff;border:1px solid #e2e8f0;
            border-radius:6px;overflow:hidden;">

  <!-- Status bar -->
  <div style="padding:20px 24px;background:{status_color};color:#ffffff;">
    <span style="font-size:28px;font-weight:700;">{status_icon} {status_label}</span>
    <span style="float:right;font-size:14px;opacity:0.9;">
      Risk Score: {decision.get("risk_score", "—")}/100
    </span>
  </div>

  <div style="padding:20px 24px;">

    <!-- Summary -->
    <p style="font-size:14px;color:#475569;margin-bottom:16px;">
      {summary}
    </p>

    <!-- Key metrics -->
    <table style="width:100%;border-collapse:collapse;margin-bottom:16px;">
      <tr>
        <td style="padding:8px 12px;border:1px solid #e2e8f0;font-size:13px;
                   font-weight:600;color:#1e293b;width:180px;">Risk Tier</td>
        <td style="padding:8px 12px;border:1px solid #e2e8f0;font-size:13px;
                   color:{tier_color};font-weight:700;">
          {risk_tier} — {decision.get("risk_label", "")}
        </td>
      </tr>
      <tr>
        <td style="padding:8px 12px;border:1px solid #e2e8f0;font-size:13px;
                   font-weight:600;color:#1e293b;">Interest Rate</td>
        <td style="padding:8px 12px;border:1px solid #e2e8f0;font-size:13px;">
          {interest:.2f}%
        </td>
      </tr>
      <tr>
        <td style="padding:8px 12px;border:1px solid #e2e8f0;font-size:13px;
                   font-weight:600;color:#1e293b;">Monthly Payment</td>
        <td style="padding:8px 12px;border:1px solid #e2e8f0;font-size:13px;">
          ${monthly:,.2f}
        </td>
      </tr>
      <tr>
        <td style="padding:8px 12px;border:1px solid #e2e8f0;font-size:13px;
                   font-weight:600;color:#1e293b;">Probability of Default</td>
        <td style="padding:8px 12px;border:1px solid #e2e8f0;font-size:13px;">
          {prob_def*100:.2f}%
        </td>
      </tr>
      <tr>
        <td style="padding:8px 12px;border:1px solid #e2e8f0;font-size:13px;
                   font-weight:600;color:#1e293b;">Max Loan Amount</td>
        <td style="padding:8px 12px;border:1px solid #e2e8f0;font-size:13px;">
          ${max_loan:,.2f}
        </td>
      </tr>
      <tr>
        <td style="padding:8px 12px;border:1px solid #e2e8f0;font-size:13px;
                   font-weight:600;color:#1e293b;">Recommended Term</td>
        <td style="padding:8px 12px;border:1px solid #e2e8f0;font-size:13px;">
          {recommended_term} months
        </td>
      </tr>
      <tr>
        <td style="padding:8px 12px;border:1px solid #e2e8f0;font-size:13px;
                   font-weight:600;color:#1e293b;">Cash Flow Adjusted</td>
        <td style="padding:8px 12px;border:1px solid #e2e8f0;font-size:13px;
                   color:{'#16a34a' if cash_flow_adj else '#64748b'};">
          {'&#10003; Yes' if cash_flow_adj else '&#10007; No'}
        </td>
      </tr>
    </table>

    <!-- Factors -->
    <h4 style="margin:12px 0 8px 0;font-size:15px;color:#1a365d;">Factor Analysis</h4>
    <table style="width:100%;border-collapse:collapse;margin-bottom:8px;">
      <thead>
        <tr>
          <th style="padding:8px 10px;border:1px solid #e2e8f0;background:#f1f5f9;
                     font-size:12px;font-weight:600;text-align:left;color:#475569;">
            Factor</th>
          <th style="padding:8px 10px;border:1px solid #e2e8f0;background:#f1f5f9;
                     font-size:12px;font-weight:600;text-align:left;color:#475569;">
            Impact</th>
          <th style="padding:8px 10px;border:1px solid #e2e8f0;background:#f1f5f9;
                     font-size:12px;font-weight:600;text-align:left;color:#475569;">
            Description</th>
        </tr>
      </thead>
      <tbody>
{factors_html}      </tbody>
    </table>

  </div>
</div>"""
    return html


# ═══════════════════════════════════════════════════════════════════════════════
#  DOCTEST-style tests
# ═══════════════════════════════════════════════════════════════════════════════

def _run_tests() -> None:
    """Run DOCTEST-style tests for the module."""
    import sys

    print("=" * 72)
    print("SHAP ADVERSE ACTION ENGINE — DOCTEST")
    print("=" * 72)

    # ── Test data ──
    FEATURES = [
        "credit_score", "dti_ratio", "utilization", "num_derogatory",
        "num_credit_lines", "age", "log_income", "employment_length",
        "log_loan_amount", "home_rent", "home_mortgage", "home_own",
    ]

    engine = ShapAdverseAction(FEATURES)

    # Simulated SHAP values for a HIGH-RISK (declined) applicant
    # Positive SHAP = pushes toward default
    shap_declined = {
        "base_value": -0.523,
        "prediction": 0.89,
        "values": [
            {"feature": "credit_score", "value": 580.0, "shap_value": 0.8241},
            {"feature": "dti_ratio", "value": 0.51, "shap_value": 0.4523},
            {"feature": "utilization", "value": 0.88, "shap_value": 0.3120},
            {"feature": "num_derogatory", "value": 3.0, "shap_value": 0.2978},
            {"feature": "num_credit_lines", "value": 2.0, "shap_value": 0.1842},
            {"feature": "age", "value": 28.0, "shap_value": 0.0912},
            {"feature": "log_income", "value": 4.301, "shap_value": 0.1547},
            {"feature": "employment_length", "value": 0.5, "shap_value": 0.1211},
            {"feature": "log_loan_amount", "value": 4.699, "shap_value": 0.0987},
            {"feature": "home_rent", "value": 1.0, "shap_value": 0.0678},
            {"feature": "home_mortgage", "value": 0.0, "shap_value": -0.0312},
            {"feature": "home_own", "value": 0.0, "shap_value": -0.0215},
        ],
    }

    # Simulated SHAP values for a LOW-RISK (approved) applicant
    shap_approved = {
        "base_value": -0.523,
        "prediction": 0.12,
        "values": [
            {"feature": "credit_score", "value": 780.0, "shap_value": -0.5341},
            {"feature": "dti_ratio", "value": 0.18, "shap_value": -0.2123},
            {"feature": "utilization", "value": 0.15, "shap_value": -0.1880},
            {"feature": "num_derogatory", "value": 0.0, "shap_value": -0.1578},
            {"feature": "num_credit_lines", "value": 12.0, "shap_value": -0.1042},
            {"feature": "age", "value": 42.0, "shap_value": -0.0512},
            {"feature": "log_income", "value": 4.903, "shap_value": -0.1147},
            {"feature": "employment_length", "value": 8.0, "shap_value": -0.0811},
            {"feature": "log_loan_amount", "value": 4.0, "shap_value": -0.0587},
            {"feature": "home_rent", "value": 0.0, "shap_value": -0.0218},
            {"feature": "home_mortgage", "value": 1.0, "shap_value": -0.0312},
            {"feature": "home_own", "value": 0.0, "shap_value": -0.0215},
        ],
    }

    app_data_declined = {
        "credit_score": 580,
        "dti_ratio": 0.51,
        "utilization": 0.88,
        "num_derogatory": 3,
        "num_credit_lines": 2,
        "age": 28,
        "annual_income": 20000,
        "employment_length": 0.5,
        "loan_amount": 50000,
        "home_ownership": "rent",
    }

    app_data_approved = {
        "credit_score": 780,
        "dti_ratio": 0.18,
        "utilization": 0.15,
        "num_derogatory": 0,
        "num_credit_lines": 12,
        "age": 42,
        "annual_income": 80000,
        "employment_length": 8,
        "loan_amount": 10000,
        "home_ownership": "mortgage",
    }

    # ── Test 1: Approved returns empty list ──
    print("\n[Test 1] Approved application -> empty list")
    reasons_approved = engine.generate(
        shap_approved, app_data_approved, risk_score=22, approved=True
    )
    assert len(reasons_approved) == 0, (
        f"Expected 0 reasons for approved, got {len(reasons_approved)}"
    )
    print("  PASS: No reasons for approved application")

    # ── Test 2: Declined returns up to 4 ranked reasons ──
    print("\n[Test 2] Declined application -> 4 ranked reasons")
    reasons_declined = engine.generate(
        shap_declined, app_data_declined, risk_score=82, approved=False
    )
    assert len(reasons_declined) <= 4, (
        f"Expected <=4 reasons, got {len(reasons_declined)}"
    )
    assert len(reasons_declined) > 0, "Expected at least 1 reason for declined"
    print(f"  Returned {len(reasons_declined)} reasons")
    for i, r in enumerate(reasons_declined):
        print(f"    {i+1}. [{r['code']}] {r['feature']}: {r['reason']}")
        print(f"       SHAP={r['shap_value']:.4f}, "
              f"actual={r['actual_value']}, weight={r['weight']:.4f}")

    # Verify ordering by SHAP descending
    for i in range(len(reasons_declined) - 1):
        assert (
            reasons_declined[i]["shap_value"]
            >= reasons_declined[i + 1]["shap_value"]
        ), f"Reasons not sorted by SHAP at index {i}"
    print("  PASS: Reasons sorted by SHAP descending")

    # ── Test 3: Excluded features not in reasons ──
    print("\n[Test 3] Excluded features ('age', 'home_mortgage', 'home_own') absent")
    for r in reasons_declined:
        assert r["feature"] not in ("age", "home_mortgage", "home_own"), (
            f"Excluded feature '{r['feature']}' found in reasons"
        )
    print("  PASS: No excluded features in reasons")

    # ── Test 4: Each reason has required fields ──
    print("\n[Test 4] Required fields present in each reason")
    required_fields = {"code", "feature", "reason", "shap_value", "actual_value", "weight"}
    for r in reasons_declined:
        missing = required_fields - set(r.keys())
        assert not missing, f"Missing fields: {missing} in {r}"
    print("  PASS: All required fields present")

    # ── Test 5: HTML notice generation ──
    print("\n[Test 5] HTML adverse action notice generation")
    cs_value = 580
    html = generate_adverse_action_notice(
        borrower_name="Jane Doe",
        reasons=reasons_declined,
        credit_score=cs_value,
        model_name="PalmFi v2.0",
    )
    assert isinstance(html, str), "HTML must be a string"
    assert "NOTICE OF ADVERSE ACTION" in html, "Missing notice title"
    assert "PalmFi Lending LLC" in html, "Missing creditor name"
    assert "Jane Doe" in html, "Missing borrower name"
    assert "Regulation B" in html, "Missing Reg B citation"
    assert "ECOA" in html, "Missing ECOA notice"
    assert "FCRA" in html, "Missing FCRA notice"
    assert "CFPB" in html or "Consumer Financial Protection Bureau" in html, (
        "Missing CFPB info"
    )
    assert "300" in html and "850" in html, "Missing score range"
    assert str(cs_value) in html, "Missing credit score value"
    assert "html" in html.lower(), "Not HTML format"
    print(f"  HTML length: {len(html)} chars")
    print("  PASS: HTML notice contains all required elements")

    # ── Test 6: HTML notice with no reasons ──
    print("\n[Test 6] HTML notice with empty reasons list")
    html_empty = generate_adverse_action_notice(
        borrower_name="John Smith",
        reasons=[],
        credit_score=720,
        date="January 15, 2025",
    )
    assert "No adverse action reasons required" in html_empty, (
        "Missing fallback text for empty reasons"
    )
    assert "John Smith" in html_empty
    assert "January 15, 2025" in html_empty
    print("  PASS: HTML handles empty reasons gracefully")

    # ── Test 7: format_decision_html ──
    print("\n[Test 7] format_decision_html output")
    decision = {
        "approved": True,
        "risk_score": 22,
        "risk_tier": "A",
        "risk_label": "Low Risk",
        "interest_rate": 8.5,
        "monthly_payment": 315.47,
        "probability_of_default": 0.12,
        "max_loan_amount": 50000.0,
        "recommended_term_months": 36,
        "cash_flow_adjusted": False,
        "explanation": {
            "summary": "Strong credit profile with excellent financial health",
            "top_factors": [
                {"factor": "credit_score", "impact": "positive",
                 "value": 780, "description": "Very good credit score"},
                {"factor": "dti_ratio", "impact": "positive",
                 "value": 0.18, "description": "Low debt-to-income ratio"},
            ],
        },
    }
    html_decision = format_decision_html(decision)
    assert isinstance(html_decision, str)
    assert "APPROVED" in html_decision
    assert "Low Risk" in html_decision
    print(f"  HTML length: {len(html_decision)} chars")
    print("  PASS: Decision HTML formatted correctly")

    # ── Test 8: Engine with custom feature names ──
    print("\n[Test 8] Engine with custom feature name list")
    custom_features = ["credit_score", "dti_ratio"]
    engine_custom = ShapAdverseAction(custom_features)
    assert engine_custom.feature_names == custom_features
    print("  PASS: Custom feature names stored correctly")

    # ── Test 9: Log-derived value resolution ──
    print("\n[Test 9] Log-derived value resolution")
    result = engine._resolve_actual_value("log_income", {"annual_income": 50000})
    assert result == 50000.0, f"Expected 50000, got {result}"
    result = engine._resolve_actual_value("log_loan_amount", {"loan_amount": 25000})
    assert result == 25000.0, f"Expected 25000, got {result}"
    print("  PASS: Log-derived values resolved correctly")

    # ── Test 10: Home ownership resolution ──
    print("\n[Test 10] Home ownership value resolution")
    result = engine._resolve_actual_value("home_rent", {"home_ownership": "rent"})
    assert result == "rent", f"Expected 'rent', got {result}"
    result = engine._resolve_actual_value("home_mortgage", {"home_ownership": "mortgage"})
    assert result == "mortgage", f"Expected 'mortgage', got {result}"
    print("  PASS: Home ownership values resolved correctly")

    # ── Summary ──
    print("\n" + "=" * 72)
    print("ALL 10 TESTS PASSED")
    print("=" * 72)


if __name__ == "__main__":
    import sys

    # If --generate-html passed, write sample HTML to stdout
    if "--generate-html" in sys.argv:
        FEATURES = [
            "credit_score", "dti_ratio", "utilization", "num_derogatory",
            "num_credit_lines", "age", "log_income", "employment_length",
            "log_loan_amount", "home_rent", "home_mortgage", "home_own",
        ]
        engine = ShapAdverseAction(FEATURES)
        shap_data = {
            "base_value": -0.523,
            "prediction": 0.89,
            "values": [
                {"feature": "credit_score", "value": 580.0, "shap_value": 0.8241},
                {"feature": "dti_ratio", "value": 0.51, "shap_value": 0.4523},
                {"feature": "utilization", "value": 0.88, "shap_value": 0.3120},
                {"feature": "num_derogatory", "value": 3.0, "shap_value": 0.2978},
                {"feature": "num_credit_lines", "value": 2.0, "shap_value": 0.1842},
                {"feature": "age", "value": 28.0, "shap_value": 0.0912},
                {"feature": "log_income", "value": 4.301, "shap_value": 0.1547},
                {"feature": "employment_length", "value": 0.5, "shap_value": 0.1211},
                {"feature": "log_loan_amount", "value": 4.699, "shap_value": 0.0987},
                {"feature": "home_rent", "value": 1.0, "shap_value": 0.0678},
                {"feature": "home_mortgage", "value": 0.0, "shap_value": -0.0312},
                {"feature": "home_own", "value": 0.0, "shap_value": -0.0215},
            ],
        }
        app_data = {
            "credit_score": 580,
            "dti_ratio": 0.51,
            "utilization": 0.88,
            "num_derogatory": 3,
            "num_credit_lines": 2,
            "age": 28,
            "annual_income": 20000,
            "employment_length": 0.5,
            "loan_amount": 50000,
            "home_ownership": "rent",
        }
        reasons = engine.generate(shap_data, app_data, 82, approved=False)
        html = generate_adverse_action_notice(
            borrower_name="Jane Doe",
            reasons=reasons,
            credit_score=580,
        )
        print(html)
        sys.exit(0)

    _run_tests()
