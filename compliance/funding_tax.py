"""Funding, CECL allowance, and P&L reporting.

CECL (ASC 326) requires recognition of expected credit losses over the life
of the asset at origination. PalmFi edition — keeps capital pools, loan
disbursement, 1099-INT, CECL reserves, and P&L dashboard while using
SunCredit's simpler approach (no fragile path resolution, no _resolve()).
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# PART 1 — Funding & Capital
# ═══════════════════════════════════════════════════════════════

def create_capital_pool(
    pool_name: str,
    initial_cents: int,
    interest_rate: float = 0.0,
    description: str = "",
    db_connection=None,
) -> dict:
    """Create a new capital pool."""
    close_db = False
    if db_connection is None:
        import sqlite3

        db_connection = sqlite3.connect(":memory:")
        close_db = True
    db = db_connection
    try:
        _ensure_funding_tables(db)
        db.execute(
            "INSERT INTO capital_pools (pool_name, description, total_capital_cents, available_cents, committed_cents, interest_rate) "
            "VALUES (?, ?, ?, ?, 0, ?)",
            (pool_name, description, initial_cents, initial_cents, interest_rate),
        )
        db.commit()
        pool_id = db.execute("SELECT last_insert_rowid() as id").fetchone()["id"]
        logger.info("Capital pool '%s' created with $%.2f", pool_name, initial_cents / 100)
        return {"pool_id": pool_id, "pool_name": pool_name, "initial_capital": initial_cents}
    finally:
        if close_db:
            db.close()


def add_capital(pool_id: int, amount_cents: int, db_connection=None) -> dict:
    """Add capital to an existing pool."""
    close_db = False
    if db_connection is None:
        import sqlite3

        db_connection = sqlite3.connect(":memory:")
        close_db = True
    db = db_connection
    try:
        _ensure_funding_tables(db)
        db.execute(
            "UPDATE capital_pools SET total_capital_cents = total_capital_cents + ?, available_cents = available_cents + ? WHERE id=?",
            (amount_cents, amount_cents, pool_id),
        )
        db.commit()
        return {"success": True, "added_cents": amount_cents}
    finally:
        if close_db:
            db.close()


def disburse_loan(loan_id: int, db_connection=None) -> dict:
    """Disburse a loan: mark as active, create funding record, update pool."""
    close_db = False
    if db_connection is None:
        import sqlite3

        db_connection = sqlite3.connect(":memory:")
        close_db = True
    db = db_connection
    try:
        _ensure_funding_tables(db)
        loan = dict(db.execute("SELECT * FROM loans WHERE id=?", (loan_id,)).fetchone())
        if not loan:
            return {"success": False, "error": "Loan not found"}
        if loan["status"] != "active":
            return {"success": False, "error": f"Loan status is '{loan['status']}', not 'active'"}

        amount_cents = int(loan["principal"] * 100)

        pool = dict(
            db.execute(
                "SELECT * FROM capital_pools WHERE status='active' AND available_cents >= ? ORDER BY available_cents DESC LIMIT 1",
                (amount_cents,),
            ).fetchone()
            or {}
        )

        funder_name = "PalmFi Capital Pool"
        pool_id = None
        if pool:
            pool_id = pool["id"]
            db.execute(
                "UPDATE capital_pools SET available_cents = available_cents - ?, committed_cents = committed_cents + ? WHERE id=?",
                (amount_cents, amount_cents, pool_id),
            )
            funder_name = pool.get("pool_name", "PalmFi Capital Pool")

        ref_id = f"LOAN-{loan_id}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
        db.execute(
            "INSERT INTO loan_funding (loan_id, pool_id, funder_type, funder_name, amount_cents, funding_date, funding_method, reference_id, notes) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                loan_id,
                pool_id,
                "capital_pool" if pool else "unfunded",
                funder_name,
                amount_cents,
                date.today().isoformat(),
                "ach_intracompany",
                ref_id,
                f"Auto-disbursement for loan {loan_id}",
            ),
        )

        db.commit()
        logger.info("Loan %d disbursed: $%.2f from pool '%s'", loan_id, amount_cents / 100, funder_name)
        return {
            "success": True,
            "loan_id": loan_id,
            "amount_cents": amount_cents,
            "amount_dollars": amount_cents / 100,
            "funding_source": funder_name,
            "pool_id": pool_id,
            "reference_id": ref_id,
            "disbursement_date": date.today().isoformat(),
        }
    finally:
        if close_db:
            db.close()


def auto_funding_check(db_connection=None) -> dict:
    """Check and auto-fund approved loans that haven't been funded."""
    close_db = False
    if db_connection is None:
        import sqlite3

        db_connection = sqlite3.connect(":memory:")
        close_db = True
    db = db_connection
    try:
        _ensure_funding_tables(db)
        loans = db.execute(
            "SELECT l.* FROM loans l LEFT JOIN loan_funding lf ON l.id = lf.loan_id WHERE l.status = 'active' AND lf.id IS NULL"
        ).fetchall()

        results = []
        for loan in loans:
            result = disburse_loan(loan["id"], db)
            results.append(result)

        return {
            "checked": len(loans),
            "funded": sum(1 for r in results if r.get("success")),
            "details": results,
        }
    finally:
        if close_db:
            db.close()


def get_funding_summary(db_connection=None) -> dict:
    """Overall funding status."""
    close_db = False
    if db_connection is None:
        import sqlite3

        db_connection = sqlite3.connect(":memory:")
        close_db = True
    db = db_connection
    try:
        _ensure_funding_tables(db)
        pools = db.execute("SELECT * FROM capital_pools WHERE status='active'").fetchall()
        total = db.execute("SELECT COALESCE(SUM(principal),0) as s FROM loans").fetchone()["s"]
        outstanding = db.execute("SELECT COALESCE(SUM(remaining_balance),0) as s FROM loans WHERE status='active'").fetchone()["s"]
        total_available = sum(p["available_cents"] for p in pools) / 100
        total_committed = sum(p["committed_cents"] for p in pools) / 100
        total_capital = sum(p["total_capital_cents"] for p in pools) / 100
        util = (total_committed / total_capital * 100) if total_capital > 0 else 0
        return {
            "total_originated": float(total),
            "total_outstanding": float(outstanding),
            "capital_pools": len(pools),
            "total_capital": total_capital,
            "available_capital": total_available,
            "committed_capital": total_committed,
            "pool_utilization_pct": round(util, 1),
        }
    finally:
        if close_db:
            db.close()


# ═══════════════════════════════════════════════════════════════
# PART 2 — Tax Reporting (1099-INT)
# ═══════════════════════════════════════════════════════════════

def interest_earned_per_borrower(borrower_id: int, tax_year: int, db_connection=None) -> dict:
    """Calculate total interest paid by borrower in a given tax year."""
    close_db = False
    if db_connection is None:
        import sqlite3

        db_connection = sqlite3.connect(":memory:")
        close_db = True
    db = db_connection
    try:
        _ensure_funding_tables(db)
        loans = db.execute("SELECT id, principal, interest_rate FROM loans WHERE borrower_id=?", (borrower_id,)).fetchall()
        total_interest = 0
        total_principal = 0
        total_payments = 0
        loan_details = []
        for loan in loans:
            payments = db.execute(
                "SELECT COALESCE(SUM(amount_cents),0) as total FROM payments WHERE loan_id=? AND status='completed' AND paid_at LIKE ?",
                (loan["id"], f"{tax_year}%"),
            ).fetchone()
            paid = payments["total"]
            total_payments += paid
            schedule_items = db.execute(
                "SELECT COALESCE(SUM(interest_cents),0) as int_total FROM payment_schedules WHERE loan_id=? AND status='paid'",
                (loan["id"],),
            ).fetchone()
            interest = schedule_items["int_total"] if schedule_items else 0
            total_interest += interest
            total_principal += paid - interest
            loan_details.append({
                "loan_id": loan["id"],
                "principal": loan["principal"],
                "interest_paid_cents": interest,
            })
        return {
            "borrower_id": borrower_id,
            "tax_year": tax_year,
            "total_interest_paid_cents": total_interest,
            "total_interest_paid": round(total_interest / 100, 2),
            "total_principal_paid_cents": total_principal,
            "total_principal_paid": round(total_principal / 100, 2),
            "total_payments": total_payments,
            "qualified_mortgage_interest": False,
            "loans": loan_details,
        }
    finally:
        if close_db:
            db.close()


def generate_1099_int_data(borrower_id: int, tax_year: int, db_connection=None) -> dict:
    """Generate 1099-INT reportable data."""
    interest_data = interest_earned_per_borrower(borrower_id, tax_year, db_connection)
    close_db = False
    if db_connection is None:
        import sqlite3

        db_connection = sqlite3.connect(":memory:")
        close_db = True
    db = db_connection
    try:
        _ensure_funding_tables(db)
        borrower = dict(db.execute("SELECT * FROM borrowers WHERE id=?", (borrower_id,)).fetchone() or {})
        return {
            "form_type": "1099-INT",
            "tax_year": tax_year,
            "payer": {
                "name": "PalmFi Financial Services",
                "tin": "XX-XXXXXXX",
                "address": "1 Financial Plaza, San Francisco, CA 94105",
                "phone": "(800) 555-0199",
            },
            "recipient": {
                "name": f"{borrower.get('first_name', '')} {borrower.get('last_name', '')}",
                "tin": "",
                "address": "",
                "account_number": f"L-{borrower_id:06d}",
            },
            "boxes": {
                "box_1_interest_income": interest_data["total_interest_paid_cents"],
                "box_1_interest_income_dollars": interest_data["total_interest_paid"],
                "box_2_early_withdrawal_penalty": 0,
                "box_3_interest_on_us_savings": 0,
                "box_4_federal_tax_withheld": 0,
                "box_5_investment_expenses": 0,
                "box_6_foreign_tax_paid": 0,
                "box_7_foreign_country": "",
                "box_8_tax_exempt_interest": 0,
                "box_9_specified_private_activity": 0,
                "box_10_market_discount": 0,
                "box_11_bond_premium": 0,
                "box_12_bond_premium_treasury": 0,
                "box_13_bond_premium_tax_exempt": 0,
                "box_14_tax_exempt_amt": 0,
                "box_15_state": "",
                "box_16_state_id": "",
                "box_17_state_tax_withheld": 0,
            },
            "filing_required": interest_data["total_interest_paid"] >= 10.00,
        }
    finally:
        if close_db:
            db.close()


def tax_summary_by_year(tax_year: int, db_connection=None) -> dict:
    """Aggregate tax report for a given year."""
    close_db = False
    if db_connection is None:
        import sqlite3

        db_connection = sqlite3.connect(":memory:")
        close_db = True
    db = db_connection
    try:
        _ensure_funding_tables(db)
        interest = db.execute(
            "SELECT COALESCE(SUM(interest_cents), 0) as total FROM payment_schedules ps "
            "JOIN loans l ON ps.loan_id = l.id WHERE ps.status='paid'"
        ).fetchone()["total"]
        originations = db.execute("SELECT COUNT(*) as c, COALESCE(SUM(principal),0) as s FROM loans").fetchone()
        defaults = db.execute("SELECT COUNT(*) as c, COALESCE(SUM(principal),0) as s FROM loans WHERE status='charged_off'").fetchone()
        borrowers_with_interest = db.execute(
            "SELECT COUNT(DISTINCT l.borrower_id) as c FROM payment_schedules ps "
            "JOIN loans l ON ps.loan_id = l.id WHERE ps.status='paid' AND ps.interest_cents > 0"
        ).fetchone()["c"]
        return {
            "tax_year": tax_year,
            "total_interest_income_cents": interest,
            "total_interest_income_dollars": round(interest / 100, 2),
            "number_of_1099s_required": borrowers_with_interest,
            "total_originations": originations["c"],
            "total_origination_amount": originations["s"],
            "total_defaulted": defaults["c"],
            "total_defaulted_amount": defaults["s"],
        }
    finally:
        if close_db:
            db.close()


# ═══════════════════════════════════════════════════════════════
# PART 3 — CECL Loan Loss Reserve
# ═══════════════════════════════════════════════════════════════

RISK_TIER_RECOVERY: Dict[str, float] = {
    "A": 0.95, "B": 0.85, "C": 0.70,
    "D": 0.50, "E": 0.30, "F": 0.20,
}


def _ensure_funding_tables(db) -> None:
    """Create funding and accounting tables if they don't exist."""
    db.executescript("""
        CREATE TABLE IF NOT EXISTS capital_pools (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pool_name TEXT NOT NULL,
            description TEXT DEFAULT '',
            total_capital_cents INTEGER NOT NULL DEFAULT 0,
            available_cents INTEGER NOT NULL DEFAULT 0,
            committed_cents INTEGER NOT NULL DEFAULT 0,
            interest_rate REAL DEFAULT 0,
            status TEXT DEFAULT 'active',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS loan_funding (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            loan_id INTEGER NOT NULL,
            pool_id INTEGER,
            funder_type TEXT DEFAULT 'capital_pool',
            funder_name TEXT DEFAULT 'PalmFi Capital Pool',
            amount_cents INTEGER NOT NULL DEFAULT 0,
            funding_date TEXT NOT NULL,
            funding_method TEXT DEFAULT 'ach',
            reference_id TEXT DEFAULT '',
            notes TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS loan_loss_reserves (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            loan_id INTEGER NOT NULL,
            reserve_amount_cents INTEGER NOT NULL DEFAULT 0,
            reserve_date TEXT NOT NULL,
            reserve_reason TEXT DEFAULT 'cecl_expected_loss',
            release_date TEXT,
            release_reason TEXT DEFAULT ''
        );
    """)


def calculate_cecl_reserve(loans: Optional[Iterable[Dict[str, Any]]] = None, db_connection=None) -> dict:
    """Calculate Current Expected Credit Loss reserve.

    If `loans` iterable is provided, compute from data directly (pure function).
    Otherwise, fall back to DB query.
    """
    if loans is not None:
        breakdown: List[Dict[str, Any]] = []
        total_balance = 0.0
        total_reserve = 0.0
        for ln in loans:
            bal = float(ln.get("remaining_balance", ln.get("loan_balance", 0.0)))
            tier = str(ln.get("risk_tier", "C") or "C").upper()
            recovery = RISK_TIER_RECOVERY.get(tier, RISK_TIER_RECOVERY["C"])
            exp_loss = bal * (1 - recovery)
            total_balance += bal
            total_reserve += exp_loss
            breakdown.append({
                "loan_id": ln.get("loan_id", ln.get("id")),
                "balance": round(bal, 2),
                "risk_tier": tier,
                "expected_loss": round(exp_loss, 2),
            })
        coverage = (total_reserve / total_balance) if total_balance else 0.0
        return {
            "as_of": datetime.now(timezone.utc).isoformat(),
            "total_loan_balance": round(total_balance, 2),
            "total_reserve_needed": round(total_reserve, 2),
            "coverage_ratio": round(coverage, 4),
            "reserve_ratio_pct": round(coverage * 100, 2),
            "active_loans": len(breakdown),
            "per_tier_breakdown": {},
            "loans": breakdown,
        }

    # DB fallback
    close_db = False
    if db_connection is None:
        import sqlite3

        db_connection = sqlite3.connect(":memory:")
        close_db = True
    db = db_connection
    try:
        _ensure_funding_tables(db)
        active = db.execute(
            "SELECT l.id, l.remaining_balance, a.risk_tier FROM loans l "
            "LEFT JOIN applications a ON l.application_id = a.id WHERE l.status='active'"
        ).fetchall()
        total_balance = 0
        total_reserve = 0
        per_tier = {}
        for loan in active:
            balance = loan["remaining_balance"]
            tier = (loan["risk_tier"] or "C").upper()
            if tier not in RISK_TIER_RECOVERY:
                tier = "C"
            recovery = RISK_TIER_RECOVERY[tier]
            expected_loss = balance * (1 - recovery)
            total_balance += balance
            total_reserve += expected_loss
            if tier not in per_tier:
                per_tier[tier] = {"count": 0, "balance": 0, "reserve": 0}
            per_tier[tier]["count"] += 1
            per_tier[tier]["balance"] += balance
            per_tier[tier]["reserve"] += expected_loss
        reserve_ratio = (total_reserve / total_balance * 100) if total_balance > 0 else 0
        return {
            "total_loan_balance": round(total_balance, 2),
            "total_reserve_needed": round(total_reserve, 2),
            "reserve_ratio_pct": round(reserve_ratio, 2),
            "active_loans": len(active),
            "per_tier_breakdown": per_tier,
        }
    finally:
        if close_db:
            db.close()


def establish_reserves(db_connection=None) -> dict:
    """Create reserve entries for all active loans."""
    cecl = calculate_cecl_reserve(db_connection=db_connection)
    close_db = False
    if db_connection is None:
        import sqlite3

        db_connection = sqlite3.connect(":memory:")
        close_db = True
    db = db_connection
    try:
        _ensure_funding_tables(db)
        active = db.execute(
            "SELECT l.id, a.risk_tier FROM loans l LEFT JOIN applications a ON l.application_id = a.id WHERE l.status='active'"
        ).fetchall()
        count = 0
        for loan in active:
            tier = (loan["risk_tier"] or "C").upper()
            if tier not in RISK_TIER_RECOVERY:
                tier = "C"
            recovery = RISK_TIER_RECOVERY[tier]
            balance = dict(db.execute("SELECT remaining_balance FROM loans WHERE id=?", (loan["id"],)).fetchone())[
                "remaining_balance"
            ]
            reserve = int(balance * (1 - recovery) * 100)
            existing = db.execute(
                "SELECT id FROM loan_loss_reserves WHERE loan_id=? AND release_date IS NULL", (loan["id"],)
            ).fetchone()
            if not existing:
                db.execute(
                    "INSERT INTO loan_loss_reserves (loan_id, reserve_amount_cents, reserve_date, reserve_reason) "
                    "VALUES (?, ?, ?, 'cecl_expected_loss')",
                    (loan["id"], reserve, date.today().isoformat()),
                )
                count += 1
        db.commit()
        return {"reserves_created": count, "cecl_summary": cecl}
    finally:
        if close_db:
            db.close()


def get_reserve_summary(db_connection=None) -> dict:
    """Current reserve status."""
    close_db = False
    if db_connection is None:
        import sqlite3

        db_connection = sqlite3.connect(":memory:")
        close_db = True
    db = db_connection
    try:
        _ensure_funding_tables(db)
        allocated = db.execute(
            "SELECT COALESCE(SUM(reserve_amount_cents),0) as s FROM loan_loss_reserves WHERE release_date IS NULL"
        ).fetchone()["s"]
        released = db.execute(
            "SELECT COALESCE(SUM(reserve_amount_cents),0) as s FROM loan_loss_reserves WHERE release_date IS NOT NULL"
        ).fetchone()["s"]
        return {
            "allocated_cents": allocated,
            "allocated_dollars": round(allocated / 100, 2),
            "released_cents": released,
            "released_dollars": round(released / 100, 2),
            "net_reserve_cents": allocated - released,
            "net_reserve_dollars": round((allocated - released) / 100, 2),
        }
    finally:
        if close_db:
            db.close()


# ═══════════════════════════════════════════════════════════════
# PART 4 — P&L Dashboard Data
# ═══════════════════════════════════════════════════════════════

def profit_and_loss(from_date: str, to_date: str, db_connection=None) -> dict:
    """Generate P&L statement for a date range."""
    close_db = False
    if db_connection is None:
        import sqlite3

        db_connection = sqlite3.connect(":memory:")
        close_db = True
    db = db_connection
    try:
        _ensure_funding_tables(db)
        interest_income_cents = db.execute(
            "SELECT COALESCE(SUM(ps.interest_cents),0) as s FROM payment_schedules ps "
            "JOIN loans l ON ps.loan_id = l.id WHERE ps.status='paid' AND ps.due_date BETWEEN ? AND ?",
            (from_date, to_date),
        ).fetchone()["s"]

        fee_income_cents = db.execute(
            "SELECT COALESCE(SUM(l.origination_fee * 100),0) as s FROM loans l WHERE l.disbursed_at BETWEEN ? AND ?",
            (from_date, to_date),
        ).fetchone()["s"]

        late_fee_cents = db.execute(
            "SELECT COALESCE(COUNT(*),0) * 100 as s FROM (SELECT 1 FROM loans l WHERE l.status='active' AND l.next_payment_date < ?)",
            (date.today().isoformat(),),
        ).fetchone()["s"]

        charge_off_loss_cents = 0
        charged_off = db.execute("SELECT remaining_balance FROM loans WHERE status='charged_off'").fetchall()
        for co in charged_off:
            charge_off_loss_cents += int(co["remaining_balance"] * 100)

        interest_income = interest_income_cents / 100
        fee_income = fee_income_cents / 100
        late_fee_income = late_fee_cents / 100
        charge_off_loss = charge_off_loss_cents / 100
        total_income = interest_income + fee_income + late_fee_income
        total_expenses = charge_off_loss

        reserve = calculate_cecl_reserve(db_connection=db)

        return {
            "period": {"from": from_date, "to": to_date},
            "income": {
                "interest_income": round(interest_income, 2),
                "fee_income": round(fee_income, 2),
                "late_fee_income": round(late_fee_income, 2),
                "total_income": round(total_income, 2),
            },
            "expenses": {
                "charge_off_losses": round(charge_off_loss, 2),
                "operating_expenses": 0.00,
                "total_expenses": round(total_expenses, 2),
            },
            "net_income": round(total_income - total_expenses, 2),
            "loan_loss_provision": round(reserve["total_reserve_needed"], 2),
            "net_after_provision": round(total_income - total_expenses - reserve["total_reserve_needed"], 2),
        }
    finally:
        if close_db:
            db.close()


def get_portfolio_metrics(db_connection=None) -> dict:
    """Key portfolio performance metrics."""
    close_db = False
    if db_connection is None:
        import sqlite3

        db_connection = sqlite3.connect(":memory:")
        close_db = True
    db = db_connection
    try:
        _ensure_funding_tables(db)
        total = db.execute("SELECT COUNT(*) as c FROM loans").fetchone()["c"]
        active = db.execute("SELECT COUNT(*) as c FROM loans WHERE status='active'").fetchone()["c"]
        paid = db.execute("SELECT COUNT(*) as c FROM loans WHERE status='paid_off'").fetchone()["c"]
        defaulted = db.execute("SELECT COUNT(*) as c FROM loans WHERE status='charged_off'").fetchone()["c"]

        delinquent = db.execute(
            "SELECT COUNT(*) as c FROM loans WHERE status='active' AND next_payment_date < ?",
            (date.today().isoformat(),),
        ).fetchone()["c"]

        apr_data = db.execute("SELECT principal, interest_rate FROM loans WHERE status='active'").fetchall()
        weighted_apr = 0
        total_principal = 0
        for l in apr_data:
            weighted_apr += l["principal"] * l["interest_rate"]
            total_principal += l["principal"]
        avg_apr = weighted_apr / total_principal if total_principal > 0 else 0

        outstanding = db.execute(
            "SELECT COALESCE(SUM(remaining_balance),0) as s FROM loans WHERE status='active'"
        ).fetchone()["s"]

        on_time = db.execute("SELECT COUNT(*) as c FROM payments WHERE status='completed'").fetchone()["c"]
        late_payments = db.execute("SELECT COUNT(*) as c FROM collections").fetchone()["c"]
        on_time_rate = (on_time / (on_time + late_payments) * 100) if (on_time + late_payments) > 0 else 100

        avg_loan_size = db.execute("SELECT COALESCE(AVG(principal),0) as s FROM loans").fetchone()["s"]
        del_rate = (delinquent / active * 100) if active > 0 else 0

        return {
            "total_loans": total,
            "active_loans": active,
            "paid_off_loans": paid,
            "charged_off_loans": defaulted,
            "delinquent_loans": delinquent,
            "delinquency_rate_pct": round(del_rate, 2),
            "avg_apr_pct": round(avg_apr, 2),
            "weighted_avg_apr_pct": round(avg_apr, 2),
            "total_outstanding": round(outstanding, 2),
            "on_time_payment_rate_pct": round(on_time_rate, 1),
            "avg_loan_size": round(avg_loan_size, 2),
        }
    finally:
        if close_db:
            db.close()
