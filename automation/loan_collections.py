"""
Automated loan collections engine.

Provides overdue detection, escalation workflow, late fee application,
charge-off processing, and collection statistics for the lending platform.

Works standalone (direct sqlite3) or imported alongside the platform module.
"""

import sys
import os
import sqlite3
import logging
from datetime import datetime, date

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# DB path resolution — works standalone and when imported from platform
# ---------------------------------------------------------------------------

def _resolve_db_path():
    """
    Return the absolute path to lending.db.

    Strategy:
      1. If platform.models is importable, use get_db() from it.
      2. Otherwise derive from this file's location:
         automation/collections.py -> platform/lending.db
    """
    # Try importing from the platform module first
    try:
        module_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if module_dir not in sys.path:
            sys.path.insert(0, module_dir)
        from platform.models import get_db  # noqa: F401
        return None  # signal that get_db function should be used
    except (ImportError, Exception):
        pass

    # Fallback: resolve relative to this file's location
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    db_path = os.path.join(base, 'platform', 'lending.db')
    if not os.path.isfile(db_path):
        logger.warning("Database not found at %s — using path anyway", db_path)
    return db_path


def _get_connection():
    """Return a sqlite3 Connection with row_factory set."""
    resolved = _resolve_db_path()
    if resolved is None:
        # platform.models available
        from platform.models import get_db  # pylint: disable=import-outside-toplevel
        return get_db()

    conn = sqlite3.connect(resolved)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


# ---------------------------------------------------------------------------
# Core helpers
# ---------------------------------------------------------------------------

def _to_dict(row):
    """Convert sqlite3.Row to a plain dict (safely handles None rows)."""
    if row is None:
        return None
    return dict(row)


def _today_str():
    """Return today's date as 'YYYY-MM-DD' string for SQL comparison."""
    return date.today().isoformat()


# ---------------------------------------------------------------------------
# 1. detect_overdue_loans
# ---------------------------------------------------------------------------

def detect_overdue_loans():
    """
    Find all active loans whose next_payment_date is in the past.

    Returns
    -------
    list[dict]
        Each dict contains: loan_id, borrower_id, days_past_due, next_payment_date
    """
    conn = _get_connection()
    try:
        rows = conn.execute(
            """
            SELECT id, borrower_id, next_payment_date
            FROM loans
            WHERE status = 'active'
              AND next_payment_date IS NOT NULL
              AND next_payment_date < ?
            """,
            (_today_str(),),
        ).fetchall()

        overdue = []
        today = date.today()
        for row in rows:
            row_dict = _to_dict(row)
            try:
                next_date = datetime.strptime(row_dict["next_payment_date"], "%Y-%m-%d").date()
            except (ValueError, TypeError):
                logger.warning(
                    "Skipping loan %s — unparseable next_payment_date: %s",
                    row_dict["id"],
                    row_dict["next_payment_date"],
                )
                continue

            days_past = (today - next_date).days
            if days_past < 1:
                continue

            overdue.append({
                "loan_id": row_dict["id"],
                "borrower_id": row_dict["borrower_id"],
                "days_past_due": days_past,
                "next_payment_date": row_dict["next_payment_date"],
            })

        logger.info("detect_overdue_loans: found %d overdue loan(s)", len(overdue))
        return overdue
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 2. escalate_collection
# ---------------------------------------------------------------------------

def escalate_collection(loan_id, borrower_id, days_past_due):
    """
    Determine collection stage and recommended actions for an overdue loan.

    Parameters
    ----------
    loan_id : int
    borrower_id : int
    days_past_due : int  (must be >= 1)

    Returns
    -------
    dict with keys: target_stage, action_description, recommended_actions
    """
    stages = {
        (1, 5): {
            "stage": 0,
            "description": "Auto-reminder",
            "channel": "auto_notification",
            "actions": [
                "Send automated SMS reminder about upcoming/overdue payment",
                "Send in-app notification reminding borrower of due date",
            ],
        },
        (6, 15): {
            "stage": 1,
            "description": "SMS + Email reminder",
            "channel": "sms_email",
            "actions": [
                "Send SMS reminder with overdue amount and late fee warning",
                "Send email with payment link and loan summary",
                "Log collection attempt outcome",
            ],
        },
        (16, 30): {
            "stage": 2,
            "description": "Phone call attempt + late fee applied",
            "channel": "phone",
            "actions": [
                "Initiate phone call to borrower's primary contact number",
                "Apply late fee (5%% of monthly payment) to remaining balance",
                "Offer payment plan or hardship accommodation",
            ],
        },
        (31, 60): {
            "stage": 3,
            "description": "Demand letter + credit bureau notification pending",
            "channel": "demand_letter",
            "actions": [
                "Send formal demand letter via email and postal mail",
                "Prepare credit bureau delinquency report",
                "Escalate to collections supervisor for review",
            ],
        },
        (61, 90): {
            "stage": 4,
            "description": "Legal escalation + debt collection agency referral",
            "channel": "legal",
            "actions": [
                "Refer account to legal department for review",
                "Engage external debt collection agency",
                "Send final notice of intent to pursue legal action",
            ],
        },
        (91, float("inf")): {
            "stage": 5,
            "description": "Charge-off / loan default",
            "channel": "charge_off",
            "actions": [
                "Mark loan as defaulted in system",
                "Write off remaining balance as charge-off",
                "Report charged-off status to credit bureaus",
                "Cease active collection efforts (transfer to recoveries)",
            ],
        },
    }

    target = None
    for (low, high), info in stages.items():
        if low <= days_past_due <= high:
            target = info
            break

    # Fallback safety — should never happen given the float('inf') range above
    if target is None:
        target = stages[(91, float("inf"))]

    action_description = (
        f"Stage {target['stage']} — {target['description']} "
        f"(loan {loan_id}, borrower {borrower_id}, "
        f"{days_past_due} day(s) past due)"
    )

    logger.info(
        "Escalating loan %s / borrower %s: Stage %s — %s",
        loan_id,
        borrower_id,
        target["stage"],
        target["description"],
    )

    return {
        "target_stage": target["stage"],
        "action_description": action_description,
        "recommended_actions": target["actions"],
    }


# ---------------------------------------------------------------------------
# 3. run_collections_cycle
# ---------------------------------------------------------------------------

def _log_collection_action(conn, loan_id, borrower_id, stage, days_past_due,
                            action_taken, channel, response="", outcome=""):
    """Insert a row into the collections table."""
    conn.execute(
        """
        INSERT INTO collections
            (loan_id, borrower_id, collection_stage, days_past_due,
             action_taken, communication_channel, response, outcome)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (loan_id, borrower_id, stage, days_past_due,
         action_taken, channel, response, outcome),
    )


def run_collections_cycle():
    """
    Main entry point: detect overdue loans, escalate each, log actions.

    Returns
    -------
    dict
        Summary with counts and per-loan results.
    """
    overdue = detect_overdue_loans()
    results = []
    stats = {"stage_0": 0, "stage_1": 0, "stage_2": 0,
             "stage_3": 0, "stage_4": 0, "stage_5": 0}

    conn = _get_connection()
    try:
        for item in overdue:
            loan_id = item["loan_id"]
            borrower_id = item["borrower_id"]
            days_past = item["days_past_due"]

            escalation = escalate_collection(loan_id, borrower_id, days_past)
            stage = escalation["target_stage"]
            action_text = escalation["action_description"]
            actions = escalation["recommended_actions"]

            # Log to collections table
            channel = {
                0: "auto_notification",
                1: "sms_email",
                2: "phone",
                3: "demand_letter",
                4: "legal",
                5: "charge_off",
            }.get(stage, "unknown")

            _log_collection_action(
                conn, loan_id, borrower_id, stage, days_past,
                action_text, channel,
            )

            # Stage-specific side effects
            if stage == 2:
                # Apply a 5% late fee — fetch the monthly_payment first
                loan_row = _to_dict(conn.execute(
                    "SELECT monthly_payment FROM loans WHERE id = ?",
                    (loan_id,),
                ).fetchone())
                if loan_row:
                    fee = round(loan_row["monthly_payment"] * 0.05, 2)
                    apply_late_fee(loan_id, fee, connection=conn)
                    logger.info("Late fee $%.2f applied to loan %s", fee, loan_id)

            if stage == 5:
                auto_charge_off(loan_id, connection=conn)

            # Track stats
            key = f"stage_{stage}"
            if key in stats:
                stats[key] += 1

            results.append({
                "loan_id": loan_id,
                "borrower_id": borrower_id,
                "days_past_due": days_past,
                "stage": stage,
                "action": action_text,
                "actions_taken": actions,
            })

        conn.commit()
    except Exception:
        conn.rollback()
        logger.exception("Collections cycle failed — rolling back")
        raise
    finally:
        conn.close()

    summary = {
        "total_overdue": len(overdue),
        "processed": len(results),
        "stages": stats,
        "results": results,
    }

    logger.info(
        "Collections cycle complete: %d overdue, %d processed. Stages: %s",
        len(overdue),
        len(results),
        stats,
    )
    return summary


# ---------------------------------------------------------------------------
# 4. apply_late_fee
# ---------------------------------------------------------------------------

def apply_late_fee(loan_id, fee_amount, connection=None):
    """
    Add a late fee to the loan's remaining_balance.

    Parameters
    ----------
    loan_id : int
    fee_amount : float  (in dollars)
    connection : sqlite3.Connection or None

    Notes
    -----
    If no connection is provided, opens and closes one.
    """
    if connection:
        conn = connection
        close_after = False
    else:
        conn = _get_connection()
        close_after = True

    try:
        conn.execute(
            "UPDATE loans SET remaining_balance = remaining_balance + ? WHERE id = ?",
            (fee_amount, loan_id),
        )
        if close_after:
            conn.commit()
        logger.info("Late fee $%.2f applied to loan %s", fee_amount, loan_id)
    except Exception:
        logger.exception("Failed to apply late fee to loan %s", loan_id)
        raise
    finally:
        if close_after:
            conn.close()


# ---------------------------------------------------------------------------
# 5. auto_charge_off
# ---------------------------------------------------------------------------

def auto_charge_off(loan_id, connection=None):
    """
    Mark a loan as defaulted with a charge-off status.

    Updates:
        status -> 'charged_off'
        remaining_balance -> 0.0  (written off)

    Parameters
    ----------
    loan_id : int
    connection : sqlite3.Connection or None
    """
    if connection:
        conn = connection
        close_after = False
    else:
        conn = _get_connection()
        close_after = True

    try:
        conn.execute(
            "UPDATE loans SET status = 'charged_off', remaining_balance = 0.0 "
            "WHERE id = ?",
            (loan_id,),
        )
        if close_after:
            conn.commit()
        logger.info("Loan %s charged off (status=charged_off)", loan_id)
    except Exception:
        logger.exception("Failed to charge off loan %s", loan_id)
        raise
    finally:
        if close_after:
            conn.close()


# ---------------------------------------------------------------------------
# 6. get_collection_stats
# ---------------------------------------------------------------------------

def get_collection_stats():
    """
    Aggregate collection data and return summary statistics.

    Returns
    -------
    dict with:
        stage_counts  — dict mapping stage number -> count
        total_at_risk — sum of loans in stages 0-4 (still collectible)
        total_charged_off — count of loans in stage 5 (charge-off)
    """
    conn = _get_connection()
    try:
        # Current stage for each loan: use the latest collection entry per loan
        rows = conn.execute(
            """
            SELECT c.collection_stage, COUNT(DISTINCT c.loan_id) AS cnt
            FROM collections c
            INNER JOIN (
                SELECT loan_id, MAX(created_at) AS latest
                FROM collections
                GROUP BY loan_id
            ) latest
                ON c.loan_id = latest.loan_id
                AND c.created_at = latest.latest
            GROUP BY c.collection_stage
            ORDER BY c.collection_stage
            """
        ).fetchall()

        stage_counts = {i: 0 for i in range(6)}
        for row in rows:
            r = _to_dict(row)
            stage_counts[r["collection_stage"]] = r["cnt"]

        # Also count active loans overdue that have no collection entry yet
        overdue = detect_overdue_loans()
        # Loans already counted in collections
        counted_loan_ids = set()
        for row in conn.execute(
            "SELECT DISTINCT loan_id FROM collections"
        ).fetchall():
            r = _to_dict(row)
            counted_loan_ids.add(r["loan_id"])

        for item in overdue:
            if item["loan_id"] not in counted_loan_ids:
                stg = escalate_collection(
                    item["loan_id"], item["borrower_id"], item["days_past_due"]
                )["target_stage"]
                stage_counts[stg] = stage_counts.get(stg, 0) + 1

        total_at_risk = sum(
            count for stage, count in stage_counts.items() if stage < 5
        )
        total_charged_off = stage_counts.get(5, 0)

        return {
            "stage_counts": stage_counts,
            "total_at_risk": total_at_risk,
            "total_charged_off": total_charged_off,
        }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# CLI convenience (python -m automation.collections)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    print("=== Collections Cycle ===")
    summary = run_collections_cycle()
    print(f"Overdue loans: {summary['total_overdue']}")
    print(f"Processed:     {summary['processed']}")
    print(f"Stage counts:  {summary['stages']}")
    print()

    print("=== Collection Stats ===")
    stats = get_collection_stats()
    print(f"At risk:       {stats['total_at_risk']}")
    print(f"Charged off:   {stats['total_charged_off']}")
    for stage, cnt in sorted(stats["stage_counts"].items()):
        if cnt:
            print(f"  Stage {stage}: {cnt}")
