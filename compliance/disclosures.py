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
