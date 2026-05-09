"""Truth in Lending Act (TILA / Regulation Z) compliance module.

Produces the federally-required TILA disclosure for closed-end consumer
installment loans. Output is offered both as a structured dict (for storage
and downstream rendering) and as a self-contained HTML fragment suitable for
embedding in the loan agreement PDF / e-sign flow.

PalmFi edition — keeps rich Reg Z-style HTML formatting while using the
cleaner dict-based approach (no DB path resolution, no _get_connection()).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict


def _payment_schedule(
    term_months: int, monthly_payment: float, total_of_payments: float
) -> list[dict]:
    """Build a payment schedule list."""
    schedule = []
    for i in range(1, term_months + 1):
        due_label = f"Monthly beginning {_first_payment_date()}"
        if i == 1:
            schedule.append({
                "number": i,
                "amount": round(monthly_payment, 2),
                "whenDue": due_label,
            })
        else:
            schedule.append({
                "number": i,
                "amount": round(monthly_payment, 2),
                "whenDue": f"Monthly thereafter ({_ordinal(i)} payment)",
            })

    # Last payment may differ slightly due to rounding
    expected_total = monthly_payment * term_months
    diff = round(total_of_payments - expected_total, 2)
    if abs(diff) > 0.01 and schedule:
        schedule[-1]["amount"] = round(schedule[-1]["amount"] + diff, 2)

    return schedule


def generate_tila_disclosure(
    loan_amount: float,
    apr: float,
    term_months: int,
    monthly_payment: float,
    origination_fee: float,
    finance_charge: float,
    total_of_payments: float,
    apr_formatted: str,
) -> dict:
    """Generate a TILA-compliant disclosure dict.

    Parameters
    ----------
    loan_amount : float
        Principal loan amount.
    apr : float
        Annual Percentage Rate as a decimal (e.g., 0.0999 for 9.99%).
    term_months : int
        Number of months in the loan term.
    monthly_payment : float
        Monthly payment amount.
    origination_fee : float
        Origination fee amount in dollars.
    finance_charge : float
        The total cost of credit (interest + fees) in dollars.
    total_of_payments : float
        Total amount to be paid over the full term.
    apr_formatted : str
        APR formatted as a display string (e.g., "9.99%").

    Returns
    -------
    dict
        Complete TILA disclosure ready for rendering and audit logging.
    """
    payment_schedule = _payment_schedule(term_months, monthly_payment, total_of_payments)

    disclosure = {
        "annualPercentageRate": {
            "value": apr_formatted,
            "raw": apr,
            "description": "The cost of your credit as a yearly rate",
        },
        "financeCharge": {
            "value": round(finance_charge, 2),
            "raw": finance_charge,
            "description": "The dollar amount the credit will cost you",
        },
        "amountFinanced": {
            "value": round(loan_amount - origination_fee, 2),
            "raw": loan_amount - origination_fee,
            "description": "The amount of credit provided to you on your behalf",
        },
        "totalOfPayments": {
            "value": round(total_of_payments, 2),
            "raw": total_of_payments,
            "description": "The amount you will have paid after making all payments as scheduled",
        },
        "paymentSchedule": {
            "payments": payment_schedule,
            "totalPayments": term_months,
            "description": "Your payment schedule",
        },
        "latePaymentFee": {
            "value": "See loan agreement",
            "description": "Any late payment fee will be disclosed in your loan agreement",
        },
        "prepaymentPenalty": {
            "value": "None",
            "description": "You may prepay your loan at any time with no penalty",
        },
        "securityInterest": {
            "value": "None",
            "description": "You are not granting a security interest in any property",
        },
        "insurance": {
            "value": "Not required",
            "description": "No credit insurance is required in connection with this loan",
        },
        "meta": {
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "loanAmount": round(loan_amount, 2),
            "annualPercentageRateRaw": apr,
            "termMonths": term_months,
            "monthlyPayment": round(monthly_payment, 2),
            "originationFee": round(origination_fee, 2),
            "financeChargeRaw": round(finance_charge, 2),
            "totalOfPaymentsRaw": round(total_of_payments, 2),
        },
    }

    return disclosure


def _first_payment_date() -> str:
    """Return a human-readable first payment date string (30 days from now)."""
    d = datetime.now(timezone.utc).isoformat()[:10]
    from datetime import timedelta

    dt = datetime.now(timezone.utc) + timedelta(days=30)
    return dt.strftime("%B %d, %Y")


def _ordinal(n: int) -> str:
    """Return ordinal string for a number (1st, 2nd, 3rd, etc.)."""
    if 11 <= n % 100 <= 13:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


# ---------------------------------------------------------------------------
# TILA disclosure validation
# ---------------------------------------------------------------------------

REQUIRED_TILA_FIELDS = [
    "annualPercentageRate",
    "financeCharge",
    "amountFinanced",
    "totalOfPayments",
    "paymentSchedule",
    "latePaymentFee",
    "prepaymentPenalty",
    "securityInterest",
    "insurance",
]


def validate_tila_disclosure(disclosure_dict: dict) -> dict:
    """Validate a TILA disclosure for completeness and mathematical accuracy.

    Checks:
    - All required fields are present
    - finance_charge + amount_financed ≈ total_of_payments (within $1)

    Parameters
    ----------
    disclosure_dict : dict
        A TILA disclosure dict as returned by generate_tila_disclosure().

    Returns
    -------
    dict
        {'valid': bool, 'errors': list of error strings}
    """
    errors = []

    if not isinstance(disclosure_dict, dict):
        return {"valid": False, "errors": ["Disclosure must be a dictionary"]}

    for field in REQUIRED_TILA_FIELDS:
        if field not in disclosure_dict:
            errors.append(f"Missing required field: {field}")

    if errors:
        return {"valid": False, "errors": errors}

    field_checks = {
        "annualPercentageRate": ["value", "raw", "description"],
        "financeCharge": ["value", "raw", "description"],
        "amountFinanced": ["value", "raw", "description"],
        "totalOfPayments": ["value", "raw", "description"],
    }
    for field, sub_keys in field_checks.items():
        for sk in sub_keys:
            if sk not in disclosure_dict.get(field, {}):
                errors.append(f"Missing sub-field '{field}.{sk}'")

    ps = disclosure_dict.get("paymentSchedule", {})
    if not isinstance(ps, dict):
        errors.append("paymentSchedule must be a dictionary")
    else:
        if "payments" not in ps:
            errors.append("paymentSchedule missing 'payments' list")
        elif not isinstance(ps["payments"], list) or len(ps["payments"]) == 0:
            errors.append("paymentSchedule.payments must be a non-empty list")

    if errors:
        return {"valid": False, "errors": errors}

    try:
        fc = float(disclosure_dict["financeCharge"]["raw"])
        af = float(disclosure_dict["amountFinanced"]["raw"])
        top = float(disclosure_dict["totalOfPayments"]["raw"])
        calculated_total = fc + af
        difference = abs(calculated_total - top)
        if difference > 1.00:
            errors.append(
                f"Math check failed: financeCharge ({fc:.2f}) + amountFinanced ({af:.2f}) "
                f"= {calculated_total:.2f}, but totalOfPayments = {top:.2f} "
                f"(difference: {difference:.2f}, tolerance: 1.00)"
            )
    except (ValueError, TypeError, KeyError) as e:
        errors.append(f"Math validation error: {e}")

    return {"valid": len(errors) == 0, "errors": errors}


# ---------------------------------------------------------------------------
# TILA HTML rendering (Reg Z format)
# ---------------------------------------------------------------------------

def format_tila_html(disclosure_dict: dict) -> str:
    """Render a TILA disclosure as an HTML string in Reg Z format.

    Parameters
    ----------
    disclosure_dict : dict
        A TILA disclosure dict as returned by generate_tila_disclosure().

    Returns
    -------
    str
        Complete HTML string styled like a Reg Z disclosure with signature line.
    """
    def v(path: str) -> str:
        parts = path.split(".")
        val = disclosure_dict
        try:
            for p in parts:
                if isinstance(val, dict):
                    val = val.get(p, {})
                else:
                    return ""
            if isinstance(val, dict):
                return str(val.get("value", "")) if "value" in val else ""
            return str(val)
        except (AttributeError, TypeError):
            return ""

    def d(path: str) -> str:
        parts = path.split(".")
        val = disclosure_dict
        try:
            for p in parts:
                if isinstance(val, dict):
                    val = val.get(p, {})
                else:
                    return ""
            if isinstance(val, dict):
                return str(val.get("description", "")) if "description" in val else ""
            return str(val)
        except (AttributeError, TypeError):
            return ""

    apr_value = v("annualPercentageRate")
    apr_desc = d("annualPercentageRate")
    fc_value = v("financeCharge")
    fc_desc = d("financeCharge")
    af_value = v("amountFinanced")
    af_desc = d("amountFinanced")
    top_value = v("totalOfPayments")
    top_desc = d("totalOfPayments")

    ps = disclosure_dict.get("paymentSchedule", {})
    payments = ps.get("payments", []) if isinstance(ps, dict) else []
    ps_rows = ""
    for pmt in payments:
        num = pmt.get("number", "")
        amt = pmt.get("amount", "")
        due = pmt.get("whenDue", "")
        ps_rows += f"""
            <tr>
                <td style="padding: 4px 8px; border: 1px solid #333;">{num}</td>
                <td style="padding: 4px 8px; border: 1px solid #333; text-align: right;">${amt}</td>
                <td style="padding: 4px 8px; border: 1px solid #333;">{due}</td>
            </tr>"""

    late_fee = v("latePaymentFee")
    prepay = v("prepaymentPenalty")
    security = v("securityInterest")
    insurance = v("insurance")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Federal Truth in Lending Disclosure</title>
<style>
    body {{
        font-family: 'Times New Roman', Times, serif;
        font-size: 12pt;
        color: #000;
        background: #fff;
        margin: 0;
        padding: 20px;
        line-height: 1.4;
    }}
    .disclosure-box {{
        max-width: 700px;
        margin: 0 auto;
        border: 2px solid #000;
        padding: 24px;
        background: #fff;
    }}
    h1 {{
        font-size: 16pt;
        font-weight: bold;
        text-align: center;
        margin: 0 0 4px 0;
        text-transform: uppercase;
    }}
    .subtitle {{
        font-size: 10pt;
        text-align: center;
        margin-bottom: 20px;
        font-style: italic;
    }}
    .disclosure-item {{ margin-bottom: 16px; }}
    .disclosure-label {{ font-weight: bold; font-size: 12pt; display: block; }}
    .disclosure-value {{ font-size: 14pt; font-weight: bold; display: block; margin: 2px 0; }}
    .disclosure-desc {{ font-size: 10pt; color: #333; display: block; }}
    table {{ width: 100%; border-collapse: collapse; margin: 8px 0; font-size: 11pt; }}
    th {{ background: #eee; padding: 6px 8px; border: 1px solid #333; text-align: left; font-weight: bold; font-size: 11pt; }}
    .signature-section {{ margin-top: 32px; border-top: 1px solid #000; padding-top: 16px; }}
    .signature-line {{ margin-top: 24px; border-top: 1px solid #000; width: 60%; padding-top: 4px; font-size: 10pt; }}
    .signature-text {{ font-size: 11pt; margin-bottom: 6px; }}
    .misc-item {{ font-size: 10pt; margin-bottom: 4px; }}
    .misc-label {{ font-weight: bold; }}
    @media (max-width: 600px) {{
        .disclosure-box {{ padding: 12px; border-width: 1px; }}
        h1 {{ font-size: 14pt; }}
        .disclosure-value {{ font-size: 12pt; }}
    }}
</style>
</head>
<body>
<div class="disclosure-box">

<h1>Federal Truth in Lending Disclosures</h1>
<p class="subtitle">As required by Regulation Z (12 CFR Part 1026)</p>

<div class="disclosure-item">
    <span class="disclosure-label">Annual Percentage Rate (APR)</span>
    <span class="disclosure-value">{apr_value}</span>
    <span class="disclosure-desc">{apr_desc}</span>
</div>

<div class="disclosure-item">
    <span class="disclosure-label">Finance Charge</span>
    <span class="disclosure-value">${fc_value}</span>
    <span class="disclosure-desc">{fc_desc}</span>
</div>

<div class="disclosure-item">
    <span class="disclosure-label">Amount Financed</span>
    <span class="disclosure-value">${af_value}</span>
    <span class="disclosure-desc">{af_desc}</span>
</div>

<div class="disclosure-item">
    <span class="disclosure-label">Total of Payments</span>
    <span class="disclosure-value">${top_value}</span>
    <span class="disclosure-desc">{top_desc}</span>
</div>

<div class="disclosure-item">
    <span class="disclosure-label">Payment Schedule</span>
    <table>
        <thead>
            <tr>
                <th>Payment</th>
                <th>Amount</th>
                <th>When Due</th>
            </tr>
        </thead>
        <tbody>
            {ps_rows}
        </tbody>
    </table>
</div>

<div class="disclosure-item">
    <div class="misc-item"><span class="misc-label">Late Payment Fee:</span> {late_fee}</div>
    <div class="misc-item"><span class="misc-label">Prepayment Penalty:</span> {prepay}</div>
    <div class="misc-item"><span class="misc-label">Security Interest:</span> {security}</div>
    <div class="misc-item"><span class="misc-label">Insurance:</span> {insurance}</div>
</div>

<div class="signature-section">
    <p class="signature-text">I acknowledge receiving a copy of this disclosure before the consummation of the transaction.</p>
    <div class="signature-line">Borrower Signature / Date</div>
</div>

</div>
</body>
</html>"""
