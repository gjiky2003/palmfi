"""State-by-state usury caps and consumer-lender licensing rules.

Values are GUIDANCE ONLY. Each state's actual statute, license type, and
bond schedule must be re-verified with state counsel before originating
in that jurisdiction. URLs point to the principal regulator.

PalmFi edition — keeps the full 50-state data with SunCredit's cleaner
dict-based approach (no DB path resolution, no _get_connection()).
"""
from __future__ import annotations

from typing import Any, Dict

# max_apr is expressed as a decimal (0.36 = 36% APR). None means "no
# specific small-loan cap; subject to general usury or bank-rate exportation."
STATE_RULES: Dict[str, Dict[str, Any]] = {
    "AL": {"max_apr": 0.36, "max_loan_amount": 15000, "min_loan_term_days": 30, "max_origination_fee_pct": 5.0, "license_required": True, "surety_bond_amount": 25000, "regulator_url": "https://banking.alabama.gov/"},
    "AK": {"max_apr": 0.36, "max_loan_amount": 25000, "min_loan_term_days": 30, "max_origination_fee_pct": 5.0, "license_required": True, "surety_bond_amount": 25000, "regulator_url": "https://www.commerce.alaska.gov/web/dbs/"},
    "AZ": {"max_apr": 0.36, "max_loan_amount": 10000, "min_loan_term_days": 60, "max_origination_fee_pct": 5.0, "license_required": True, "surety_bond_amount": 25000, "regulator_url": "https://dfi.az.gov/"},
    "AR": {"max_apr": 0.17, "max_loan_amount": 10000, "min_loan_term_days": 30, "max_origination_fee_pct": 5.0, "license_required": True, "surety_bond_amount": 50000, "regulator_url": "https://securities.arkansas.gov/"},
    "CA": {"max_apr": 0.36, "max_loan_amount": 10000, "min_loan_term_days": 60, "max_origination_fee_pct": 5.0, "license_required": True, "surety_bond_amount": 25000, "regulator_url": "https://dfpi.ca.gov/"},
    "CO": {"max_apr": 0.36, "max_loan_amount": 15000, "min_loan_term_days": 60, "max_origination_fee_pct": 5.0, "license_required": True, "surety_bond_amount": 25000, "regulator_url": "https://coag.gov/office-sections/consumer-protection/consumer-credit-unit/"},
    "CT": {"max_apr": 0.12, "max_loan_amount": 15000, "min_loan_term_days": 30, "max_origination_fee_pct": 5.0, "license_required": True, "surety_bond_amount": 40000, "regulator_url": "https://portal.ct.gov/dob"},
    "DE": {"max_apr": None, "max_loan_amount": 25000, "min_loan_term_days": 30, "max_origination_fee_pct": 5.0, "license_required": True, "surety_bond_amount": 25000, "regulator_url": "https://banking.delaware.gov/"},
    "FL": {"max_apr": 0.30, "max_loan_amount": 15000, "min_loan_term_days": 60, "max_origination_fee_pct": 5.0, "license_required": True, "surety_bond_amount": 25000, "regulator_url": "https://flofr.gov/"},
    "GA": {"max_apr": 0.60, "max_loan_amount": 10000, "min_loan_term_days": 30, "max_origination_fee_pct": 5.0, "license_required": True, "surety_bond_amount": 25000, "regulator_url": "https://dbf.georgia.gov/"},
    "HI": {"max_apr": 0.24, "max_loan_amount": 15000, "min_loan_term_days": 30, "max_origination_fee_pct": 5.0, "license_required": True, "surety_bond_amount": 25000, "regulator_url": "https://cca.hawaii.gov/dfi/"},
    "ID": {"max_apr": None, "max_loan_amount": 15000, "min_loan_term_days": 30, "max_origination_fee_pct": 5.0, "license_required": True, "surety_bond_amount": 25000, "regulator_url": "https://dof.idaho.gov/"},
    "IL": {"max_apr": 0.36, "max_loan_amount": 10000, "min_loan_term_days": 60, "max_origination_fee_pct": 5.0, "license_required": True, "surety_bond_amount": 25000, "regulator_url": "https://idfpr.illinois.gov/"},
    "IN": {"max_apr": 0.36, "max_loan_amount": 10000, "min_loan_term_days": 30, "max_origination_fee_pct": 5.0, "license_required": True, "surety_bond_amount": 25000, "regulator_url": "https://www.in.gov/dfi/"},
    "IA": {"max_apr": 0.36, "max_loan_amount": 15000, "min_loan_term_days": 30, "max_origination_fee_pct": 5.0, "license_required": True, "surety_bond_amount": 25000, "regulator_url": "https://idob.state.ia.us/"},
    "KS": {"max_apr": 0.36, "max_loan_amount": 10000, "min_loan_term_days": 30, "max_origination_fee_pct": 5.0, "license_required": True, "surety_bond_amount": 25000, "regulator_url": "https://osbckansas.org/"},
    "KY": {"max_apr": 0.36, "max_loan_amount": 10000, "min_loan_term_days": 60, "max_origination_fee_pct": 5.0, "license_required": True, "surety_bond_amount": 25000, "regulator_url": "https://kfi.ky.gov/"},
    "LA": {"max_apr": 0.36, "max_loan_amount": 10000, "min_loan_term_days": 30, "max_origination_fee_pct": 5.0, "license_required": True, "surety_bond_amount": 25000, "regulator_url": "https://www.ofi.la.gov/"},
    "ME": {"max_apr": 0.30, "max_loan_amount": 10000, "min_loan_term_days": 60, "max_origination_fee_pct": 5.0, "license_required": True, "surety_bond_amount": 25000, "regulator_url": "https://www.maine.gov/pfr/financialinstitutions/"},
    "MD": {"max_apr": 0.33, "max_loan_amount": 10000, "min_loan_term_days": 60, "max_origination_fee_pct": 5.0, "license_required": True, "surety_bond_amount": 25000, "regulator_url": "https://www.dllr.state.md.us/finance/"},
    "MA": {"max_apr": 0.23, "max_loan_amount": 10000, "min_loan_term_days": 60, "max_origination_fee_pct": 5.0, "license_required": True, "surety_bond_amount": 75000, "regulator_url": "https://www.mass.gov/orgs/division-of-banks"},
    "MI": {"max_apr": 0.25, "max_loan_amount": 15000, "min_loan_term_days": 30, "max_origination_fee_pct": 5.0, "license_required": True, "surety_bond_amount": 25000, "regulator_url": "https://www.michigan.gov/difs"},
    "MN": {"max_apr": 0.36, "max_loan_amount": 10000, "min_loan_term_days": 30, "max_origination_fee_pct": 5.0, "license_required": True, "surety_bond_amount": 50000, "regulator_url": "https://mn.gov/commerce/"},
    "MS": {"max_apr": 0.36, "max_loan_amount": 15000, "min_loan_term_days": 30, "max_origination_fee_pct": 5.0, "license_required": True, "surety_bond_amount": 25000, "regulator_url": "https://dbcf.ms.gov/"},
    "MO": {"max_apr": None, "max_loan_amount": 10000, "min_loan_term_days": 30, "max_origination_fee_pct": 5.0, "license_required": True, "surety_bond_amount": 25000, "regulator_url": "https://finance.mo.gov/"},
    "MT": {"max_apr": 0.36, "max_loan_amount": 15000, "min_loan_term_days": 30, "max_origination_fee_pct": 5.0, "license_required": True, "surety_bond_amount": 25000, "regulator_url": "https://banking.mt.gov/"},
    "NE": {"max_apr": 0.36, "max_loan_amount": 15000, "min_loan_term_days": 30, "max_origination_fee_pct": 5.0, "license_required": True, "surety_bond_amount": 25000, "regulator_url": "https://ndbf.nebraska.gov/"},
    "NV": {"max_apr": 0.40, "max_loan_amount": 15000, "min_loan_term_days": 30, "max_origination_fee_pct": 5.0, "license_required": True, "surety_bond_amount": 50000, "regulator_url": "https://fid.nv.gov/"},
    "NH": {"max_apr": 0.36, "max_loan_amount": 15000, "min_loan_term_days": 30, "max_origination_fee_pct": 5.0, "license_required": True, "surety_bond_amount": 25000, "regulator_url": "https://www.nh.gov/banking/"},
    "NJ": {"max_apr": 0.30, "max_loan_amount": 10000, "min_loan_term_days": 60, "max_origination_fee_pct": 5.0, "license_required": True, "surety_bond_amount": 25000, "regulator_url": "https://www.state.nj.us/dobi/"},
    "NM": {"max_apr": 0.36, "max_loan_amount": 10000, "min_loan_term_days": 30, "max_origination_fee_pct": 5.0, "license_required": True, "surety_bond_amount": 25000, "regulator_url": "https://www.rld.nm.gov/financial-institutions/"},
    "NY": {"max_apr": 0.16, "max_loan_amount": 5000, "min_loan_term_days": 60, "max_origination_fee_pct": 3.0, "license_required": True, "surety_bond_amount": 50000, "regulator_url": "https://www.dfs.ny.gov/"},
    "NC": {"max_apr": 0.36, "max_loan_amount": 10000, "min_loan_term_days": 60, "max_origination_fee_pct": 5.0, "license_required": True, "surety_bond_amount": 25000, "regulator_url": "https://www.nccob.gov/"},
    "ND": {"max_apr": 0.36, "max_loan_amount": 15000, "min_loan_term_days": 30, "max_origination_fee_pct": 5.0, "license_required": True, "surety_bond_amount": 25000, "regulator_url": "https://www.nd.gov/dfi/"},
    "OH": {"max_apr": 0.28, "max_loan_amount": 10000, "min_loan_term_days": 60, "max_origination_fee_pct": 5.0, "license_required": True, "surety_bond_amount": 25000, "regulator_url": "https://com.ohio.gov/divisions-and-programs/financial-institutions/"},
    "OK": {"max_apr": 0.36, "max_loan_amount": 15000, "min_loan_term_days": 30, "max_origination_fee_pct": 5.0, "license_required": True, "surety_bond_amount": 25000, "regulator_url": "https://www.ok.gov/okdocc/"},
    "OR": {"max_apr": 0.36, "max_loan_amount": 15000, "min_loan_term_days": 60, "max_origination_fee_pct": 5.0, "license_required": True, "surety_bond_amount": 25000, "regulator_url": "https://dfr.oregon.gov/"},
    "PA": {"max_apr": 0.24, "max_loan_amount": 10000, "min_loan_term_days": 60, "max_origination_fee_pct": 5.0, "license_required": True, "surety_bond_amount": 25000, "regulator_url": "https://www.dobs.pa.gov/"},
    "RI": {"max_apr": 0.36, "max_loan_amount": 15000, "min_loan_term_days": 30, "max_origination_fee_pct": 5.0, "license_required": True, "surety_bond_amount": 25000, "regulator_url": "https://dbr.ri.gov/"},
    "SC": {"max_apr": None, "max_loan_amount": 10000, "min_loan_term_days": 30, "max_origination_fee_pct": 5.0, "license_required": True, "surety_bond_amount": 25000, "regulator_url": "https://consumer.sc.gov/"},
    "SD": {"max_apr": 0.36, "max_loan_amount": 20000, "min_loan_term_days": 30, "max_origination_fee_pct": 5.0, "license_required": True, "surety_bond_amount": 25000, "regulator_url": "https://dlr.sd.gov/banking/"},
    "TN": {"max_apr": 0.24, "max_loan_amount": 10000, "min_loan_term_days": 30, "max_origination_fee_pct": 5.0, "license_required": True, "surety_bond_amount": 25000, "regulator_url": "https://www.tn.gov/tdfi/"},
    "TX": {"max_apr": 0.36, "max_loan_amount": 15000, "min_loan_term_days": 60, "max_origination_fee_pct": 5.0, "license_required": True, "surety_bond_amount": 25000, "regulator_url": "https://occc.texas.gov/"},
    "UT": {"max_apr": None, "max_loan_amount": 15000, "min_loan_term_days": 30, "max_origination_fee_pct": 5.0, "license_required": True, "surety_bond_amount": 25000, "regulator_url": "https://dfi.utah.gov/"},
    "VT": {"max_apr": 0.18, "max_loan_amount": 10000, "min_loan_term_days": 60, "max_origination_fee_pct": 5.0, "license_required": True, "surety_bond_amount": 50000, "regulator_url": "https://dfr.vermont.gov/"},
    "VA": {"max_apr": 0.36, "max_loan_amount": 15000, "min_loan_term_days": 60, "max_origination_fee_pct": 5.0, "license_required": True, "surety_bond_amount": 25000, "regulator_url": "https://www.scc.virginia.gov/pages/Bureau-of-Financial-Institutions"},
    "WA": {"max_apr": 0.25, "max_loan_amount": 15000, "min_loan_term_days": 60, "max_origination_fee_pct": 5.0, "license_required": True, "surety_bond_amount": 30000, "regulator_url": "https://dfi.wa.gov/"},
    "WV": {"max_apr": 0.31, "max_loan_amount": 10000, "min_loan_term_days": 30, "max_origination_fee_pct": 5.0, "license_required": True, "surety_bond_amount": 25000, "regulator_url": "https://dfi.wv.gov/"},
    "WI": {"max_apr": 0.36, "max_loan_amount": 15000, "min_loan_term_days": 30, "max_origination_fee_pct": 5.0, "license_required": True, "surety_bond_amount": 25000, "regulator_url": "https://dfi.wi.gov/"},
    "WY": {"max_apr": 0.36, "max_loan_amount": 15000, "min_loan_term_days": 30, "max_origination_fee_pct": 5.0, "license_required": True, "surety_bond_amount": 25000, "regulator_url": "https://wyomingbankingdivision.wyo.gov/"},
}

_DEFAULT_RULES = {
    "max_apr": 0.36,
    "max_loan_amount": 10000,
    "min_loan_term_days": 30,
    "max_origination_fee_pct": 5.0,
    "license_required": True,
    "surety_bond_amount": 25000,
}


def _get_state_rules(state_code: str) -> dict:
    """Get rules for a state code, falling back to defaults."""
    return STATE_RULES.get(state_code.upper(), _DEFAULT_RULES)


# ---------------------------------------------------------------------------
# Loan compliance check
# ---------------------------------------------------------------------------

def check_loan_compliance(
    loan_amount: float,
    apr: float,
    origination_fee_pct: float,
    term_months: int,
    state_code: str,
    loan_purpose: str = "personal",
) -> dict:
    """Check if a loan is compliant in the given state.

    Parameters
    ----------
    loan_amount : float
        Principal loan amount in dollars.
    apr : float
        Annual Percentage Rate as a decimal (e.g., 0.2999 for 29.99%).
    origination_fee_pct : float
        Origination fee as a percentage of loan amount.
    term_months : int
        Loan term in months.
    state_code : str
        Two-letter US state code (e.g., 'CA', 'NY').
    loan_purpose : str
        Purpose of the loan.

    Returns
    -------
    dict
        compliant, violations, applicable_rules, max_allowed_apr, max_allowed_amount.
    """
    rules = _get_state_rules(state_code)
    violations = []
    loan_term_days = term_months * 30

    cap = rules.get("max_apr")
    if cap is not None and apr > cap:
        violations.append(
            f"APR of {apr*100:.2f}% exceeds {state_code.upper()} maximum of {cap*100:.1f}%"
        )

    max_amt = rules["max_loan_amount"]
    if loan_amount > max_amt:
        violations.append(
            f"Loan amount ${loan_amount:.2f} exceeds {state_code.upper()} maximum of ${max_amt:.2f}"
        )

    min_term = rules["min_loan_term_days"]
    if loan_term_days < min_term:
        violations.append(
            f"Loan term of {loan_term_days} days ({term_months} months) is below "
            f"{state_code.upper()} minimum of {min_term} days"
        )

    max_orig = rules["max_origination_fee_pct"]
    if origination_fee_pct > max_orig:
        violations.append(
            f"Origination fee of {origination_fee_pct:.1f}% exceeds "
            f"{state_code.upper()} maximum of {max_orig:.1f}%"
        )

    return {
        "compliant": len(violations) == 0,
        "violations": violations,
        "applicable_rules": dict(rules),
        "max_allowed_apr": (cap * 100 if cap is not None else None),
        "max_allowed_amount": max_amt,
        "state_code": state_code.upper(),
    }


# ---------------------------------------------------------------------------
# Federal compliance — Military Lending Act (36% cap)
# ---------------------------------------------------------------------------

def is_federally_permissible(loan_amount: float, apr: float) -> dict:
    """Check federal usury limits, specifically the Military Lending Act cap.

    Parameters
    ----------
    loan_amount : float
        Principal loan amount in dollars.
    apr : float
        Annual Percentage Rate as a percentage (e.g., 36.0 for 36%).

    Returns
    -------
    dict
        federally_permissible, warning, mla_cap, effective_apr.
    """
    mla_cap = 36.0

    if apr > mla_cap:
        return {
            "federally_permissible": False,
            "warning": (
                f"APR of {apr:.2f}% exceeds the Military Lending Act cap of {mla_cap:.1f}% "
                f"for covered borrowers. If the borrower is active-duty military or a dependent, "
                f"this loan is prohibited under 10 U.S.C. § 987."
            ),
            "mla_cap": mla_cap,
            "effective_apr": apr,
            "requires_scra_check": True,
        }

    return {
        "federally_permissible": True,
        "warning": None,
        "mla_cap": mla_cap,
        "effective_apr": apr,
        "requires_scra_check": False,
    }
