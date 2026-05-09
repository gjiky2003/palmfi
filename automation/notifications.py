"""
Notification system with graceful fallbacks.

Sends email (SendGrid) and SMS (Twilio) with automatic fallback to
print/logging when API keys are missing. Integrates with the lending
platform database for borrower lookups and audit logging.

Works standalone (direct sqlite3) or imported alongside the platform module.
"""

import sys
import os
import json
import logging
from datetime import datetime, date

logger = logging.getLogger(__name__)

BRAND = 'AI Lending'
FROM_EMAIL_DEFAULT = 'noreply@ailending.com'


# ---------------------------------------------------------------------------
# DB path resolution — matches pattern in collections.py / kyc.py
# ---------------------------------------------------------------------------

def _resolve_db_path():
    """
    Return the absolute path to lending.db.

    Strategy:
      1. If platform.models is importable, use get_db() from it.
      2. Otherwise derive from this file's location:
         automation/notifications.py -> platform/lending.db
    """
    try:
        module_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if module_dir not in sys.path:
            sys.path.insert(0, module_dir)
        from platform.models import get_db  # noqa: F401
        return None
    except (ImportError, Exception):
        pass

    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    db_path = os.path.join(base, 'platform', 'lending.db')
    if not os.path.isfile(db_path):
        logger.warning("Database not found at %s — using path anyway", db_path)
    return db_path


def _get_connection():
    """Return a sqlite3 Connection with row_factory set."""
    resolved = _resolve_db_path()
    if resolved is None:
        from platform.models import get_db
        return get_db()

    import sqlite3
    conn = sqlite3.connect(resolved)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _to_dict(row):
    """Convert sqlite3.Row to a plain dict (safely handles None rows)."""
    if row is None:
        return None
    return dict(row)


def _get_borrower(borrower_id):
    """Fetch a borrower row by id, return dict or None."""
    conn = _get_connection()
    try:
        row = conn.execute(
            "SELECT id, first_name, last_name, email, phone FROM borrowers WHERE id = ?",
            (borrower_id,),
        ).fetchone()
        return _to_dict(row)
    finally:
        conn.close()


def _audit_log(action_type, borrower_id, actor='system', details=None):
    """Add an entry to the audit_logs table."""
    try:
        conn = _get_connection()
        conn.execute(
            "INSERT INTO audit_logs (action_type, borrower_id, actor, details) VALUES (?, ?, ?, ?)",
            (action_type, borrower_id, actor, json.dumps(details or {})),
        )
        conn.commit()
        conn.close()
    except Exception:
        logger.exception("Failed to write audit log entry")


# ---------------------------------------------------------------------------
# Config helper — load from env via platform.config if possible
# ---------------------------------------------------------------------------

_SETTINGS_CACHE = None


def _resolve_project_root():
    """Return the absolute path of the project root (one level above automation/)."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _get_settings_value(*keys, default=''):
    """
    Read a value from launch/settings.json with dot-notation key path.
    Fallback order: settings.json → Config/env → default.
    """
    global _SETTINGS_CACHE
    if _SETTINGS_CACHE is None:
        settings_path = os.path.join(_resolve_project_root(), 'launch', 'settings.json')
        if os.path.isfile(settings_path):
            try:
                with open(settings_path) as f:
                    _SETTINGS_CACHE = json.load(f)
            except Exception:
                _SETTINGS_CACHE = {}
        else:
            _SETTINGS_CACHE = {}
    # Walk the dot-notation path
    val = _SETTINGS_CACHE
    for key in keys:
        if isinstance(val, dict):
            val = val.get(key)
        else:
            val = None
            break
    if val is not None and val != '':
        return val
    return _get_config_value(keys[-1], default)


def _get_config_value(name, default=''):
    """Safely read a config value from Config class or os.environ."""
    try:
        module_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if module_dir not in sys.path:
            sys.path.insert(0, module_dir)
        from platform.config import Config
        return getattr(Config, name, os.getenv(name, default))
    except (ImportError, Exception):
        return os.getenv(name, default)


def _clear_settings_cache():
    """Clear cached settings (useful after admin applies new settings)."""
    global _SETTINGS_CACHE
    _SETTINGS_CACHE = None


# ---------------------------------------------------------------------------
# Branded HTML email wrapper
# ---------------------------------------------------------------------------

def _wrap_html(title, inner):
    """Wrap inner HTML content in a branded email template."""
    return f"""<!DOCTYPE html><html><body style="font-family:Arial,sans-serif;background:#f5f5f5;padding:20px">
  <div style="max-width:600px;margin:auto;background:#fff;border-radius:8px;overflow:hidden;border:1px solid #e3e3e3">
    <div style="background:#1565c0;color:#fff;padding:16px 24px;font-size:20px;font-weight:bold">{BRAND}</div>
    <div style="padding:24px;color:#222;line-height:1.5">
      <h2 style="margin-top:0;color:#1565c0">{title}</h2>
      {inner}
      <hr style="border:none;border-top:1px solid #eee;margin:24px 0"/>
      <p style="color:#888;font-size:12px">{BRAND} &middot; This is an automated message. Reply to support@ailending.com for help.</p>
    </div>
  </div></body></html>"""


# ---------------------------------------------------------------------------
# 1. send_email  —  SendGrid with fallback
# ---------------------------------------------------------------------------

def send_email(to_email, subject, body_html):
    """
    Send an HTML email via SendGrid.

    Falls back to print/logging if SendGrid is not configured or fails.
    Settings-aware: reads from launch/settings.json → Config/env → default.

    Returns dict with {'real': bool, 'sent': bool, ...}.
    """
    if not to_email:
        logger.warning("send_email: no recipient provided")
        return {'real': False, 'sent': False, 'to': '', 'subject': subject, 'error': 'no_recipient'}

    # Try settings.json first, then Config/env
    api_key = _get_settings_value('email', 'api_key', default='')
    if not api_key:
        api_key = _get_config_value('SENDGRID_API_KEY', '')
    from_addr = _get_settings_value('email', 'from_address', default='')

    if not api_key:
        logger.warning(
            "SENDGRID_API_KEY not configured — falling back to print. "
            "Would send email to %s: %s", to_email, subject
        )
        print(f"[EMAIL] To: {to_email} | Subject: {subject}")
        print(f"[EMAIL] Body: {body_html[:200]}...")
        return {'real': False, 'sent': True, 'to': to_email, 'subject': subject}

    try:
        from sendgrid import SendGridAPIClient
        from sendgrid.helpers.mail import Mail

        from_email = from_addr or _get_config_value('SENDGRID_FROM_EMAIL', FROM_EMAIL_DEFAULT)
        message = Mail(
            from_email=from_email,
            to_emails=to_email,
            subject=subject,
            html_content=body_html,
        )
        sg = SendGridAPIClient(api_key)
        response = sg.send(message)
        logger.info(
            "Email sent to %s — status %s",
            to_email, response.status_code,
        )
        return {'real': True, 'sent': True, 'to': to_email, 'subject': subject, 'status_code': response.status_code}
    except Exception:
        logger.exception("SendGrid email failed for %s — falling back to print", to_email)
        print(f"[EMAIL FALLBACK] To: {to_email} | Subject: {subject}")
        print(f"[EMAIL FALLBACK] Body: {body_html[:200]}...")
        return {'real': False, 'sent': False, 'to': to_email, 'subject': subject}


# ---------------------------------------------------------------------------
# 2. send_sms  —  Twilio with fallback
# ---------------------------------------------------------------------------

def send_sms(to_phone, message):
    """
    Send an SMS via Twilio.

    Falls back to print/logging if Twilio is not configured or fails.

    Returns dict with {'real': bool, 'sent': bool, ...}.
    """
    account_sid = _get_config_value('TWILIO_ACCOUNT_SID', '')
    auth_token = _get_config_value('TWILIO_AUTH_TOKEN', '')
    from_number = _get_config_value('TWILIO_FROM_NUMBER', '')

    if not account_sid or not auth_token or not from_number:
        logger.warning(
            "Twilio not fully configured (missing TWILIO_ACCOUNT_SID, "
            "TWILIO_AUTH_TOKEN, or TWILIO_FROM_NUMBER) — falling back to print. "
            "Would send SMS to %s: %s", to_phone, message[:100]
        )
        print(f"[SMS] To: {to_phone} | Message: {message}")
        return {'real': False, 'sent': True, 'to': to_phone}

    try:
        from twilio.rest import Client

        client = Client(account_sid, auth_token)
        twilio_message = client.messages.create(
            body=message,
            from_=from_number,
            to=to_phone,
        )
        logger.info(
            "SMS sent to %s — SID %s",
            to_phone, twilio_message.sid,
        )
        return {'real': True, 'sent': True, 'to': to_phone, 'sid': twilio_message.sid}
    except Exception:
        logger.exception("Twilio SMS failed for %s — falling back to print", to_phone)
        print(f"[SMS FALLBACK] To: {to_phone} | Message: {message}")
        return {'real': False, 'sent': False, 'to': to_phone}


# ---------------------------------------------------------------------------
# 3. notify_borrower
# ---------------------------------------------------------------------------

def notify_borrower(borrower_id, subject, message, channel='email'):
    """
    Look up borrower contact info from DB and send via the requested channel.

    Parameters
    ----------
    borrower_id : int
    subject : str
    message : str
    channel : str — 'email' or 'sms'

    Returns
    -------
    dict with status information.
    """
    borrower = _get_borrower(borrower_id)

    if borrower is None:
        logger.warning("notify_borrower: borrower %s not found", borrower_id)
        return {'real': False, 'sent': False, 'error': 'borrower_not_found'}

    result = None
    if channel == 'email':
        email = borrower.get('email', '')
        if not email:
            logger.warning("notify_borrower: borrower %s has no email", borrower_id)
            return {'real': False, 'sent': False, 'error': 'no_email'}
        html = _wrap_html(subject, f"<p>Hi {borrower.get('first_name', '')},</p><p>{message}</p>")
        result = send_email(email, subject, html)
    elif channel == 'sms':
        phone = borrower.get('phone', '')
        if not phone:
            logger.warning("notify_borrower: borrower %s has no phone", borrower_id)
            return {'real': False, 'sent': False, 'error': 'no_phone'}
        result = send_sms(phone, message)
    else:
        logger.warning("notify_borrower: unknown channel '%s'", channel)
        return {'real': False, 'sent': False, 'error': 'unknown_channel'}

    # Log to audit
    _audit_log(
        f'notification_{channel}',
        borrower_id,
        actor='system',
        details={
            'subject': subject,
            'channel': channel,
            'result': result,
        },
    )

    return result


# ---------------------------------------------------------------------------
# 4. notify_admin
# ---------------------------------------------------------------------------

def notify_admin(subject, message):
    """Send a notification to the admin email address from settings or Config."""
    admin_email = _get_settings_value('email', 'from_address', default='')
    if not admin_email:
        admin_email = _get_config_value('ADMIN_EMAIL', 'admin@ailending.com')
    html = _wrap_html(subject, f"<p>{message}</p>")
    return send_email(admin_email, subject, html)


# ---------------------------------------------------------------------------
# 5. send_payment_reminder
# ---------------------------------------------------------------------------

def send_payment_reminder(borrower_id, loan_id, amount_due, due_date):
    """
    Send a friendly reminder about an upcoming payment.

    Parameters
    ----------
    borrower_id : int
    loan_id : int
    amount_due : float — dollar amount
    due_date : str — e.g. '2025-05-15'
    """
    borrower = _get_borrower(borrower_id)

    if borrower is None:
        logger.warning("send_payment_reminder: borrower %s not found", borrower_id)
        return {'real': False, 'sent': False, 'error': 'borrower_not_found'}

    first_name = borrower.get('first_name', 'Valued Customer')
    subject = f"Payment Reminder — ${amount_due:.2f} due {due_date}"

    inner = f"""
      <p>Hi {first_name},</p>
      <p>This is a friendly reminder about your upcoming loan payment.</p>
      <table style="width:100%;border-collapse:collapse;margin:16px 0">
        <tr><td style="padding:8px;background:#f9f9f9"><b>Amount Due</b></td>
            <td style="padding:8px">${amount_due:.2f}</td></tr>
        <tr><td style="padding:8px;background:#f9f9f9"><b>Due Date</b></td>
            <td style="padding:8px">{due_date}</td></tr>
        <tr><td style="padding:8px;background:#f9f9f9"><b>Loan ID</b></td>
            <td style="padding:8px">{loan_id}</td></tr>
      </table>
      <p>Please log in to make your payment on time to avoid late fees.</p>
      <p>Thank you for being a valued borrower!</p>
    """
    email_body = _wrap_html(subject, inner)

    sms_message = (
        f"Hi {first_name}, reminder: ${amount_due:.2f} payment for loan #{loan_id} "
        f"is due {due_date}. Please log in to pay on time. Thank you!"
    )

    # Try email first, then SMS as fallback
    result = send_email(borrower.get('email', ''), subject, email_body)
    if result.get('sent'):
        return result

    phone = borrower.get('phone', '')
    if phone:
        return send_sms(phone, sms_message)

    return {'real': False, 'sent': False, 'error': 'no_channel_available'}


# ---------------------------------------------------------------------------
# 6. Collection dunning templates (stages 0–5)
# ---------------------------------------------------------------------------

_COLLECTION_TEMPLATES = {
    0: {
        'subject': "Friendly reminder: payment due — Loan #{loan_id}",
        'tone': "We noticed your payment is a few days late. No worries — life happens.",
        'cta': "Please make a payment when you get a chance to keep your account in good standing.",
    },
    1: {
        'subject': "Your payment is overdue — Loan #{loan_id}",
        'tone': "Your payment is now {days} days past due.",
        'cta': "Please log in and bring your account current to avoid additional fees.",
    },
    2: {
        'subject': "URGENT: Loan #{loan_id} — Late fee assessed",
        'tone': "Your account is {days} days past due. A late fee has been assessed.",
        'cta': "Pay today to stop further fees and protect your credit.",
    },
    3: {
        'subject': "FINAL NOTICE — Loan #{loan_id}",
        'tone': "Your loan is {days} days past due. This is a FINAL NOTICE before further action.",
        'cta': "Contact us within 7 days to arrange payment or a hardship plan.",
    },
    4: {
        'subject': "Legal referral pending — Loan #{loan_id}",
        'tone': "Your account ({days} days past due) is being prepared for legal/3rd-party referral.",
        'cta': "Call us immediately to resolve this matter and avoid escalation.",
    },
    5: {
        'subject': "Account charged off — Loan #{loan_id}",
        'tone': "After {days} days past due, your loan has been charged off and reported.",
        'cta': "Settlement options may still be available. Contact our recovery team.",
    },
}


def send_collection_notice(borrower_id, loan_id, days_past_due, stage):
    """
    Send an escalating urgency message based on collection stage.

    Parameters
    ----------
    borrower_id : int
    loan_id : int
    days_past_due : int
    stage : int — collection stage (0–5)

    Sends email always. Also sends SMS automatically for stages >= 2
    if the borrower has a phone number on file.
    """
    borrower = _get_borrower(borrower_id)

    if borrower is None:
        logger.warning("send_collection_notice: borrower %s not found", borrower_id)
        return {'real': False, 'sent': False, 'error': 'borrower_not_found'}

    tpl = _COLLECTION_TEMPLATES.get(int(stage), _COLLECTION_TEMPLATES[0])
    subject = tpl['subject'].format(loan_id=loan_id, days=days_past_due)

    inner = f"""
      <p>Hi {borrower.get('first_name', '')},</p>
      <p>{tpl['tone'].format(days=days_past_due)}</p>
      <p><b>{tpl['cta']}</b></p>
      <p>Loan: <b>#{loan_id}</b> &middot; Days past due: <b>{days_past_due}</b> &middot; Stage: <b>{stage}</b></p>
    """
    html = _wrap_html(subject, inner)

    email = borrower.get('email', '')
    phone = borrower.get('phone', '')

    # Always try email
    results = []
    if email:
        results.append(send_email(email, subject, html))
    else:
        logger.warning("send_collection_notice: borrower %s has no email", borrower_id)

    # SMS for stages >= 2 if phone available
    if int(stage) >= 2 and phone:
        sms_result = send_sms(phone, f"{BRAND}: {subject} — log in to resolve.")
        results.append(sms_result)
    elif int(stage) >= 2 and not phone:
        logger.warning("send_collection_notice: borrower %s has no phone for stage %s SMS", borrower_id, stage)

    # Log the collection action
    _audit_log(
        'collection_notice',
        borrower_id,
        actor='system',
        details={
            'loan_id': loan_id,
            'days_past_due': days_past_due,
            'stage': stage,
            'results': results,
        },
    )

    if not results:
        return {'real': False, 'sent': False, 'error': 'no_contact_info'}

    all_sent = all(r.get('sent') for r in results)
    return {'real': any(r.get('real') for r in results), 'sent': all_sent, 'results': results}


# ---------------------------------------------------------------------------
# 7. notify_loan_approved
# ---------------------------------------------------------------------------

def notify_loan_approved(borrower_id, loan_id, amount, apr):
    """
    Send a congratulatory message to the borrower about their approved loan.

    Parameters
    ----------
    borrower_id : int
    loan_id : int
    amount : float — approved loan amount in dollars
    apr : float — annual percentage rate (e.g. 8.5 for 8.5%)
    """
    borrower = _get_borrower(borrower_id)

    if borrower is None:
        logger.warning("notify_loan_approved: borrower %s not found", borrower_id)
        return {'real': False, 'sent': False, 'error': 'borrower_not_found'}

    first_name = borrower.get('first_name', 'Valued Customer')

    subject = f"Congratulations! Your Loan of ${amount:,.2f} Has Been Approved 🎉"

    inner = f"""
      <p>Hi {first_name},</p>
      <p>We're excited to let you know that your loan application has been <strong>approved</strong>.</p>
      <table style="width:100%;border-collapse:collapse;margin:16px 0;background:#f9f9f9;padding:8px;border-radius:6px">
        <tr><td style="padding:8px"><b>Loan Amount</b></td>
            <td style="padding:8px">${amount:,.2f}</td></tr>
        <tr><td style="padding:8px"><b>APR</b></td>
            <td style="padding:8px">{apr:.2f}%</td></tr>
        <tr><td style="padding:8px"><b>Loan ID</b></td>
            <td style="padding:8px">{loan_id}</td></tr>
      </table>
      <p>Funds will be disbursed to your account shortly. You can track your loan status
      by logging into your dashboard.</p>
      <p>If you have any questions, please don't hesitate to reach out to our support team.</p>
      <p>Welcome to the family! 🎊</p>
    """
    email_body = _wrap_html(subject, inner)

    sms_message = (
        f"Congratulations {first_name}! Your loan of ${amount:,.2f} at {apr:.1f}% APR "
        f"has been approved (Loan #{loan_id}). Funds will be disbursed shortly! 🎉"
    )

    email = borrower.get('email', '')
    phone = borrower.get('phone', '')

    # Try email first
    if email:
        result = send_email(email, subject, email_body)
    elif phone:
        result = send_sms(phone, sms_message)
    else:
        logger.warning("notify_loan_approved: borrower %s has no contact info", borrower_id)
        return {'real': False, 'sent': False, 'error': 'no_contact_info'}

    _audit_log(
        'loan_approved_notification',
        borrower_id,
        actor='system',
        details={
            'loan_id': loan_id,
            'amount': amount,
            'apr': apr,
            'result': result,
        },
    )

    return result
