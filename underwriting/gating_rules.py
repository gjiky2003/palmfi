#!/usr/bin/env python3
"""
Gating Rules Engine — Hard Cuts, Suppressions & Soft Overrides

Implements the pre-scoring gate layer for the PalmFi lending platform
(loans $500–$5 000, 6–24 month terms).  Runs *before* any ML scoring
to enforce regulatory, fraud, and policy boundaries.

Architecture
------------
                  ┌──────────────────────┐
                  │   Application Data    │
                  │   + Bureau Data (opt) │
                  └──────────┬───────────┘
                             │
                             ▼
                  ┌──────────────────────┐
                  │    GatingRules        │
                  │    .evaluate()        │
                  └──────────┬───────────┘
                             │
              ┌──────────────┼─────────────┐
              ▼              ▼             ▼
      ┌────────────┐ ┌────────────┐ ┌────────────┐
      │ Hard Cuts  │ │Suppressions│ │Soft Overr. │
      │ (decline)  │ │(manual rev)│ │(boost)     │
      └────────────┘ └────────────┘ └────────────┘

Three rule categories:
    **Hard Cuts** — Any match = immediate decline, no scoring.
    **Suppressions** — Flagged for manual review (score overridden).
    **Soft Overrides** — Can push borderline cases toward approval.
"""

from __future__ import annotations

import datetime
import math
from typing import Any, Dict, List, Optional, Set


# ──────────────────────────────────────────────────────────────────────
#  Allowed operating states (expand as licensing grows)
# ──────────────────────────────────────────────────────────────────────
_DEFAULT_ALLOWED_STATES: Set[str] = {"VA", "TX", "FL", "NC", "GA", "AZ"}

# High-risk ZIP codes (Virginia — configurable via add_high_risk_zip)
_DEFAULT_HIGH_RISK_ZIPS: Set[str] = {
    "23223", "23224", "23234", "23831",
}

# Severity labels for suppression categories
SUPPRESSION_CATEGORIES: Dict[str, str] = {
    "velocity": "HIGH",
    "fraud": "HIGH",
    "discrepancy": "MEDIUM",
    "instability": "LOW",
}


def _parse_dob(dob: Any) -> Optional[datetime.date]:
    """Parse a date-of-birth value into a `datetime.date`."""
    if dob is None:
        return None
    if isinstance(dob, datetime.date):
        return dob
    if isinstance(dob, str):
        for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%Y%m%d"):
            try:
                return datetime.datetime.strptime(dob, fmt).date()
            except ValueError:
                continue
    if isinstance(dob, (int, float)):
        # Treat as epoch seconds
        try:
            return datetime.datetime.fromtimestamp(float(dob)).date()
        except (OSError, ValueError, OverflowError):
            pass
    return None


def _age_from_dob(dob: Any) -> Optional[int]:
    """Calculate age in years from a date-of-birth value."""
    d = _parse_dob(dob)
    if d is None:
        return None
    today = datetime.date.today()
    return today.year - d.year - (
        (today.month, today.day) < (d.month, d.day)
    )


# ══════════════════════════════════════════════════════════════════════
#  GatingRules
# ══════════════════════════════════════════════════════════════════════

class GatingRules:
    """Pre-scoring gate layer for PalmFi lending decisions.

    Evaluates an application against three tiers of rules:

    * **Hard Cuts** — Absolute decline conditions (age, fraud,
      bankruptcy, charge-off, state restrictions, etc.).  If *any* hard
      cut triggers, the application is immediately declined without
      scoring and the applicant receives an adverse-action notice.

    * **Suppressions** — Suspicious patterns that warrant manual review
      (velocity, address instability, income discrepancy, inquiry
      spikes, high-risk ZIPs, suspicious timing, new-account velocity).
      A suppression *does not* auto-decline but marks the application
      for manual review by an LLM-augmented underwriter.

    * **Soft Overrides** — Positive signals that can push a borderline
      case toward approval (existing good customer, veteran status,
      referral from a borrower in good standing).

    Parameters
    ----------
    allowed_states : set of str, optional
        State codes where PalmFi is licensed to lend.  Defaults to
        ``{"VA", "TX", "FL", "NC", "GA", "AZ"}``.
    high_risk_zips : set of str, optional
        ZIP codes considered high-risk.  Defaults to a curated set of
        VA ZIP codes.  Can be extended at runtime via
        :meth:`add_high_risk_zip`.
    """

    def __init__(
        self,
        allowed_states: Optional[Set[str]] = None,
        high_risk_zips: Optional[Set[str]] = None,
    ) -> None:
        self._allowed_states: Set[str] = (
            set(allowed_states) if allowed_states is not None
            else _DEFAULT_ALLOWED_STATES.copy()
        )
        self._high_risk_zips: Set[str] = (
            set(high_risk_zips) if high_risk_zips is not None
            else _DEFAULT_HIGH_RISK_ZIPS.copy()
        )

    # ──────────────────────────────────────────────────────────────────
    #  Public API
    # ──────────────────────────────────────────────────────────────────

    def evaluate(
        self,
        app_data: Dict[str, Any],
        bureau_data: Optional[Dict[str, Any]] = None,
        application_history: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Run all gating rules against an application.

        Parameters
        ----------
        app_data : dict
            Application payload.  Expected keys:

            - ``dob`` / ``date_of_birth`` — Date of birth
            - ``ssn`` — Social Security number (last 4 or full)
            - ``name`` — Full name
            - ``email`` — Email address
            - ``state`` — Two-letter state code
            - ``loan_amount`` — Requested amount (**required**)
            - ``term_months`` — Requested term in months (**required**)
            - ``annual_income`` — Stated annual income
            - ``zip_code`` — ZIP code
            - ``submission_time`` — Datetime the application was
              submitted (ISO string, ``datetime``, or epoch seconds)
            - ``account_created_at`` — Datetime the borrower account was
              created
            - ``veteran`` — *bool* veteran flag
            - ``referral_code`` — Referral code from another borrower
            - ``existing_customer`` — *bool* active loan flag
            - ``self_reported_bankruptcy`` — *bool*
            - ``self_reported_chargeoff`` — *bool*
            - ``on_time_payment_months`` — *int* months of on-time
              payment history

        bureau_data : dict, optional
            Credit bureau data.  Expected keys:

            - ``bankruptcy_flag`` — *bool*
            - ``bankruptcy_date`` — Date string
            - ``active_loans`` — *int* number of active loans on file
            - ``chargeoff_in_24mo`` — *bool*
            - ``chargeoff_date`` — Date string
            - ``death_flag`` — *bool*
            - ``stated_income`` — Income amount reported to bureau
            - ``address_changes_6mo`` — *int* address changes in 6 mo
            - ``credit_inquiries_90d`` — *int* inquiries in 90 days
            - ``fico_score`` — *int* FICO score

        application_history : list of dict, optional
            Recent applications (same SSN/email) for velocity checks.
            Each dict should have at least a ``submission_time`` key.

        Returns
        -------
        dict
            Result dictionary with keys:

            - **hard_cuts** — List of dicts ``{'rule', 'reason',
              'blocked'}`` for each hard cut evaluation.
            - **hard_cut_blocked** — ``True`` if *any* hard cut
              triggered (immediate decline).
            - **suppressions** — List of dicts ``{'rule', 'reason',
              'flagged'}`` for each suppression check.
            - **suppression_flagged** — ``True`` if *any* suppression
              triggered (manual review required).
            - **soft_overrides** — List of dicts ``{'rule', 'reason',
              'applies'}`` for each soft override check.
            - **soft_override_applies** — ``True`` if *any* soft
              override applies.
            - **gating_summary** — Human-readable summary string.
        """
        bureau = bureau_data or {}
        history = application_history or []

        # ── Hard Cuts ──
        hard_cuts: List[Dict[str, Any]] = [
            self.age_gate(app_data),
            self.ssn_fraud_gate(app_data),
            self.bankruptcy_gate(app_data, bureau),
            self.existing_active_loan_gate(app_data, bureau),
            self.previous_chargeoff_gate(app_data, bureau),
            self.state_restriction_gate(app_data),
            self.amount_range_gate(app_data),
            self.term_range_gate(app_data),
            self.ofac_sanctions_gate(app_data),
            self.death_master_gate(app_data, bureau),
        ]
        hard_cut_blocked = any(hc["blocked"] for hc in hard_cuts)

        # ── Suppressions ──
        suppressions: List[Dict[str, Any]] = [
            self.velocity_check(app_data, history),
            self.address_instability(app_data, bureau),
            self.income_discrepancy(app_data, bureau),
            self.inquiry_spike(app_data, bureau),
            self.high_risk_zip(app_data),
            self.suspicious_timing(app_data),
            self.new_account_velocity(app_data),
        ]
        suppression_flagged = any(s["flagged"] for s in suppressions)

        # ── Soft Overrides ──
        soft_overrides: List[Dict[str, Any]] = [
            self.existing_good_customer(app_data),
            self.veteran_status(app_data),
            self.referral_from_good(app_data),
        ]
        soft_override_applies = any(so["applies"] for so in soft_overrides)

        # ── Summary ──
        gating_summary = self._build_summary(
            hard_cut_blocked, suppression_flagged, soft_override_applies,
            hard_cuts, suppressions, soft_overrides,
        )

        return {
            "hard_cuts": hard_cuts,
            "hard_cut_blocked": hard_cut_blocked,
            "suppressions": suppressions,
            "suppression_flagged": suppression_flagged,
            "soft_overrides": soft_overrides,
            "soft_override_applies": soft_override_applies,
            "gating_summary": gating_summary,
        }

    def is_allowed_state(self, state: str) -> bool:
        """Check whether *state* is in the set of licensed operating states.

        Parameters
        ----------
        state : str
            Two-letter US state code (e.g. ``'VA'``).

        Returns
        -------
        bool
        """
        return state.upper() in self._allowed_states

    def add_high_risk_zip(self, zip_code: str) -> None:
        """Add a ZIP code to the high-risk set at runtime.

        Parameters
        ----------
        zip_code : str
            ZIP code to add (e.g. ``'22030'``).
        """
        self._high_risk_zips.add(zip_code)

    # ──────────────────────────────────────────────────────────────────
    #  Hard Cuts  (absolute decline — cannot be overridden)
    # ──────────────────────────────────────────────────────────────────

    def age_gate(self, app_data: Dict[str, Any]) -> Dict[str, Any]:
        """Hard cut — age outside 18–75.

        Checks DOB from ``app_data`` (keys ``'dob'`` or
        ``'date_of_birth'``).  Borrowers under 18 or over 75 are
        immediately declined.

        Returns
        -------
        dict
            ``{'rule': 'age_gate', 'reason': str, 'blocked': bool}``
        """
        dob = app_data.get("dob") or app_data.get("date_of_birth")
        age = _age_from_dob(dob)

        if age is None:
            return {
                "rule": "age_gate",
                "reason": "Date of birth missing or unparseable; cannot verify age.",
                "blocked": True,
            }
        if age < 18:
            return {
                "rule": "age_gate",
                "reason": f"Applicant age ({age}) is below the minimum of 18.",
                "blocked": True,
            }
        if age > 75:
            return {
                "rule": "age_gate",
                "reason": f"Applicant age ({age}) exceeds the maximum of 75.",
                "blocked": True,
            }
        return {
            "rule": "age_gate",
            "reason": f"Applicant age ({age}) is within allowed range.",
            "blocked": False,
        }

    def ssn_fraud_gate(self, app_data: Dict[str, Any]) -> Dict[str, Any]:
        """Hard cut — SSN matches known fraud / test patterns.

        Declines if SSN starts with 000, 666, or 900–999, or if a
        ``'fraud_ssn'`` flag is present in ``app_data``.

        Returns
        -------
        dict
            ``{'rule': 'ssn_fraud_gate', 'reason': str, 'blocked': bool}``
        """
        ssn = str(app_data.get("ssn", "")).replace("-", "").replace(" ", "")

        if not ssn:
            return {
                "rule": "ssn_fraud_gate",
                "reason": "SSN missing; cannot verify.",
                "blocked": True,
            }

        # Simulated fraud patterns
        if ssn.startswith("000"):
            return {
                "rule": "ssn_fraud_gate",
                "reason": "SSN starts with 000 (test/invalid pattern).",
                "blocked": True,
            }
        if ssn.startswith("666"):
            return {
                "rule": "ssn_fraud_gate",
                "reason": "SSN starts with 666 (known invalid pattern).",
                "blocked": True,
            }
        if len(ssn) >= 3 and ssn[:3] >= "900":
            return {
                "rule": "ssn_fraud_gate",
                "reason": f"SSN area number {ssn[:3]} is in the 900+ range (invalid).",
                "blocked": True,
            }
        if app_data.get("fraud_ssn") or app_data.get("fraud_ssn", "").lower() == "true":
            return {
                "rule": "ssn_fraud_gate",
                "reason": "SSN flagged as fraudulent in internal database.",
                "blocked": True,
            }
        return {
            "rule": "ssn_fraud_gate",
            "reason": "SSN passes fraud pattern check.",
            "blocked": False,
        }

    def bankruptcy_gate(
        self, app_data: Dict[str, Any], bureau: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Hard cut — bankruptcy flag present.

        Declines if the bureau data contains a bankruptcy flag *or* the
        applicant self-reported bankruptcy within the last 12 months.

        Returns
        -------
        dict
            ``{'rule': 'bankruptcy_gate', 'reason': str, 'blocked': bool}``
        """
        bureau_bk = bureau.get("bankruptcy_flag", False)
        self_reported = app_data.get("self_reported_bankruptcy", False)

        if bureau_bk:
            bk_date = bureau.get("bankruptcy_date")
            if bk_date:
                return {
                    "rule": "bankruptcy_gate",
                    "reason": f"Bankruptcy on record as of {bk_date}.",
                    "blocked": True,
                }
            return {
                "rule": "bankruptcy_gate",
                "reason": "Bankruptcy flag present in credit bureau data.",
                "blocked": True,
            }

        if self_reported:
            return {
                "rule": "bankruptcy_gate",
                "reason": "Applicant self-reported a bankruptcy within 12 months.",
                "blocked": True,
            }

        return {
            "rule": "bankruptcy_gate",
            "reason": "No bankruptcy flag detected.",
            "blocked": False,
        }

    def existing_active_loan_gate(
        self, app_data: Dict[str, Any], bureau: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Hard cut — borrower already has an active PalmFi loan.

        Checks the ``'existing_customer'`` flag in ``app_data`` and the
        number of active loans reported by the bureau (3+ active loans
        on file is treated as a risk proxy for existing exposure).

        Returns
        -------
        dict
            ``{'rule': 'existing_active_loan_gate', 'reason': str, 'blocked': bool}``
        """
        existing = app_data.get("existing_customer", False)
        if existing:
            return {
                "rule": "existing_active_loan_gate",
                "reason": "Borrower already has an active PalmFi loan on file.",
                "blocked": True,
            }

        active_loans = bureau.get("active_loans", 0)
        if isinstance(active_loans, (int, float)) and active_loans >= 3:
            return {
                "rule": "existing_active_loan_gate",
                "reason": f"Bureau reports {int(active_loans)} active loans; "
                f"excessive concurrent exposure.",
                "blocked": True,
            }

        return {
            "rule": "existing_active_loan_gate",
            "reason": "No existing active loan detected.",
            "blocked": False,
        }

    def previous_chargeoff_gate(
        self, app_data: Dict[str, Any], bureau: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Hard cut — previous charge-off with PalmFi.

        Declines if bureau data shows a charge-off within the last 24
        months, or if the applicant self-reported a charge-off.

        Returns
        -------
        dict
            ``{'rule': 'previous_chargeoff_gate', 'reason': str, 'blocked': bool}``
        """
        chargeoff_bureau = bureau.get("chargeoff_in_24mo", False)
        chargeoff_self = app_data.get("self_reported_chargeoff", False)

        if chargeoff_bureau:
            co_date = bureau.get("chargeoff_date")
            detail = f"on {co_date}" if co_date else "in last 24 months"
            return {
                "rule": "previous_chargeoff_gate",
                "reason": f"Charge-off reported {detail}.",
                "blocked": True,
            }

        if chargeoff_self:
            return {
                "rule": "previous_chargeoff_gate",
                "reason": "Applicant self-reported a previous charge-off.",
                "blocked": True,
            }

        return {
            "rule": "previous_chargeoff_gate",
            "reason": "No previous charge-off detected.",
            "blocked": False,
        }

    def state_restriction_gate(self, app_data: Dict[str, Any]) -> Dict[str, Any]:
        """Hard cut — state not in licensed operating set.

        PalmFi is currently licensed in: VA, TX, FL, NC, GA, AZ.

        Returns
        -------
        dict
            ``{'rule': 'state_restriction_gate', 'reason': str, 'blocked': bool}``
        """
        state = str(app_data.get("state", "")).strip().upper()

        if not state:
            return {
                "rule": "state_restriction_gate",
                "reason": "State is missing from application.",
                "blocked": True,
            }
        if not self.is_allowed_state(state):
            return {
                "rule": "state_restriction_gate",
                "reason": f"State '{state}' is not in PalmFi's licensed "
                f"operating area ({', '.join(sorted(self._allowed_states))}).",
                "blocked": True,
            }
        return {
            "rule": "state_restriction_gate",
            "reason": f"State '{state}' is in operating area.",
            "blocked": False,
        }

    def amount_range_gate(self, app_data: Dict[str, Any]) -> Dict[str, Any]:
        """Hard cut — loan amount outside $500–$5 000.

        PalmFi's product range is $500–$5 000.  Amounts outside this
        range are declined.

        Returns
        -------
        dict
            ``{'rule': 'amount_range_gate', 'reason': str, 'blocked': bool}``
        """
        amount = app_data.get("loan_amount")

        if amount is None:
            return {
                "rule": "amount_range_gate",
                "reason": "Loan amount is missing.",
                "blocked": True,
            }
        try:
            amount = float(amount)
        except (TypeError, ValueError):
            return {
                "rule": "amount_range_gate",
                "reason": f"Loan amount '{amount}' is not a valid number.",
                "blocked": True,
            }

        if amount < 500:
            return {
                "rule": "amount_range_gate",
                "reason": f"Loan amount ${amount:,.2f} is below the $500 minimum.",
                "blocked": True,
            }
        if amount > 5000:
            return {
                "rule": "amount_range_gate",
                "reason": f"Loan amount ${amount:,.2f} exceeds the $5,000 maximum.",
                "blocked": True,
            }
        return {
            "rule": "amount_range_gate",
            "reason": f"Loan amount ${amount:,.2f} is within $500–$5,000 range.",
            "blocked": False,
        }

    def term_range_gate(self, app_data: Dict[str, Any]) -> Dict[str, Any]:
        """Hard cut — term outside 6–24 months.

        PalmFi offers 6 to 24 month terms.  Terms outside this range
        are declined.

        Returns
        -------
        dict
            ``{'rule': 'term_range_gate', 'reason': str, 'blocked': bool}``
        """
        term = app_data.get("term_months")

        if term is None:
            return {
                "rule": "term_range_gate",
                "reason": "Loan term is missing.",
                "blocked": True,
            }
        try:
            term = int(term)
        except (TypeError, ValueError):
            return {
                "rule": "term_range_gate",
                "reason": f"Term '{term}' is not a valid integer.",
                "blocked": True,
            }

        if term < 6:
            return {
                "rule": "term_range_gate",
                "reason": f"Term of {term} months is below the 6-month minimum.",
                "blocked": True,
            }
        if term > 24:
            return {
                "rule": "term_range_gate",
                "reason": f"Term of {term} months exceeds the 24-month maximum.",
                "blocked": True,
            }
        return {
            "rule": "term_range_gate",
            "reason": f"Term of {term} months is within 6–24 month range.",
            "blocked": False,
        }

    def ofac_sanctions_gate(self, app_data: Dict[str, Any]) -> Dict[str, Any]:
        """Hard cut — name matches OFAC sanctions list (simulated).

        Simulates OFAC screening by checking for the word
        ``'SANCTION'`` in the applicant's name or a
        ``'ofac_flagged'`` key in ``app_data``.

        Returns
        -------
        dict
            ``{'rule': 'ofac_sanctions_gate', 'reason': str, 'blocked': bool}``
        """
        name = str(app_data.get("name", ""))
        name_upper = name.upper()

        if "SANCTION" in name_upper or "SANCTIONS" in name_upper:
            return {
                "rule": "ofac_sanctions_gate",
                "reason": f"Name '{name}' triggered OFAC sanctions match (simulated).",
                "blocked": True,
            }
        if app_data.get("ofac_flagged", False):
            return {
                "rule": "ofac_sanctions_gate",
                "reason": "Applicant flagged on OFAC sanctions list.",
                "blocked": True,
            }
        return {
            "rule": "ofac_sanctions_gate",
            "reason": "No OFAC sanctions match detected.",
            "blocked": False,
        }

    def death_master_gate(
        self, app_data: Dict[str, Any], bureau: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Hard cut — SSN matches Death Master File (simulated).

        Checks for a death flag in the bureau data, which simulates a
        Social Security Death Master File lookup.

        Returns
        -------
        dict
            ``{'rule': 'death_master_gate', 'reason': str, 'blocked': bool}``
        """
        if bureau.get("death_flag", False):
            ssn = str(app_data.get("ssn", "")).replace("-", "")
            masked = f"***-**-{ssn[-4:]}" if len(ssn) >= 4 else "unknown"
            return {
                "rule": "death_master_gate",
                "reason": f"SSN ending in {masked} matches Death Master File record.",
                "blocked": True,
            }
        if app_data.get("death_master_flag", False):
            return {
                "rule": "death_master_gate",
                "reason": "SSN flagged in Death Master File (internal flag).",
                "blocked": True,
            }
        return {
            "rule": "death_master_gate",
            "reason": "No Death Master File match detected.",
            "blocked": False,
        }

    # ──────────────────────────────────────────────────────────────────
    #  Suppression Rules  (override model — manual review)
    # ──────────────────────────────────────────────────────────────────

    def velocity_check(
        self,
        app_data: Dict[str, Any],
        history: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Suppression — same SSN/email submitted >3 times in 24 h.

        Counts recent submissions (same SSN or email) within the last
        24 hours from the optional *history* list.

        Returns
        -------
        dict
            ``{'rule': 'velocity_check', 'reason': str, 'flagged': bool}``
        """
        ssn = str(app_data.get("ssn", "")).replace("-", "").replace(" ", "")
        email = str(app_data.get("email", "")).strip().lower()

        if not history:
            return {
                "rule": "velocity_check",
                "reason": "No application history available for velocity check.",
                "flagged": False,
            }

        now = datetime.datetime.now()
        window_start = now - datetime.timedelta(hours=24)
        count = 0

        for entry in history:
            ts = entry.get("submission_time")
            if ts is None:
                continue
            # Parse submission_time
            entry_time = None
            if isinstance(ts, datetime.datetime):
                entry_time = ts
            elif isinstance(ts, str):
                try:
                    entry_time = datetime.datetime.fromisoformat(ts)
                except ValueError:
                    pass
            elif isinstance(ts, (int, float)):
                try:
                    entry_time = datetime.datetime.fromtimestamp(float(ts))
                except (OSError, ValueError):
                    pass

            if entry_time is None or entry_time < window_start:
                continue

            entry_ssn = str(entry.get("ssn", "")).replace("-", "").replace(" ", "")
            entry_email = str(entry.get("email", "")).strip().lower()

            if entry_ssn == ssn or entry_email == email:
                count += 1

        if count > 3:
            return {
                "rule": "velocity_check",
                "reason": f"SSN/email submitted {count} times in the last 24 hours "
                f"(limit: 3).",
                "flagged": True,
            }
        return {
            "rule": "velocity_check",
            "reason": f"SSN/email submitted {count} time(s) in the last 24 hours.",
            "flagged": False,
        }

    def address_instability(
        self, app_data: Dict[str, Any], bureau: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Suppression — >2 address changes in last 6 months.

        Uses ``address_changes_6mo`` from bureau data.

        Returns
        -------
        dict
            ``{'rule': 'address_instability', 'reason': str, 'flagged': bool}``
        """
        changes = bureau.get("address_changes_6mo", 0)

        try:
            changes = int(changes)
        except (TypeError, ValueError):
            return {
                "rule": "address_instability",
                "reason": "Address change data unavailable.",
                "flagged": False,
            }

        if changes > 2:
            return {
                "rule": "address_instability",
                "reason": f"{changes} address changes in the last 6 months "
                f"(threshold: 2).",
                "flagged": True,
            }
        return {
            "rule": "address_instability",
            "reason": f"{changes} address change(s) in the last 6 months.",
            "flagged": False,
        }

    def income_discrepancy(
        self, app_data: Dict[str, Any], bureau: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Suppression — stated vs. bureau-reported income differs >50 %.

        Compares the ``'annual_income'`` in *app_data* with
        ``'stated_income'`` in *bureau*.  A difference greater than
        50 % (in either direction) flags the application.

        Returns
        -------
        dict
            ``{'rule': 'income_discrepancy', 'reason': str, 'flagged': bool}``
        """
        stated = app_data.get("annual_income")
        bureau_income = bureau.get("stated_income")

        if stated is None or bureau_income is None:
            return {
                "rule": "income_discrepancy",
                "reason": "Insufficient income data for comparison.",
                "flagged": False,
            }

        try:
            stated = float(stated)
            bureau_income = float(bureau_income)
        except (TypeError, ValueError):
            return {
                "rule": "income_discrepancy",
                "reason": "Income values are not valid numbers.",
                "flagged": False,
            }

        if stated <= 0 or bureau_income <= 0:
            return {
                "rule": "income_discrepancy",
                "reason": "Non-positive income value; cannot compare.",
                "flagged": False,
            }

        larger = max(stated, bureau_income)
        smaller = min(stated, bureau_income)
        ratio = larger / smaller

        if ratio > 1.5:  # > 50% difference
            diff_pct = round((ratio - 1) * 100)
            return {
                "rule": "income_discrepancy",
                "reason": f"Stated income (${stated:,.0f}) vs. bureau-reported "
                f"(${bureau_income:,.0f}) differs by {diff_pct}% (threshold: 50%).",
                "flagged": True,
            }
        return {
            "rule": "income_discrepancy",
            "reason": f"Stated income (${stated:,.0f}) is consistent with "
            f"bureau data (${bureau_income:,.0f}).",
            "flagged": False,
        }

    def inquiry_spike(
        self, app_data: Dict[str, Any], bureau: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Suppression — >5 credit inquiries in last 90 days.

        Uses ``credit_inquiries_90d`` from bureau data.

        Returns
        -------
        dict
            ``{'rule': 'inquiry_spike', 'reason': str, 'flagged': bool}``
        """
        inquiries = bureau.get("credit_inquiries_90d", 0)

        try:
            inquiries = int(inquiries)
        except (TypeError, ValueError):
            return {
                "rule": "inquiry_spike",
                "reason": "Credit inquiry data unavailable.",
                "flagged": False,
            }

        if inquiries > 5:
            return {
                "rule": "inquiry_spike",
                "reason": f"{inquiries} credit inquiries in the last 90 days "
                f"(threshold: 5).",
                "flagged": True,
            }
        return {
            "rule": "inquiry_spike",
            "reason": f"{inquiries} credit inquiry(ies) in the last 90 days.",
            "flagged": False,
        }

    def high_risk_zip(self, app_data: Dict[str, Any]) -> Dict[str, Any]:
        """Suppression — ZIP code in high-risk list.

        Checks the applicant's ZIP code against a configurable set of
        high-risk ZIP codes (initialised with a curated set of VA ZIPs).
        Also respects a ``'high_risk_zip'`` boolean flag in app_data.

        Returns
        -------
        dict
            ``{'rule': 'high_risk_zip', 'reason': str, 'flagged': bool}``
        """
        zip_code = str(app_data.get("zip_code", "")).strip()[:5]
        flag = app_data.get("high_risk_zip", False)

        if flag:
            return {
                "rule": "high_risk_zip",
                "reason": "Applicant flagged as high-risk ZIP (internal flag).",
                "flagged": True,
            }
        if zip_code and zip_code in self._high_risk_zips:
            return {
                "rule": "high_risk_zip",
                "reason": f"ZIP code {zip_code} is in the high-risk list.",
                "flagged": True,
            }
        return {
            "rule": "high_risk_zip",
            "reason": f"ZIP code '{zip_code or 'N/A'}' not in high-risk list.",
            "flagged": False,
        }

    def suspicious_timing(self, app_data: Dict[str, Any]) -> Dict[str, Any]:
        """Suppression — application submitted between 12am and 5am.

        Checks the ``'submission_time'`` key.  Applications submitted
        between 00:00 and 05:59 local time are flagged as suspicious.

        Returns
        -------
        dict
            ``{'rule': 'suspicious_timing', 'reason': str, 'flagged': bool}``
        """
        ts = app_data.get("submission_time")

        if ts is None:
            return {
                "rule": "suspicious_timing",
                "reason": "Submission time not available.",
                "flagged": False,
            }

        dt = None
        if isinstance(ts, datetime.datetime):
            dt = ts
        elif isinstance(ts, str):
            try:
                dt = datetime.datetime.fromisoformat(ts)
            except ValueError:
                pass
        elif isinstance(ts, (int, float)):
            try:
                dt = datetime.datetime.fromtimestamp(float(ts))
            except (OSError, ValueError):
                pass

        if dt is None:
            return {
                "rule": "suspicious_timing",
                "reason": "Submission time could not be parsed.",
                "flagged": False,
            }

        hour = dt.hour
        if 0 <= hour < 5:
            return {
                "rule": "suspicious_timing",
                "reason": f"Application submitted at {dt.strftime('%H:%M')} "
                f"(between 12am–5am, considered suspicious timing).",
                "flagged": True,
            }
        return {
            "rule": "suspicious_timing",
            "reason": f"Application submitted at {dt.strftime('%H:%M')} "
            f"(within normal hours).",
            "flagged": False,
        }

    def new_account_velocity(self, app_data: Dict[str, Any]) -> Dict[str, Any]:
        """Suppression — borrower account created <24h before applying.

        Compares ``'account_created_at'`` with ``'submission_time'``.
        If the account was created less than 24 hours before the
        application, it is flagged.

        Returns
        -------
        dict
            ``{'rule': 'new_account_velocity', 'reason': str, 'flagged': bool}``
        """
        created = app_data.get("account_created_at")
        submitted = app_data.get("submission_time")

        if created is None or submitted is None:
            return {
                "rule": "new_account_velocity",
                "reason": "Account creation or submission time missing.",
                "flagged": False,
            }

        def _to_dt(val):
            if isinstance(val, datetime.datetime):
                return val
            if isinstance(val, str):
                try:
                    return datetime.datetime.fromisoformat(val)
                except ValueError:
                    pass
            if isinstance(val, (int, float)):
                try:
                    return datetime.datetime.fromtimestamp(float(val))
                except (OSError, ValueError):
                    pass
            return None

        created_dt = _to_dt(created)
        submitted_dt = _to_dt(submitted)

        if created_dt is None or submitted_dt is None:
            return {
                "rule": "new_account_velocity",
                "reason": "Could not parse account creation or submission time.",
                "flagged": False,
            }

        age = submitted_dt - created_dt

        if age < datetime.timedelta(hours=24):
            hours_old = max(0, round(age.total_seconds() / 3600, 1))
            return {
                "rule": "new_account_velocity",
                "reason": f"Account created {hours_old} hour(s) before application "
                f"(threshold: 24 hours).",
                "flagged": True,
            }
        hours_old = round(age.total_seconds() / 3600, 1)
        return {
            "rule": "new_account_velocity",
            "reason": f"Account age is {hours_old} hour(s) at time of application.",
            "flagged": False,
        }

    # ──────────────────────────────────────────────────────────────────
    #  Soft Overrides  (approve borderline applications)
    # ──────────────────────────────────────────────────────────────────

    def existing_good_customer(self, app_data: Dict[str, Any]) -> Dict[str, Any]:
        """Soft override — 6+ months on-time payment history.

        Checks ``'on_time_payment_months'``.  Borrowers with 6 or more
        consecutive months of on-time payments qualify.

        Returns
        -------
        dict
            ``{'rule': 'existing_good_customer', 'reason': str, 'applies': bool}``
        """
        months = app_data.get("on_time_payment_months", 0)

        try:
            months = int(months)
        except (TypeError, ValueError):
            return {
                "rule": "existing_good_customer",
                "reason": "On-time payment data unavailable.",
                "applies": False,
            }

        if months >= 6:
            return {
                "rule": "existing_good_customer",
                "reason": f"Borrower has {months} months of on-time payment history "
                f"(threshold: 6).",
                "applies": True,
            }
        return {
            "rule": "existing_good_customer",
            "reason": f"Borrower has {months} month(s) of on-time payment history.",
            "applies": False,
        }

    def veteran_status(self, app_data: Dict[str, Any]) -> Dict[str, Any]:
        """Soft override — applicant is a veteran.

        Checks the ``'veteran'`` boolean flag in app data.

        Returns
        -------
        dict
            ``{'rule': 'veteran_status', 'reason': str, 'applies': bool}``
        """
        if app_data.get("veteran", False):
            return {
                "rule": "veteran_status",
                "reason": "Applicant is an honourably-discharged veteran.",
                "applies": True,
            }
        return {
            "rule": "veteran_status",
            "reason": "Applicant is not a veteran or status unknown.",
            "applies": False,
        }

    def referral_from_good(self, app_data: Dict[str, Any]) -> Dict[str, Any]:
        """Soft override — referred by a borrower in good standing.

        Checks ``'referral_code'``.  A non-empty referral code that
        does not match the explicit exclusion flag
        ``'referral_bad_standing'`` is treated as a positive signal.

        Returns
        -------
        dict
            ``{'rule': 'referral_from_good', 'reason': str, 'applies': bool}``
        """
        referral = app_data.get("referral_code")
        bad_standing = app_data.get("referral_bad_standing", False)

        if referral and not bad_standing:
            return {
                "rule": "referral_from_good",
                "reason": f"Referred via code '{referral}' from a borrower "
                f"in good standing.",
                "applies": True,
            }
        if referral and bad_standing:
            return {
                "rule": "referral_from_good",
                "reason": f"Referral code '{referral}' is from a borrower "
                f"not in good standing.",
                "applies": False,
            }
        return {
            "rule": "referral_from_good",
            "reason": "No referral code provided.",
            "applies": False,
        }

    # ──────────────────────────────────────────────────────────────────
    #  Internal helpers
    # ──────────────────────────────────────────────────────────────────

    def _build_summary(
        self,
        hard_cut_blocked: bool,
        suppression_flagged: bool,
        soft_override_applies: bool,
        hard_cuts: List[Dict[str, Any]],
        suppressions: List[Dict[str, Any]],
        soft_overrides: List[Dict[str, Any]],
    ) -> str:
        """Build a human-readable gating summary."""
        parts: List[str] = []

        triggered_hard = [h for h in hard_cuts if h["blocked"]]
        triggered_supp = [s for s in suppressions if s["flagged"]]
        triggered_soft = [s for s in soft_overrides if s["applies"]]

        if hard_cut_blocked:
            parts.append(
                f"⛔ DECLINED — {len(triggered_hard)} hard cut(s) triggered: "
                + "; ".join(h["reason"] for h in triggered_hard)
            )
        if suppression_flagged:
            parts.append(
                f"⚠️  {len(triggered_supp)} suppression(s) flagged: "
                + "; ".join(s["reason"] for s in triggered_supp)
            )
        if soft_override_applies:
            parts.append(
                f"✅ {len(triggered_soft)} soft override(s) apply: "
                + "; ".join(s["reason"] for s in triggered_soft)
            )

        if not hard_cut_blocked and not suppression_flagged and not soft_override_applies:
            return "All gating rules passed — application ready for scoring."

        if hard_cut_blocked:
            return " | ".join(parts)

        if suppression_flagged:
            parts.append("Application flagged for manual review.")
            return " | ".join(parts)

        if soft_override_applies:
            parts.append("Soft overrides available to boost borderline applications.")
            return " | ".join(parts)

        return "All gating rules passed — application ready for scoring."


# ══════════════════════════════════════════════════════════════════════
#  Tests
# ══════════════════════════════════════════════════════════════════════

def _make_app(**overrides) -> Dict[str, Any]:
    """Build a standard valid application for testing."""
    base = {
        "dob": "1990-06-15",
        "ssn": "123-45-6789",
        "name": "Jane Doe",
        "email": "jane@example.com",
        "state": "VA",
        "loan_amount": 2500,
        "term_months": 12,
        "annual_income": 60000,
        "zip_code": "20147",
        "submission_time": datetime.datetime.now().isoformat(),
        "account_created_at": (
            datetime.datetime.now() - datetime.timedelta(days=30)
        ).isoformat(),
    }
    base.update(overrides)
    return base


def test_hard_cuts() -> None:
    """Run hard cut rule tests."""
    g = GatingRules()

    # 1. Age gate
    assert g.age_gate(_make_app(dob="2010-01-01"))["blocked"], "Under 18 should block"
    assert g.age_gate(_make_app(dob="1945-01-01"))["blocked"], "Over 75 should block"
    assert not g.age_gate(_make_app(dob="1990-06-15"))["blocked"], "30yo should pass"
    assert g.age_gate(_make_app())["blocked"] is False, "Default 1990 should pass age"

    # 2. SSN fraud gate
    assert g.ssn_fraud_gate(_make_app(ssn="000-45-6789"))["blocked"], "000 SSN blocks"
    assert g.ssn_fraud_gate(_make_app(ssn="666-45-6789"))["blocked"], "666 SSN blocks"
    assert g.ssn_fraud_gate(_make_app(ssn="900-45-6789"))["blocked"], "900+ SSN blocks"
    assert g.ssn_fraud_gate(_make_app(ssn="123-45-6789", fraud_ssn=True))["blocked"]
    assert not g.ssn_fraud_gate(_make_app(ssn="123-45-6789"))["blocked"]

    # 3. Bankruptcy gate
    assert g.bankruptcy_gate(_make_app(), {"bankruptcy_flag": True})["blocked"]
    assert g.bankruptcy_gate(
        _make_app(self_reported_bankruptcy=True), {}
    )["blocked"]
    assert not g.bankruptcy_gate(_make_app(), {})["blocked"]

    # 4. Existing active loan gate
    assert g.existing_active_loan_gate(
        _make_app(existing_customer=True), {}
    )["blocked"]
    assert g.existing_active_loan_gate(
        _make_app(), {"active_loans": 3}
    )["blocked"]
    assert not g.existing_active_loan_gate(
        _make_app(), {"active_loans": 1}
    )["blocked"]

    # 5. Previous chargeoff gate
    assert g.previous_chargeoff_gate(
        _make_app(), {"chargeoff_in_24mo": True}
    )["blocked"]
    assert g.previous_chargeoff_gate(
        _make_app(self_reported_chargeoff=True), {}
    )["blocked"]
    assert not g.previous_chargeoff_gate(_make_app(), {})["blocked"]

    # 6. State restriction gate
    assert g.state_restriction_gate(_make_app(state="CA"))["blocked"]
    assert g.state_restriction_gate(_make_app(state="VA"))["blocked"] is False
    assert g.state_restriction_gate(_make_app(state="tx"))["blocked"] is False

    # 7. Amount range gate
    assert g.amount_range_gate(_make_app(loan_amount=100))["blocked"]
    assert g.amount_range_gate(_make_app(loan_amount=10000))["blocked"]
    assert not g.amount_range_gate(_make_app(loan_amount=2500))["blocked"]
    assert not g.amount_range_gate(_make_app(loan_amount=500))["blocked"]
    assert not g.amount_range_gate(_make_app(loan_amount=5000))["blocked"]

    # 8. Term range gate
    assert g.term_range_gate(_make_app(term_months=3))["blocked"]
    assert g.term_range_gate(_make_app(term_months=36))["blocked"]
    assert not g.term_range_gate(_make_app(term_months=12))["blocked"]
    assert not g.term_range_gate(_make_app(term_months=6))["blocked"]
    assert not g.term_range_gate(_make_app(term_months=24))["blocked"]

    # 9. OFAC sanctions gate
    assert g.ofac_sanctions_gate(_make_app(name="John Sanction"))["blocked"]
    assert g.ofac_sanctions_gate(_make_app(name="Jane", ofac_flagged=True))["blocked"]
    assert not g.ofac_sanctions_gate(_make_app(name="Jane Doe"))["blocked"]

    # 10. Death master gate
    assert g.death_master_gate(_make_app(), {"death_flag": True})["blocked"]
    assert g.death_master_gate(
        _make_app(death_master_flag=True), {}
    )["blocked"]
    assert not g.death_master_gate(_make_app(), {})["blocked"]

    print("✅  All hard cut tests passed.")


def test_suppressions() -> None:
    """Run suppression rule tests."""
    g = GatingRules()
    now = datetime.datetime.now()

    # 1. Velocity check
    recent_history = [
        {"ssn": "123-45-6789", "email": "jane@example.com",
         "submission_time": (now - datetime.timedelta(hours=1)).isoformat()},
        {"ssn": "123-45-6789", "email": "jane@example.com",
         "submission_time": (now - datetime.timedelta(hours=2)).isoformat()},
        {"ssn": "123-45-6789", "email": "jane@example.com",
         "submission_time": (now - datetime.timedelta(hours=3)).isoformat()},
        {"ssn": "123-45-6789", "email": "jane@example.com",
         "submission_time": (now - datetime.timedelta(hours=4)).isoformat()},
    ]
    assert g.velocity_check(
        _make_app(), recent_history
    )["flagged"], "4+ submissions should flag"

    low_history = [
        {"ssn": "123-45-6789", "email": "jane@example.com",
         "submission_time": (now - datetime.timedelta(hours=1)).isoformat()},
    ]
    assert not g.velocity_check(
        _make_app(), low_history
    )["flagged"], "1 submission should not flag"

    # 2. Address instability
    assert g.address_instability(
        _make_app(), {"address_changes_6mo": 3}
    )["flagged"]
    assert not g.address_instability(
        _make_app(), {"address_changes_6mo": 1}
    )["flagged"]

    # 3. Income discrepancy
    assert g.income_discrepancy(
        _make_app(annual_income=60000), {"stated_income": 15000}
    )["flagged"]
    assert not g.income_discrepancy(
        _make_app(annual_income=60000), {"stated_income": 55000}
    )["flagged"]

    # 4. Inquiry spike
    assert g.inquiry_spike(
        _make_app(), {"credit_inquiries_90d": 6}
    )["flagged"]
    assert not g.inquiry_spike(
        _make_app(), {"credit_inquiries_90d": 3}
    )["flagged"]

    # 5. High-risk ZIP
    assert g.high_risk_zip(_make_app(zip_code="23223"))["flagged"]
    assert g.high_risk_zip(_make_app(zip_code="23224"))["flagged"]
    assert not g.high_risk_zip(_make_app(zip_code="20147"))["flagged"]
    # Test flag-based
    assert g.high_risk_zip(
        _make_app(zip_code="20147", high_risk_zip=True)
    )["flagged"]

    # 6. Suspicious timing
    assert g.suspicious_timing(
        _make_app(submission_time="2025-01-01T03:30:00")
    )["flagged"]
    assert not g.suspicious_timing(
        _make_app(submission_time="2025-01-01T14:30:00")
    )["flagged"]

    # 7. New account velocity
    assert g.new_account_velocity(_make_app(
        account_created_at=(
            datetime.datetime.now() - datetime.timedelta(hours=2)
        ).isoformat()
    ))["flagged"]
    assert not g.new_account_velocity(_make_app(
        account_created_at=(
            datetime.datetime.now() - datetime.timedelta(days=30)
        ).isoformat()
    ))["flagged"]

    print("✅  All suppression tests passed.")


def test_soft_overrides() -> None:
    """Run soft override tests."""
    g = GatingRules()

    # 1. Existing good customer
    assert g.existing_good_customer(
        _make_app(on_time_payment_months=6)
    )["applies"]
    assert not g.existing_good_customer(
        _make_app(on_time_payment_months=3)
    )["applies"]

    # 2. Veteran status
    assert g.veteran_status(_make_app(veteran=True))["applies"]
    assert not g.veteran_status(_make_app(veteran=False))["applies"]

    # 3. Referral from good
    assert g.referral_from_good(
        _make_app(referral_code="FRIEND123")
    )["applies"]
    assert not g.referral_from_good(
        _make_app(referral_code="BAD123", referral_bad_standing=True)
    )["applies"]
    assert not g.referral_from_good(_make_app())["applies"]

    print("✅  All soft override tests passed.")


def test_evaluate_integration() -> None:
    """Run integration tests on the full evaluate() workflow."""
    g = GatingRules()

    # Case 1: All clean — everything passes
    result = g.evaluate(_make_app())
    assert not result["hard_cut_blocked"], "Clean app should not hard block"
    assert not result["suppression_flagged"], "Clean app should not suppress"
    assert not result["soft_override_applies"], "Clean app has no overrides"
    assert "passed" in result["gating_summary"].lower()

    # Case 2: Hard cut triggered
    result = g.evaluate(_make_app(loan_amount=100))
    assert result["hard_cut_blocked"]
    assert len([h for h in result["hard_cuts"] if h["blocked"]]) >= 1

    # Case 3: Suppression triggered
    result = g.evaluate(
        _make_app(zip_code="23223"),
    )
    assert result["suppression_flagged"]
    assert not result["hard_cut_blocked"]

    # Case 4: Soft override applies
    result = g.evaluate(_make_app(veteran=True))
    assert result["soft_override_applies"]

    # Case 5: Multiple categories
    result = g.evaluate(
        _make_app(veteran=True, zip_code="23223"),
        bureau_data={"credit_inquiries_90d": 7},
    )
    assert result["suppression_flagged"]
    assert result["soft_override_applies"]
    assert not result["hard_cut_blocked"]

    # Case 6: Hard cut takes priority
    result = g.evaluate(
        _make_app(loan_amount=100, veteran=True),
    )
    assert result["hard_cut_blocked"]
    # Soft overrides still evaluated
    assert result["soft_override_applies"]

    print("✅  All integration tests passed.")


def test_edge_cases() -> None:
    """Test edge cases and boundary conditions."""
    g = GatingRules()

    # Boundary hard cuts — use explicit dates to avoid leap-year drift
    today = datetime.date.today()
    exact_18_bday = today.replace(year=today.year - 18)
    day_before_18 = exact_18_bday + datetime.timedelta(days=1)  # 17 years old
    assert not g.age_gate(
        _make_app(dob=exact_18_bday.isoformat())
    )["blocked"], f"Exact 18th birthday ({exact_18_bday}) should pass"
    assert g.age_gate(
        _make_app(dob=day_before_18.isoformat())
    )["blocked"], f"Day before 18th ({day_before_18}) should block"

    # Edge amounts
    assert not g.amount_range_gate(_make_app(loan_amount=500))["blocked"]
    assert not g.amount_range_gate(_make_app(loan_amount=5000))["blocked"]
    assert g.amount_range_gate(_make_app(loan_amount=499.99))["blocked"]
    assert g.amount_range_gate(_make_app(loan_amount=5000.01))["blocked"]

    # Edge terms
    assert not g.term_range_gate(_make_app(term_months=6))["blocked"]
    assert not g.term_range_gate(_make_app(term_months=24))["blocked"]
    assert g.term_range_gate(_make_app(term_months=5))["blocked"]
    assert g.term_range_gate(_make_app(term_months=25))["blocked"]

    # Missing data
    assert g.age_gate(_make_app(dob=None))["blocked"]
    assert g.amount_range_gate(_make_app(loan_amount=None))["blocked"]
    assert g.term_range_gate(_make_app(term_months=None))["blocked"]

    # is_allowed_state
    assert g.is_allowed_state("VA")
    assert g.is_allowed_state("TX")
    assert not g.is_allowed_state("CA")
    assert not g.is_allowed_state("")

    # add_high_risk_zip
    g.add_high_risk_zip("99999")
    assert g.high_risk_zip(_make_app(zip_code="99999"))["flagged"]

    # SUPPRESSION_CATEGORIES constant
    assert SUPPRESSION_CATEGORIES["velocity"] == "HIGH"
    assert SUPPRESSION_CATEGORIES["instability"] == "LOW"

    print("✅  All edge case tests passed.")


def test_dob_parsing() -> None:
    """Test the DOB parsing utility."""
    # ISO format
    assert _age_from_dob("1990-06-15") == datetime.date.today().year - 1990 - (
        (datetime.date.today().month, datetime.date.today().day) < (6, 15)
    )
    # date object
    assert _age_from_dob(datetime.date(1990, 6, 15)) == _age_from_dob("1990-06-15")
    # None
    assert _age_from_dob(None) is None
    # Empty string
    assert _age_from_dob("") is None

    print("✅  All DOB parsing tests passed.")


if __name__ == "__main__":
    print("═" * 60)
    print("  Gating Rules Engine — Test Suite")
    print("═" * 60)
    print()
    test_dob_parsing()
    test_hard_cuts()
    test_suppressions()
    test_soft_overrides()
    test_edge_cases()
    test_evaluate_integration()
    print()
    print("═" * 60)
    print("  ✅  All tests passed successfully!")
    print("═" * 60)
