"""E-SIGN Act (15 U.S.C. ch. 96) compliance helpers.

Records borrower consent to do business electronically, the document hash
they consented to, source IP, and timestamp. Provides audit trail logging
and acceptance record-keeping.

PalmFi edition — keeps the CONSENT_TEMPLATE text and audit trail while
using SunCredit's simpler DB pattern (no _resolve_db_path, no _get_connection).
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# E-SIGN consent generation
# ---------------------------------------------------------------------------

CONSENT_TEMPLATE = """CONSUMER CONSENT TO ELECTRONIC DISCLOSURES

Pursuant to the Electronic Signatures in Global and National Commerce Act
(E-SIGN Act, 15 U.S.C. § 7001 et seq.), you are providing your consent to
receive all disclosures, notices, documents, and communications related to
your loan electronically rather than in paper form.

HARDWARE AND SOFTWARE REQUIREMENTS
To access and retain electronic disclosures, you will need:
• A computer or mobile device with internet access
• An HTML-capable email application or web browser
• A PDF reader (such as Adobe Acrobat Reader or browser built-in PDF viewer)
• A web browser supporting 128-bit encryption (all modern browsers satisfy this)
• Sufficient storage capacity to save and retain disclosures

RIGHT TO WITHDRAW CONSENT
You may withdraw your consent to receive electronic disclosures at any time.
However, withdrawing consent may affect your ability to complete or maintain
your loan. To withdraw consent, you must notify us in writing or by email.

WITHDRAWAL PROCEDURE
To withdraw your consent, contact us:
• Email: compliance@ailending.com
• Mail: AI Lending Company, Attn: Compliance, 100 Financial Blvd, Suite 200

Upon withdrawal, we will provide disclosures in paper format for any future
communications. Withdrawal of consent will not affect the legal validity or
enforceability of electronic disclosures provided before the withdrawal date.

CONSENT
By accepting this disclosure, you acknowledge that you have read and
understand the above terms, and you voluntarily consent to receive all
disclosures and communications electronically as described above."""


def generate_esign_consent(
    borrower_name: str,
    borrower_email: str,
    ip_address: str = "",
    user_agent: str = "",
) -> dict:
    """Generate an E-SIGN consent record.

    Parameters
    ----------
    borrower_name : str
        Full name of the borrower.
    borrower_email : str
        Email address of the borrower.
    ip_address : str
        IP address from which consent was provided.
    user_agent : str
        User-agent string of the browser/device.

    Returns
    -------
    dict
        Consent record with consent_id, consumer_name, email, ip, user_agent,
        timestamp, and consent_text.
    """
    consent_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    return {
        "consent_id": consent_id,
        "consumer_name": borrower_name,
        "email": borrower_email,
        "ip_address": ip_address,
        "user_agent": user_agent,
        "timestamp": now,
        "consent_text": CONSENT_TEMPLATE,
    }


def _ensure_notifications_table(conn) -> None:
    """Create the notifications table if it does not exist."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            borrower_id INTEGER NOT NULL,
            action TEXT NOT NULL,
            data TEXT DEFAULT '{}',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)


def record_esign_acceptance(
    consent_id: str,
    borrower_id: int,
    db_connection=None,
) -> dict:
    """Record E-SIGN acceptance in the database.

    Creates a notifications table entry with action='esign_accept' and stores
    the full consent record as JSON.

    Parameters
    ----------
    consent_id : str
        The consent ID from generate_esign_consent().
    borrower_id : int
        The borrower's database ID.
    db_connection : sqlite3.Connection, optional
        An existing database connection.

    Returns
    -------
    dict
        Contains acceptance_id, timestamp.
    """
    import sqlite3

    close_conn = False
    if db_connection is None:
        db_connection = sqlite3.connect(":memory:")
        close_conn = True

    try:
        _ensure_notifications_table(db_connection)

        now = datetime.now(timezone.utc).isoformat()
        data = json.dumps({"consent_id": consent_id, "accepted_at": now})

        cursor = db_connection.execute(
            "INSERT INTO notifications (borrower_id, action, data, created_at) VALUES (?, ?, ?, ?)",
            (borrower_id, "esign_accept", data, now),
        )
        db_connection.commit()
        acceptance_id = cursor.lastrowid

        return {
            "acceptance_id": acceptance_id,
            "timestamp": now,
        }
    finally:
        if close_conn:
            db_connection.close()


def get_esign_status(borrower_id: int, db_connection=None) -> dict:
    """Get the E-SIGN consent status for a borrower.

    Parameters
    ----------
    borrower_id : int
        The borrower's database ID.
    db_connection : sqlite3.Connection, optional
        An existing database connection.

    Returns
    -------
    dict
        Contains has_consented, consent_date, consent_record.
    """
    import sqlite3

    close_conn = False
    if db_connection is None:
        db_connection = sqlite3.connect(":memory:")
        close_conn = True

    try:
        _ensure_notifications_table(db_connection)

        row = db_connection.execute(
            "SELECT id, data, created_at FROM notifications "
            "WHERE borrower_id = ? AND action = 'esign_accept' "
            "ORDER BY created_at DESC LIMIT 1",
            (borrower_id,),
        ).fetchone()

        if row is None:
            return {
                "has_consented": False,
                "consent_date": None,
                "consent_record": None,
            }

        try:
            consent_record = json.loads(row["data"])
        except (json.JSONDecodeError, TypeError):
            consent_record = {"raw_data": row["data"]}

        return {
            "has_consented": True,
            "consent_date": row["created_at"],
            "consent_record": consent_record,
        }
    finally:
        if close_conn:
            db_connection.close()


def create_audit_trail(
    borrower_id: int,
    action_type: str,
    details_dict: dict,
    ip_address: str,
    db_connection=None,
) -> dict:
    """Record an audit trail entry to the audit_logs table.

    Parameters
    ----------
    borrower_id : int
        The borrower's database ID.
    action_type : str
        The type of action being recorded.
    details_dict : dict
        Detailed information about the action.
    ip_address : str
        IP address of the actor.
    db_connection : sqlite3.Connection, optional
        An existing database connection.

    Returns
    -------
    dict
        Contains status and details about the audit entry.
    """
    import sqlite3

    close_conn = False
    if db_connection is None:
        db_connection = sqlite3.connect(":memory:")
        close_conn = True

    try:
        # Ensure audit_logs table exists
        db_connection.execute("""
            CREATE TABLE IF NOT EXISTS audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action_type TEXT NOT NULL,
                borrower_id INTEGER,
                actor TEXT DEFAULT 'borrower',
                details TEXT DEFAULT '{}',
                ip_address TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        details_json = json.dumps(details_dict or {})
        actor = "borrower"
        db_connection.execute(
            "INSERT INTO audit_logs (action_type, borrower_id, actor, details, ip_address) "
            "VALUES (?, ?, ?, ?, ?)",
            (action_type, borrower_id, actor, details_json, ip_address),
        )
        db_connection.commit()
        return {"status": "logged", "action_type": action_type, "borrower_id": borrower_id}
    except Exception as e:
        logger.exception("Failed to write audit trail entry")
        return {"status": "error", "error": str(e)}
    finally:
        if close_conn:
            db_connection.close()
