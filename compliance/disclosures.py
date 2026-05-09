"""Federal consumer-credit disclosure notices required at application,
adverse-action, and origination time.

Includes:
  * ECOA (Equal Credit Opportunity Act / Reg B) notice
  * FCRA (Fair Credit Reporting Act) notice
  * GLBA (Gramm-Leach-Bliley Act) privacy notice
  * MLA (Military Lending Act) covered-borrower check
"""
from __future__ import annotations

from typing import Dict, Any

ECOA_NOTICE = """\
EQUAL CREDIT OPPORTUNITY ACT NOTICE

The Federal Equal Credit Opportunity Act prohibits creditors from
discriminating against credit applicants on the basis of race, color,
religion, national origin, sex, marital status, age (provided the applicant
has the capacity to enter into a binding contract); because all or part of
the applicant's income derives from any public assistance program; or
because the applicant has in good faith exercised any right under the
Consumer Credit Protection Act.

The federal agency that administers compliance with this law concerning
this creditor is the Consumer Financial Protection Bureau, 1700 G Street NW,
Washington, DC 20552.
"""

FCRA_NOTICE = """\
FAIR CREDIT REPORTING ACT NOTICE

In connection with your application for credit, we may obtain a consumer
report from one or more consumer reporting agencies. If we take adverse
action based in whole or in part on information contained in such a report,
we will provide you with the name, address, and telephone number of the
consumer reporting agency that furnished the report, a statement that the
agency did not make the credit decision and is unable to provide the
specific reasons for the adverse action, and a notice of your right to
obtain a free copy of the report and to dispute inaccurate information.

You have the right under the FCRA to know the information contained in
your file at the consumer reporting agency. You also have the right to
dispute any inaccurate information.
"""

GLBA_PRIVACY_NOTICE = """\
PRIVACY NOTICE — PalmFi Lending LLC

FACTS: WHAT DOES PALMFI DO WITH YOUR PERSONAL INFORMATION?

Why?       Financial companies choose how they share your personal
           information. Federal law gives consumers the right to limit some
           but not all sharing. Federal law also requires us to tell you how
           we collect, share, and protect your personal information. Please
           read this notice carefully to understand what we do.

What?      The types of personal information we collect and share depend on
           the product or service you have with us. This information can
           include: Social Security number, income, account balances,
           payment history, credit history, and credit scores.

How?       All financial companies need to share customers' personal
           information to run their everyday business. In the section below,
           we list the reasons financial companies can share their
           customers' personal information; the reasons PalmFi chooses to
           share; and whether you can limit this sharing.

Reasons we can share your personal information:
  * For our everyday business purposes — such as to process your
    transactions, maintain your account, respond to court orders and legal
    investigations, or report to credit bureaus: YES — Cannot limit.
  * For our marketing purposes — to offer our products and services to you:
    YES — Cannot limit.
  * For joint marketing with other financial companies: NO.
  * For our affiliates' everyday business purposes — information about your
    transactions and experiences: NO.
  * For our affiliates' everyday business purposes — information about your
    creditworthiness: NO.
  * For our affiliates to market to you: NO.
  * For nonaffiliates to market to you: NO.

Questions? Call (XXX) XXX-XXXX or email privacy@palmfi.com.
"""


def ecoa_notice() -> str:
    return ECOA_NOTICE


def fcra_notice() -> str:
    return FCRA_NOTICE


def glba_privacy_notice() -> str:
    return GLBA_PRIVACY_NOTICE


def military_lending_act_check(borrower: Dict[str, Any]) -> Dict[str, Any]:
    """Determine whether borrower is a covered borrower under the MLA.

    The MLA caps APR at 36% MAPR for active-duty servicemembers, their
    spouses, and certain dependents. Production should query the DoD
    Manpower Database. Here we accept the borrower's self-attested status
    plus an optional dod_status field.
    """
    is_active_duty = bool(borrower.get("active_duty_military"))
    is_dependent = bool(borrower.get("military_dependent"))
    covered = is_active_duty or is_dependent
    return {
        "covered_borrower": covered,
        "max_mapr": 0.36 if covered else None,
        "requires_oral_disclosure": covered,
        "notice": (
            "Federal law provides important protections to members of the "
            "Armed Forces and their dependents relating to extensions of "
            "consumer credit. In general, the cost of consumer credit to a "
            "member of the Armed Forces and his or her dependent may not "
            "exceed an annual percentage rate of 36 percent."
            if covered
            else "Borrower is not a covered borrower under the MLA."
        ),
        "verification_method": "DoD MLA database (https://mla.dmdc.osd.mil)",
    }


def all_disclosures(borrower: Dict[str, Any] | None = None) -> Dict[str, Any]:
    return {
        "ecoa": ECOA_NOTICE,
        "fcra": FCRA_NOTICE,
        "glba_privacy": GLBA_PRIVACY_NOTICE,
        "mla": military_lending_act_check(borrower or {}),
    }


# ── DisclosureManager ─────────────────────────────────────────────────────

import json
from datetime import datetime, timezone
from typing import Optional


class DisclosureManager:
    """Manages the creation, presentation, and acceptance of disclosure packets.

    Uses the existing notice functions (ecoa_notice, fcra_notice, etc.) plus
    TILA and state compliance to build a complete disclosure packet for a loan.
    """

    def __init__(self, db=None):
        """Initialize with optional database connection.

        Parameters
        ----------
        db : callable or connection, optional
            A callable that returns a DB connection (e.g., get_db), or a
            connection directly. If None, acceptance recording is skipped.
        """
        self._db_factory = db if callable(db) else None
        self._conn = db if not callable(db) else None

    def _get_conn(self):
        return self._conn if self._conn else self._db_factory() if self._db_factory else None

    def create_packet(
        self,
        loan_amount: float,
        apr: float,
        term_months: int,
        monthly_payment: float,
        origination_fee: float,
        finance_charge: float,
        total_of_payments: float,
        borrower: Optional[Dict[str, Any]] = None,
        state_code: str = "CA",
        loan_purpose: str = "personal",
    ) -> Dict[str, Any]:
        """Create a complete disclosure packet.

        Builds TILA disclosure, applies state and federal compliance checks,
        and bundles all required notices (ECOA, FCRA, GLBA, MLA) into a single
        packet dict ready for presentation and audit logging.

        Parameters
        ----------
        loan_amount : float
            Principal loan amount.
        apr : float
            Annual Percentage Rate as a decimal (e.g., 0.0999 for 9.99%).
        term_months : int
            Loan term in months.
        monthly_payment : float
            Monthly payment amount.
        origination_fee : float
            Origination fee in dollars.
        finance_charge : float
            Total finance charge (interest + fees) in dollars.
        total_of_payments : float
            Total of all payments over the full term.
        borrower : dict, optional
            Borrower info dict (used for MLA check).
        state_code : str
            Two-letter US state code for compliance check.
        loan_purpose : str
            Purpose of the loan.

        Returns
        -------
        dict
            Complete disclosure packet with keys:
            - packet_id: unique timestamp-based ID
            - created_at: ISO-formatted timestamp
            - loan_details: summary of loan terms
            - tila: TILA disclosure dict
            - state_compliance: state compliance check results
            - federal_compliance: federal (MLA) compliance check results
            - ecoa_notice: ECOA notice text
            - fcra_notice: FCRA notice text
            - glba_notice: GLBA privacy notice text
            - mla: MLA check results
        """
        from compliance.tila import generate_tila_disclosure
        from compliance.state_licensing import check_loan_compliance, is_federally_permissible

        apr_formatted = f"{apr * 100:.2f}%"

        # TILA disclosure
        tila = generate_tila_disclosure(
            loan_amount=loan_amount,
            apr=apr,
            term_months=term_months,
            monthly_payment=monthly_payment,
            origination_fee=origination_fee,
            finance_charge=finance_charge,
            total_of_payments=total_of_payments,
            apr_formatted=apr_formatted,
        )

        # State compliance
        orig_fee_pct = (origination_fee / loan_amount * 100) if loan_amount > 0 else 0
        state_compliance = check_loan_compliance(
            loan_amount=loan_amount,
            apr=apr,
            origination_fee_pct=orig_fee_pct,
            term_months=term_months,
            state_code=state_code,
            loan_purpose=loan_purpose,
        )

        # Federal (MLA) compliance
        federal_compliance = is_federally_permissible(
            loan_amount=loan_amount,
            apr=apr * 100,  # convert decimal to percentage for the function
        )

        # Bundle existing notices
        borrower_data = borrower or {}
        disclosures = all_disclosures(borrower_data)

        packet_id = f"PACKET-{int(datetime.now(timezone.utc).timestamp())}"

        packet = {
            "packet_id": packet_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "loan_details": {
                "loan_amount": round(loan_amount, 2),
                "apr": apr_formatted,
                "term_months": term_months,
                "monthly_payment": round(monthly_payment, 2),
                "origination_fee": round(origination_fee, 2),
                "finance_charge": round(finance_charge, 2),
                "total_of_payments": round(total_of_payments, 2),
            },
            "tila": tila,
            "state_compliance": state_compliance,
            "federal_compliance": federal_compliance,
            "ecoa_notice": disclosures["ecoa"],
            "fcra_notice": disclosures["fcra"],
            "glba_notice": disclosures["glba_privacy"],
            "mla": disclosures["mla"],
        }
        return packet

    def present_to_borrower(self, packet: Dict[str, Any]) -> str:
        """Render a disclosure packet as an HTML string for borrower presentation.

        Parameters
        ----------
        packet : dict
            A disclosure packet created by create_packet().

        Returns
        -------
        str
            Complete HTML document string.
        """
        ld = packet.get("loan_details", {})
        sc = packet.get("state_compliance", {})
        fc = packet.get("federal_compliance", {})

        # Format TILA table rows
        tila = packet.get("tila", {})
        tila_rows = ""
        for key, val in tila.items():
            if isinstance(val, dict):
                label = val.get("description", key.replace("_", " ").title())
                value = val.get("value", "")
                tila_rows += f"<tr><td>{label}</td><td><strong>{value}</strong></td></tr>\n"

        # Payment schedule from TILA
        schedule_rows = ""
        schedule = tila.get("paymentSchedule", [])
        if isinstance(schedule, list):
            for p in schedule:
                schedule_rows += (
                    f"<tr><td>{p.get('number', '')}</td>"
                    f"<td>${p.get('amount', 0):.2f}</td>"
                    f"<td>{p.get('whenDue', '')}</td></tr>\n"
                )

        # State compliance
        state_status = "✅ Compliant" if sc.get("compliant") else "❌ Non-compliant"
        violations_html = ""
        for v in sc.get("violations", []):
            violations_html += f"<li>{v}</li>\n"

        # Federal compliance
        fed_status = "✅ Permissible" if fc.get("federally_permissible") else "⚠️ Restricted"
        fed_warning = fc.get("warning", "")

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Loan Disclosure Packet - {packet.get('packet_id', '')}</title>
<style>
  body {{ font-family: Arial, Helvetica, sans-serif; max-width: 800px; margin: 20px auto; padding: 20px; color: #333; }}
  h1 {{ color: #1a5276; border-bottom: 2px solid #1a5276; padding-bottom: 8px; }}
  h2 {{ color: #2c3e50; margin-top: 24px; }}
  table {{ width: 100%; border-collapse: collapse; margin: 12px 0; }}
  th, td {{ padding: 8px 12px; text-align: left; border: 1px solid #ddd; }}
  th {{ background-color: #f2f6f9; font-weight: 600; }}
  .notice {{ background: #f9f9f9; border-left: 4px solid #2980b9; padding: 12px 16px; margin: 12px 0; white-space: pre-wrap; font-size: 13px; line-height: 1.5; }}
  .compliant {{ color: #27ae60; font-weight: bold; }}
  .non-compliant {{ color: #e74c3c; font-weight: bold; }}
  .violations {{ color: #e74c3c; }}
  .footer {{ margin-top: 32px; padding-top: 16px; border-top: 1px solid #ddd; font-size: 12px; color: #777; }}
  .accept-btn {{ background: #1a5276; color: white; border: none; padding: 12px 24px; font-size: 16px; border-radius: 4px; cursor: pointer; }}
  .accept-btn:hover {{ background: #154360; }}
</style>
</head>
<body>
<h1>📄 Loan Disclosure Packet</h1>
<p><strong>Packet ID:</strong> {packet.get('packet_id', '')}</p>
<p><strong>Created:</strong> {packet.get('created_at', '')}</p>

<h2>Loan Summary</h2>
<table>
  <tr><th>Detail</th><th>Value</th></tr>
  <tr><td>Loan Amount</td><td>${ld.get('loan_amount', 0):.2f}</td></tr>
  <tr><td>APR</td><td>{ld.get('apr', '')}</td></tr>
  <tr><td>Term</td><td>{ld.get('term_months', 0)} months</td></tr>
  <tr><td>Monthly Payment</td><td>${ld.get('monthly_payment', 0):.2f}</td></tr>
  <tr><td>Origination Fee</td><td>${ld.get('origination_fee', 0):.2f}</td></tr>
  <tr><td>Finance Charge</td><td>${ld.get('finance_charge', 0):.2f}</td></tr>
  <tr><td>Total of Payments</td><td>${ld.get('total_of_payments', 0):.2f}</td></tr>
</table>

<h2>📊 Truth in Lending (TILA) Disclosure</h2>
<table>
  <tr><th>Item</th><th>Value</th></tr>
  {tila_rows}
</table>

<h3>Payment Schedule</h3>
<table>
  <tr><th>#</th><th>Amount</th><th>Due</th></tr>
  {schedule_rows}
</table>

<h2>✅ State Compliance — {sc.get('state_code', 'N/A')}</h2>
<p class="{'compliant' if sc.get('compliant') else 'non-compliant'}">{state_status}</p>
{violations_html}

<h2>🏛️ Federal Compliance (MLA)</h2>
<p class="{'compliant' if fc.get('federally_permissible') else 'non-compliant'}">{fed_status}</p>
{fed_warning}

<h2>⚖️ Equal Credit Opportunity Act (ECOA) Notice</h2>
<div class="notice">{packet.get('ecoa_notice', '')}</div>

<h2>📋 Fair Credit Reporting Act (FCRA) Notice</h2>
<div class="notice">{packet.get('fcra_notice', '')}</div>

<h2>🔒 Privacy Notice (GLBA)</h2>
<div class="notice">{packet.get('glba_notice', '')}</div>

<h2>🪖 Military Lending Act</h2>
<div class="notice">{packet.get('mla', {}).get('notice', '')}</div>

<div class="footer">
  <p>By accepting this disclosure packet, you acknowledge that you have received,
  read, and understand all disclosures above.</p>
</div>
</body>
</html>"""
        return html

    def borrower_accepts(
        self,
        packet: Dict[str, Any],
        borrower_id: int,
        loan_id: int = 0,
        application_id: int = 0,
        signature: str = "",
    ) -> Dict[str, Any]:
        """Record borrower acceptance of a disclosure packet in the database.

        Creates a disclosure_acceptances table if it does not exist, then
        inserts a record of the borrower's acceptance including the packet
        content as JSON.

        Parameters
        ----------
        packet : dict
            The disclosure packet being accepted.
        borrower_id : int
            ID of the accepting borrower.
        loan_id : int, optional
            Related loan ID if available.
        application_id : int, optional
            Related application ID if available.
        signature : str
            Optional signature string (e.g., typed name or e-signature ref).

        Returns
        -------
        dict
            Result dict with success status, acceptance_id, and timestamp.
        """
        conn = self._get_conn()
        if conn is None:
            return {
                "success": False,
                "error": "No database connection available",
            }

        try:
            # Ensure table exists
            conn.execute("""
                CREATE TABLE IF NOT EXISTS disclosure_acceptances (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    packet_id TEXT NOT NULL,
                    borrower_id INTEGER NOT NULL,
                    loan_id INTEGER DEFAULT 0,
                    application_id INTEGER DEFAULT 0,
                    packet_json TEXT NOT NULL,
                    signature TEXT DEFAULT '',
                    accepted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (borrower_id) REFERENCES borrowers(id)
                )
            """)
            conn.commit()

            now = datetime.now(timezone.utc).isoformat()
            cursor = conn.execute(
                """INSERT INTO disclosure_acceptances
                   (packet_id, borrower_id, loan_id, application_id, packet_json, signature, accepted_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    packet.get("packet_id", ""),
                    borrower_id,
                    loan_id,
                    application_id,
                    json.dumps(packet),
                    signature,
                    now,
                ),
            )
            conn.commit()
            acceptance_id = cursor.lastrowid

            return {
                "success": True,
                "acceptance_id": acceptance_id,
                "packet_id": packet.get("packet_id", ""),
                "borrower_id": borrower_id,
                "accepted_at": now,
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
            }
