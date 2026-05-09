"""
PalmFi Autonomous Operations Engine.
Runs all automated processes on a schedule: collections, payments, funding, reserves,
KYC, fraud checks, auto-decisioning, disbursement, dunning, escalation, rate improvement,
and daily reporting.
Designed to be called by a cron job or the built-in scheduler loop.
"""
from __future__ import annotations
import sys, os, json, logging, time, sqlite3, traceback
from datetime import datetime, timezone, timedelta, date
from pathlib import Path

# File + console logging — structured to match SunCredit's autopilot logger
LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] autopilot: %(message)s",
    handlers=[logging.FileHandler(str(LOG_DIR / "autopilot.log")), logging.StreamHandler()],
)
logger = logging.getLogger("autopilot")

# Add all project paths
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in [BASE, os.path.join(BASE, 'platform'), os.path.join(BASE, 'automation'),
          os.path.join(BASE, 'compliance'), os.path.join(BASE, 'underwriting')]:
    if p not in sys.path:
        sys.path.insert(0, p)


# ----- ML Scorer (lazy-loaded singleton) -----
from underwriting.scorer import LoanScorer
_scorer = None
def _get_scorer():
    global _scorer
    if _scorer is None:
        _scorer = LoanScorer()
        try:
            _scorer.load()
        except Exception as e:
            logger.warning("LoanScorer model not loaded (will use rule-based fallback): %s", e)
    return _scorer

def uw_score(features):
    """Score application features via ML model."""
    s = _get_scorer()
    if s.model_loaded:
        return s.score_application(features)
    # Rule-based fallback when model unavailable
    cs = features.get("credit_score", 600)
    dti = features.get("dti_ratio", 0.30)
    risk = max(0, min(100, int(round((1000 - cs) / 10 + dti * 50))))
    return {"risk_score": risk, "tier": "C" if risk > 50 else "B" if risk > 30 else "A"}


# ----- Notifications stub (for new steps — integrates with existing PalmFi patterns) -----
def _send_notification(to, template, context):
    """Send a notification email/log entry.
    Falls back to logger if no real notification module available.
    """
    logger.info("NOTIFICATION to=%s template=%s context=%s", to, template, context)
    try:
        # Try PalmFi's platform audit_log for notification tracking
        from platform.models import audit_log
        audit_log("notification", actor="autopilot", details={"to": to, "template": template, "context": context})
    except Exception:
        pass


# ----- Stripe payments module -----
try:
    from automation import stripe_payments as sp
except Exception:
    sp = None


# ----- Policy thresholds (the AI's "judgement") -----
AUTO_APPROVE_MIN_SCORE = 680   # auto-approve above this
AUTO_DECLINE_MAX_SCORE = 540   # auto-decline below this
# 540-680 → flag for human review
MAX_AUTO_LOAN_AMOUNT = 15000   # anything bigger needs human
DUNNING_DAYS = [3, 7, 15, 30]
ESCALATION_DAY = 60
RATE_IMPROVE_MIN_PAYMENTS = 6  # need 6 on-time payments for rate cut


def get_db():
    from models import get_db as _g
    return _g()


# ═══════════════════════════════════════════════════════════════
# Structured Audit Logging (autopilot_log table)
# ═══════════════════════════════════════════════════════════════

def ensure_log_table(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS autopilot_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts TEXT NOT NULL,
        action TEXT NOT NULL,
        target_type TEXT,
        target_id INTEGER,
        details TEXT,
        success INTEGER DEFAULT 1
    )""")
    conn.commit()


def record(conn, action, target_type=None, target_id=None, details=None, success=True):
    conn.execute(
        "INSERT INTO autopilot_log (ts, action, target_type, target_id, details, success) VALUES (?,?,?,?,?,?)",
        (datetime.now(timezone.utc).isoformat(), action, target_type, target_id,
         json.dumps(details or {}, default=str), 1 if success else 0),
    )
    conn.commit()
    logger.info("%s %s#%s success=%s %s", action, target_type or '', target_id or '', success, details or '')


# ═══════════════════════════════════════════════════════════════
# 1. Auto-Decision pending applications (ML scoring)
# ═══════════════════════════════════════════════════════════════

def step_auto_decision(conn) -> dict:
    pending = conn.execute(
        "SELECT a.id, a.borrower_id, a.loan_amount, a.term_months, a.status, "
        "b.first_name, b.last_name, b.email, b.credit_score, b.annual_income, "
        "b.employment_status "
        "FROM applications a JOIN borrowers b ON a.borrower_id=b.id "
        "WHERE a.status = 'pending' AND a.loan_amount IS NOT NULL "
        "ORDER BY a.created_at ASC LIMIT 50"
    ).fetchall()

    stats = {"approved": 0, "declined": 0, "manual_review": 0, "errors": 0}
    for app in pending:
        try:
            features = {
                "credit_score": app["credit_score"] or 600,
                "annual_income": app["annual_income"] or 50000,
                "loan_amount": app["loan_amount"],
                "term_months": app["term_months"] or 36,
                "employment_status": app["employment_status"] or "full_time",
                "dti_ratio": 0.30,   # default — PalmFi doesn't store DTI on apps
                "prior_defaults": 0,  # default — not in PalmFi schema
                # Additional fields required by PalmFi's LoanScorer.score_application()
                "age": 35,
                "employment_length": 3,
                "utilization": 0.3,
                "num_derogatory": 0,
                "num_credit_lines": 5,
                "home_ownership": "rent",
                "loan_purpose": "debt_consolidation",
            }
            result = uw_score(features)
            risk = result.get("risk_score", 50)
            tier = result.get("risk_tier", result.get("tier", "C"))

            decision, reason = "manual_review", "in human-review band"
            if app["loan_amount"] > MAX_AUTO_LOAN_AMOUNT:
                decision, reason = "manual_review", f"amount exceeds ${MAX_AUTO_LOAN_AMOUNT} auto-cap"
            elif risk >= AUTO_APPROVE_MIN_SCORE:
                decision, reason = "approved", "auto-approved by AI"
            elif risk <= AUTO_DECLINE_MAX_SCORE:
                decision, reason = "declined", "auto-declined by AI"

            conn.execute(
                "UPDATE applications SET status=?, risk_score=?, risk_tier=?, "
                "decision_explanation=?, decided_at=? WHERE id=?",
                (decision, risk, tier, json.dumps({"reason": reason}),
                 datetime.now(timezone.utc).isoformat(), app["id"]),
            )

            # Notify borrower if final decision
            if decision in ("approved", "declined"):
                _send_notification(
                    to=app["email"],
                    template=f"{decision}_email",
                    context={"name": app["first_name"], "amount": app["loan_amount"]},
                )

            stats[decision if decision != "manual_review" else "manual_review"] += 1
            record(conn, "auto_decision", "application", app["id"],
                   {"decision": decision, "risk_score": risk, "reason": reason})
        except Exception as e:
            stats["errors"] += 1
            record(conn, "auto_decision_error", "application", app["id"],
                   {"error": str(e), "trace": traceback.format_exc()[:500]}, success=False)
    conn.commit()
    return stats


# ═══════════════════════════════════════════════════════════════
# 2. Auto-Disburse approved loans (Stripe ACH)
# ═══════════════════════════════════════════════════════════════

def step_auto_disburse(conn) -> dict:
    apps = conn.execute(
        "SELECT a.id, a.borrower_id, a.loan_amount, a.term_months, a.interest_rate, "
        "b.first_name, b.email, b.stripe_customer_id "
        "FROM applications a "
        "JOIN borrowers b ON a.borrower_id=b.id "
        "LEFT JOIN loans l ON l.application_id=a.id "
        "WHERE a.status='approved' AND l.id IS NULL "
        "LIMIT 50"
    ).fetchall()
    stats = {"disbursed": 0, "errors": 0}
    for app in apps:
        try:
            monthly_pmt = round(app["loan_amount"] * (app["interest_rate"] or 0.18) / 12 * 
                               (1 + 1 / ((1 + (app["interest_rate"] or 0.18) / 12) ** (app["term_months"] or 36) - 1)), 2)
            if monthly_pmt <= 0:
                monthly_pmt = round(app["loan_amount"] / (app["term_months"] or 36), 2)
            # Create loan record
            conn.execute(
                "INSERT INTO loans (application_id, borrower_id, principal, interest_rate, "
                "term_months, monthly_payment, origination_fee, remaining_balance, status, "
                "disbursed_at, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (app["id"], app["borrower_id"], app["loan_amount"], app["interest_rate"] or 0.18,
                 app["term_months"] or 36, monthly_pmt, 0,
                 app["loan_amount"], "active",
                 datetime.now(timezone.utc).isoformat(),
                 datetime.now(timezone.utc).isoformat()),
            )
            loan_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

            # Trigger Stripe ACH transfer
            transfer_id = None
            if sp and os.environ.get("STRIPE_SECRET_KEY"):
                try:
                    transfer_id = sp.disburse(
                        borrower_id=app["borrower_id"], amount=app["loan_amount"], loan_id=loan_id,
                    )
                except Exception:
                    logger.warning("Stripe disburse failed for loan %d — continuing", loan_id)

            conn.execute(
                "UPDATE applications SET decided_at=? WHERE id=?",
                (datetime.now(timezone.utc).isoformat(), app["id"]),
            )
            _send_notification(to=app["email"], template="funded_email",
                               context={"name": app["first_name"], "amount": app["loan_amount"]})
            stats["disbursed"] += 1
            record(conn, "auto_disburse", "loan", loan_id,
                   {"amount": app["loan_amount"], "transfer_id": transfer_id})
        except Exception as e:
            stats["errors"] += 1
            record(conn, "auto_disburse_error", "application", app["id"],
                   {"error": str(e)}, success=False)
    conn.commit()
    return stats


# ═══════════════════════════════════════════════════════════════
# 3. Auto-Collect scheduled payments (autopay charge)
# ═══════════════════════════════════════════════════════════════

def step_auto_collect(conn) -> dict:
    today = datetime.now(timezone.utc).date().isoformat()
    due = conn.execute(
        "SELECT p.id, p.loan_id, p.borrower_id, p.amount_cents, p.due_date, "
        "b.email, b.first_name FROM payments p "
        "JOIN loans l ON p.loan_id=l.id JOIN borrowers b ON l.borrower_id=b.id "
        "WHERE p.status='scheduled' AND p.due_date <= ? "
        "LIMIT 100",
        (today,),
    ).fetchall()
    stats = {"charged": 0, "failed": 0}
    for p in due:
        try:
            charged = True
            if sp and os.environ.get("STRIPE_SECRET_KEY"):
                charged = sp.charge(borrower_id=p["borrower_id"], amount_cents=p["amount_cents"])
            new_status = "paid" if charged else "failed"
            conn.execute(
                "UPDATE payments SET status=?, paid_at=? WHERE id=?",
                (new_status, datetime.now(timezone.utc).isoformat() if charged else None, p["id"]),
            )
            if charged:
                stats["charged"] += 1
                _send_notification(to=p["email"], template="payment_received",
                                   context={"name": p["first_name"], "amount": p["amount_cents"] / 100})
            else:
                stats["failed"] += 1
            record(conn, "auto_collect", "payment", p["id"],
                   {"amount_cents": p["amount_cents"], "result": new_status})
        except Exception as e:
            stats["failed"] += 1
            record(conn, "auto_collect_error", "payment", p["id"], {"error": str(e)}, success=False)
    conn.commit()
    return stats


# ═══════════════════════════════════════════════════════════════
# 4. Dunning ladder (targeted reminders at 3/7/15/30 days)
# ═══════════════════════════════════════════════════════════════

def step_dunning(conn) -> dict:
    today = datetime.now(timezone.utc).date()
    stats = {"reminders_sent": 0}
    for days_late in DUNNING_DAYS:
        target = (today - timedelta(days=days_late)).isoformat()
        late = conn.execute(
            "SELECT p.id, p.loan_id, p.amount_cents, p.due_date, "
            "b.email, b.first_name FROM payments p "
            "JOIN loans l ON p.loan_id=l.id JOIN borrowers b ON l.borrower_id=b.id "
            "WHERE p.status IN ('scheduled','failed') AND p.due_date = ?",
            (target,),
        ).fetchall()
        for p in late:
            severity = "soft" if days_late <= 7 else "firm" if days_late <= 15 else "final"
            _send_notification(
                to=p["email"], template="payment_reminder",
                context={"name": p["first_name"], "amount": p["amount_cents"] / 100,
                         "days_late": days_late, "severity": severity},
            )
            stats["reminders_sent"] += 1
            record(conn, "dunning", "payment", p["id"], {"days_late": days_late, "severity": severity})
    return stats


# ═══════════════════════════════════════════════════════════════
# 5. Escalate severe delinquencies (60+ days)
# ═══════════════════════════════════════════════════════════════

def step_escalate(conn) -> dict:
    cutoff = (datetime.now(timezone.utc).date() - timedelta(days=ESCALATION_DAY)).isoformat()
    bad = conn.execute(
        "SELECT DISTINCT l.id, l.borrower_id, l.principal FROM loans l "
        "JOIN payments p ON p.loan_id=l.id "
        "WHERE p.status IN ('scheduled','failed') AND p.due_date <= ? "
        "AND l.status='active'",
        (cutoff,),
    ).fetchall()
    for ln in bad:
        conn.execute("UPDATE loans SET status='delinquent_escalated' WHERE id=?", (ln["id"],))
        record(conn, "escalate", "loan", ln["id"], {"reason": f"{ESCALATION_DAY}+ days delinquent"})
    conn.commit()
    return {"escalated": len(bad)}


# ═══════════════════════════════════════════════════════════════
# 6. Rate improvement (reward 6+ on-time payments)
# ═══════════════════════════════════════════════════════════════

def step_rate_improve(conn) -> dict:
    candidates = conn.execute(
        "SELECT l.id, l.borrower_id, l.interest_rate, l.principal, b.email, b.first_name "
        "FROM loans l JOIN borrowers b ON l.borrower_id=b.id "
        "WHERE l.status='active' AND l.rate_improved_at IS NULL "
        "AND (SELECT COUNT(*) FROM payments p WHERE p.loan_id=l.id AND p.status='paid') >= ?",
        (RATE_IMPROVE_MIN_PAYMENTS,),
    ).fetchall()
    stats = {"improved": 0}
    for ln in candidates:
        new_rate = max(0.06, (ln["interest_rate"] or 0.18) - 0.02)  # cut 2 percentage points
        # Check if PalmFi loans table has rate_improved_at column; if not, add it
        try:
            conn.execute(
                "UPDATE loans SET interest_rate=?, rate_improved_at=? WHERE id=?",
                (new_rate, datetime.now(timezone.utc).isoformat(), ln["id"]),
            )
        except sqlite3.OperationalError:
            conn.execute("ALTER TABLE loans ADD COLUMN rate_improved_at TEXT")
            conn.execute(
                "UPDATE loans SET interest_rate=?, rate_improved_at=? WHERE id=?",
                (new_rate, datetime.now(timezone.utc).isoformat(), ln["id"]),
            )
        _send_notification(to=ln["email"], template="rate_improvement",
                           context={"name": ln["first_name"], "new_rate": new_rate})
        stats["improved"] += 1
        record(conn, "rate_improve", "loan", ln["id"],
               {"old_rate": ln["interest_rate"], "new_rate": new_rate})
    conn.commit()
    return stats


# ═══════════════════════════════════════════════════════════════
# 7. Daily ops report (aggregated from autopilot_log)
# ═══════════════════════════════════════════════════════════════

def step_daily_report(conn) -> dict:
    last_24h = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    rows = conn.execute(
        "SELECT action, COUNT(*) AS n, COALESCE(SUM(success), 0) AS ok FROM autopilot_log "
        "WHERE ts >= ? GROUP BY action", (last_24h,)
    ).fetchall()
    summary = {r["action"]: {"total": r["n"], "success": r["ok"]} for r in rows}
    portfolio = conn.execute(
        "SELECT COUNT(*) AS n, COALESCE(SUM(principal), 0) AS p FROM loans WHERE status='active'"
    ).fetchone()
    summary["_portfolio"] = {"active_loans": portfolio["n"], "principal_outstanding": portfolio["p"]}
    record(conn, "daily_report", "system", 0, summary)
    return summary


# ═══════════════════════════════════════════════════════════════
# Orchestrated Run — One Call Does Everything
# ═══════════════════════════════════════════════════════════════

def run_all_operations():
    """
    Master function: runs every autonomous operation in order.
    This is what the cron job calls.
    
    Order of operations:
      1. Collections Cycle           (PalmFi existing)
      2. Payment Batch Processing    (PalmFi existing)
      3. Auto-Funding Check          (PalmFi existing)
      4. Loan Loss Reserves          (PalmFi existing)
      5. Auto-KYC Verification       (PalmFi existing)
      6. OFAC/Fraud Check            (PalmFi existing)
      7. Auto-Decision               (SunCredit new)
      8. Auto-Disburse               (SunCredit new)
      9. Auto-Collect                (SunCredit new)
     10. Dunning                     (SunCredit new)
     11. Escalate                    (SunCredit new)
     12. Rate Improvement            (SunCredit new)
     13. Daily Report                (SunCredit new)
    """
    results = {}

    logger.info("=" * 60)
    logger.info("PalmFi Autopilot Cycle Starting")
    logger.info("Time: %s", datetime.now(timezone.utc).isoformat())
    logger.info("=" * 60)

    # ----- Existing PalmFi Steps -----

    # 1. Collections Cycle
    try:
        from loan_collections import run_collections_cycle
        coll = run_collections_cycle()
        results["collections"] = {
            "status": "ok",
            "processed": coll.get("processed", 0),
            "overdue": coll.get("total_overdue", 0),
        }
        logger.info("Collections: %d processed, %d overdue",
                   results["collections"]["processed"], results["collections"]["overdue"])
    except Exception as e:
        results["collections"] = {"status": "error", "error": str(e)}
        logger.error("Collections cycle failed: %s", e)

    # 2. Payment Batch Processing
    try:
        from stripe_payments import process_payment_batch
        batch = process_payment_batch()
        results["payments"] = {
            "status": "ok",
            "processed": batch.get("processed", 0),
            "total": batch.get("total_amount_dollars", 0),
        }
        logger.info("Payment batch: %d processed ($%.2f)",
                   results["payments"]["processed"], results["payments"]["total"])
    except Exception as e:
        results["payments"] = {"status": "error", "error": str(e)}
        logger.error("Payment batch failed: %s", e)

    # 3. Auto-Funding Check
    try:
        from compliance.funding_tax import auto_funding_check, init_tables
        init_tables()
        funding = auto_funding_check()
        results["funding"] = {
            "status": "ok",
            "checked": funding.get("checked", 0),
            "funded": funding.get("funded", 0),
        }
        logger.info("Funding: %d checked, %d auto-funded",
                   results["funding"]["checked"], results["funding"]["funded"])
    except Exception as e:
        results["funding"] = {"status": "error", "error": str(e)}
        logger.error("Auto-funding failed: %s", e)

    # 4. Loan Loss Reserves
    try:
        from compliance.funding_tax import establish_reserves, get_reserve_summary
        reserves = establish_reserves()
        reserve_summary = get_reserve_summary()
        results["reserves"] = {
            "status": "ok",
            "created": reserves.get("reserves_created", 0),
            "allocated_dollars": reserve_summary.get("allocated_dollars", 0),
        }
        logger.info("Reserves: %d created ($%.2f allocated)",
                   results["reserves"]["created"], results["reserves"]["allocated_dollars"])
    except Exception as e:
        results["reserves"] = {"status": "error", "error": str(e)}
        logger.error("Reserve establishment failed: %s", e)

    # 5. Auto-KYC Verification Batch
    try:
        from kyc import list_all_pending_kyc, auto_verify_kyc
        pending = list_all_pending_kyc()
        auto_verified = 0
        for borrower in pending:
            try:
                result = auto_verify_kyc(borrower.get('id') or borrower.get('borrower_id'))
                if result.get("approved"):
                    auto_verified += 1
            except Exception:
                pass
        results["kyc"] = {
            "status": "ok",
            "pending": len(pending),
            "auto_verified": auto_verified,
        }
        logger.info("KYC: %d pending, %d auto-verified", len(pending), auto_verified)
    except Exception as e:
        results["kyc"] = {"status": "error", "error": str(e)}
        logger.error("KYC batch failed: %s", e)

    # 6. OFAC/Fraud Check for new applications
    try:
        db = get_db()
        new_apps = db.execute("""
            SELECT a.id as app_id, a.borrower_id, a.loan_amount, a.status,
                   b.first_name, b.last_name, b.email
            FROM applications a JOIN borrowers b ON a.borrower_id = b.id
            WHERE a.status IN ('submitted', 'pending') AND a.created_at > datetime('now', '-24 hours')
        """).fetchall()
        db.close()
        fraud_results = []
        for app in new_apps:
            try:
                from identity import run_full_verification
                app_dict = dict(app)
                result = run_full_verification(app_dict['borrower_id'], {
                    "loan_amount": app_dict.get("loan_amount", 0),
                    "email": app_dict.get("email", ""),
                })
                fraud_results.append({
                    "app_id": app_dict["app_id"],
                    "decision": result.get("decision"),
                    "fraud_score": result.get("fraud", {}).get("fraud_score", 0),
                })
                # Auto-decline critical fraud
                if result.get("decision") == "DECLINED" and result.get("ofac", {}).get("flagged"):
                    db2 = get_db()
                    db2.execute("UPDATE applications SET status='declined', decided_at=datetime('now') WHERE id=?",
                               (app_dict["app_id"],))
                    db2.commit()
                    db2.close()
                    logger.info("Auto-declined app %d due to OFAC match", app_dict["app_id"])
            except Exception as e2:
                logger.warning("Fraud check failed for app %s: %s", app.get("app_id"), e2)
        results["fraud"] = {
            "status": "ok",
            "checked": len(fraud_results),
            "flagged": sum(1 for r in fraud_results if r.get("decision") == "DECLINED"),
        }
        logger.info("Fraud: %d checked, %d flagged", len(fraud_results), results["fraud"]["flagged"])
    except Exception as e:
        results["fraud"] = {"status": "error", "error": str(e)}
        logger.error("Fraud batch failed: %s", e)

    # ----- New SunCredit Steps (with audit logging) -----
    db_conn = get_db()
    try:
        ensure_log_table(db_conn)

        # 7. Auto-Decision
        try:
            results["auto_decision"] = step_auto_decision(db_conn)
            logger.info("Auto-decision: %s", results["auto_decision"])
        except Exception as e:
            results["auto_decision"] = {"error": str(e)}
            logger.error("Auto-decision step failed: %s", e)

        # 8. Auto-Disburse
        try:
            results["auto_disburse"] = step_auto_disburse(db_conn)
            logger.info("Auto-disburse: %s", results["auto_disburse"])
        except Exception as e:
            results["auto_disburse"] = {"error": str(e)}
            logger.error("Auto-disburse step failed: %s", e)

        # 9. Auto-Collect (scheduled autopay charges)
        try:
            results["auto_collect"] = step_auto_collect(db_conn)
            logger.info("Auto-collect: %s", results["auto_collect"])
        except Exception as e:
            results["auto_collect"] = {"error": str(e)}
            logger.error("Auto-collect step failed: %s", e)

        # 10. Dunning
        try:
            results["dunning"] = step_dunning(db_conn)
            logger.info("Dunning: %s", results["dunning"])
        except Exception as e:
            results["dunning"] = {"error": str(e)}
            logger.error("Dunning step failed: %s", e)

        # 11. Escalate
        try:
            results["escalate"] = step_escalate(db_conn)
            logger.info("Escalate: %s", results["escalate"])
        except Exception as e:
            results["escalate"] = {"error": str(e)}
            logger.error("Escalate step failed: %s", e)

        # 12. Rate Improvement
        try:
            results["rate_improve"] = step_rate_improve(db_conn)
            logger.info("Rate improvement: %s", results["rate_improve"])
        except Exception as e:
            results["rate_improve"] = {"error": str(e)}
            logger.error("Rate improvement step failed: %s", e)

        # 13. Daily Report
        try:
            results["daily_report"] = step_daily_report(db_conn)
            logger.info("Daily report: %s", results["daily_report"])
        except Exception as e:
            results["daily_report"] = {"error": str(e)}
            logger.error("Daily report step failed: %s", e)

    finally:
        db_conn.close()

    # Summary
    results["cycle_time"] = datetime.now(timezone.utc).isoformat()
    results["status"] = "completed"

    # Save to status file for dashboard
    try:
        status_path = os.path.join(BASE, 'autopilot_status_last.json')
        with open(status_path, 'w') as f:
            json.dump(results, f, default=str)
    except Exception as e:
        logger.warning("Could not save status file: %s", e)

    logger.info("=" * 60)
    logger.info("Autopilot Cycle Complete")
    for key, val in results.items():
        if key not in ("cycle_time", "status"):
            s = val.get("status", "?")
            logger.info("  %s: %s", key, s)
    logger.info("=" * 60)

    return results


# ═══════════════════════════════════════════════════════════════
# Built-in Scheduler (Background Thread)
# ═══════════════════════════════════════════════════════════════

class AutopilotScheduler:
    """
    Runs autonomous operations on an interval.
    
    Usage:
        scheduler = AutopilotScheduler(interval_minutes=60)
        scheduler.start()  # starts background thread
    
    Or use the standalone cron script approach:
        * * * * * cd /path/to/project && python3 -m automation.autopilot --cron
    """
    
    def __init__(self, interval_minutes=60, run_on_start=True):
        self.interval = interval_minutes * 60
        self.running = False
        self.thread = None
        self.run_on_start = run_on_start
        self.last_run = None
        self.cycle_count = 0
    
    def _loop(self):
        if self.run_on_start:
            self._execute_cycle()
        while self.running:
            time.sleep(self.interval)
            if self.running:
                self._execute_cycle()
    
    def _execute_cycle(self):
        self.cycle_count += 1
        logger.info("Schedule cycle #%d starting", self.cycle_count)
        try:
            result = run_all_operations()
            self.last_run = result
            logger.info("Schedule cycle #%d complete", self.cycle_count)
        except Exception as e:
            logger.error("Schedule cycle #%d failed: %s", self.cycle_count, e)
    
    def start(self):
        if self.running:
            return
        self.running = True
        import threading
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()
        logger.info("Autopilot scheduler started (interval=%ds)", self.interval)
    
    def stop(self):
        self.running = False
        logger.info("Autopilot scheduler stopped")
    
    def status(self):
        return {
            "running": self.running,
            "interval_seconds": self.interval,
            "cycle_count": self.cycle_count,
            "last_run": self.last_run["cycle_time"] if self.last_run else None,
        }


# ═══════════════════════════════════════════════════════════════
# Standalone Cron Entry Point
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="PalmFi Autonomous Operations")
    parser.add_argument("--cron", action="store_true", help="Run one cycle (for system cron)")
    parser.add_argument("--daemon", action="store_true", help="Run persistent scheduler")
    parser.add_argument("--interval", type=int, default=60, help="Interval in minutes (default: 60)")
    parser.add_argument("--status", action="store_true", help="Show last run status")
    args = parser.parse_args()
    
    if args.cron:
        result = run_all_operations()
        print(json.dumps(result, indent=2, default=str))
    elif args.daemon:
        sched = AutopilotScheduler(interval_minutes=args.interval, run_on_start=True)
        sched.start()
        try:
            while True:
                time.sleep(10)
        except KeyboardInterrupt:
            sched.stop()
            print("Scheduler stopped.")
    elif args.status:
        import glob
        status_files = glob.glob(os.path.join(BASE, "autopilot_status_*.json"))
        if status_files:
            latest = max(status_files, key=os.path.getmtime)
            with open(latest) as f:
                print(f.read())
        else:
            print("No autopilot status files found. Run --cron first.")
    else:
        # Single run
        result = run_all_operations()
        print(json.dumps(result, indent=2, default=str))
