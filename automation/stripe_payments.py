"""
Real Stripe payment processing for the lending platform.

Handles customer creation, payment intents, webhook verification,
and batch processing of scheduled payments.

Works standalone (direct sqlite3) or imported alongside the platform module.
"""

import sys
import os
import json
import uuid
import logging
from datetime import datetime, date, timezone

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# DB path resolution — matches pattern in collections.py / kyc.py
# ---------------------------------------------------------------------------

def _resolve_db_path():
    """
    Return the absolute path to lending.db.

    Strategy:
      1. If platform.models is importable, use get_db() from it.
      2. Otherwise derive from this file's location:
         automation/stripe_payments.py -> platform/lending.db
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


def _mock_id(prefix):
    """Generate a deterministic-looking mock ID for use when Stripe is not configured."""
    return f"{prefix}_mock_{uuid.uuid4().hex[:24]}"


# ---------------------------------------------------------------------------
# Config helper
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Stripe initialization
# ---------------------------------------------------------------------------

def _get_stripe():
    """
    Import and configure the stripe module.

    Returns the stripe module if configured, or None if STRIPE_SECRET_KEY
    is missing (graceful degradation).
    """
    secret_key = _get_config_value('STRIPE_SECRET_KEY', '')
    if not secret_key or 'placeholder' in secret_key:
        logger.warning(
            "STRIPE_SECRET_KEY not configured or is a placeholder — "
            "Stripe operations will be simulated"
        )
        return None

    try:
        import stripe
        stripe.api_key = secret_key
        return stripe
    except ImportError:
        logger.warning("stripe Python package not installed — Stripe operations will be simulated")
        return None


def _log_audit(action_type, borrower_id, actor='system', details=None):
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
# 1. create_stripe_customer
# ---------------------------------------------------------------------------

def create_stripe_customer(borrower_id, email, name):
    """
    Create a Stripe Customer object.

    Parameters
    ----------
    borrower_id : int
    email : str
    name : str

    Returns
    -------
    dict with keys: real, customer_id
    """
    stripe = _get_stripe()
    real = bool(stripe)
    if stripe is None:
        logger.warning(
            "Stripe not configured — returning mock customer ID for borrower %s",
            borrower_id,
        )
        customer_id = _mock_id('cus')
        # Still update the borrower record with the mock ID
        conn = _get_connection()
        try:
            conn.execute(
                "UPDATE borrowers SET stripe_customer_id = ? WHERE id = ?",
                (customer_id, borrower_id),
            )
            conn.commit()
        finally:
            conn.close()
        return {'real': False, 'customer_id': customer_id}

    try:
        customer = stripe.Customer.create(
            email=email,
            name=name,
            metadata={'borrower_id': str(borrower_id)},
        )
        customer_id = customer['id']

        # Store customer ID in borrower record
        conn = _get_connection()
        try:
            conn.execute(
                "UPDATE borrowers SET stripe_customer_id = ? WHERE id = ?",
                (customer_id, borrower_id),
            )
            conn.commit()
        finally:
            conn.close()

        logger.info("Stripe customer created: %s for borrower %s", customer_id, borrower_id)

        _log_audit(
            'stripe_customer_created',
            borrower_id,
            actor='system',
            details={'stripe_customer_id': customer_id, 'email': email},
        )

        return {'real': True, 'customer_id': customer_id}
    except Exception:
        logger.exception("Failed to create Stripe customer for borrower %s", borrower_id)
        raise


# ---------------------------------------------------------------------------
# 2. create_payment_intent
# ---------------------------------------------------------------------------

def create_payment_intent(amount_cents, borrower_id, loan_id, metadata=None):
    """
    Create a Stripe PaymentIntent.

    Parameters
    ----------
    amount_cents : int — amount in cents (e.g. 5000 = $50.00)
    borrower_id : int
    loan_id : int
    metadata : dict, optional — additional metadata to include

    Returns
    -------
    dict with keys: client_secret, id (payment_intent_id), status
    """
    stripe = _get_stripe()
    real = bool(stripe)
    base_meta = {'loan_id': str(loan_id), 'borrower_id': str(borrower_id)}
    if metadata:
        base_meta.update(metadata)

    if stripe is None:
        mock_id = _mock_id('pi')
        logger.warning(
            "Stripe not configured — returning mock PaymentIntent for loan %s",
            loan_id,
        )
        result = {
            'real': False,
            'client_secret': f'{mock_id}_secret_mock',
            'id': mock_id,
            'status': 'requires_payment_method',
            'amount_cents': amount_cents,
            'currency': 'usd',
            'metadata': base_meta,
        }
        _log_audit(
            'payment_intent_created',
            borrower_id,
            actor='system',
            details={'loan_id': loan_id, 'mock': True, 'result': result},
        )
        return result

    try:
        intent = stripe.PaymentIntent.create(
            amount=amount_cents,
            currency='usd',
            metadata=base_meta,
        )
        result = {
            'real': True,
            'client_secret': intent['client_secret'],
            'id': intent['id'],
            'status': intent['status'],
            'amount_cents': amount_cents,
            'currency': 'usd',
            'metadata': base_meta,
        }
        logger.info(
            "PaymentIntent %s created for loan %s ($%.2f)",
            intent['id'], loan_id, amount_cents / 100.0,
        )
        _log_audit(
            'payment_intent_created',
            borrower_id,
            actor='system',
            details={'loan_id': loan_id, 'payment_intent_id': intent['id']},
        )
        return result
    except Exception:
        logger.exception("Failed to create PaymentIntent for loan %s", loan_id)
        raise


# ---------------------------------------------------------------------------
# 3. confirm_payment
# ---------------------------------------------------------------------------

def confirm_payment(payment_intent_id):
    """
    Confirm a Stripe PaymentIntent.

    Parameters
    ----------
    payment_intent_id : str

    Returns
    -------
    dict — result of the confirmation (stripe PaymentIntent dict or mock)
    """
    stripe = _get_stripe()
    real = bool(stripe)
    if stripe is None:
        if payment_intent_id.startswith('pi_mock_'):
            logger.warning(
                "Stripe not configured — confirming mock PaymentIntent %s",
                payment_intent_id,
            )
            return {
                'real': False,
                'id': payment_intent_id,
                'status': 'succeeded',
                'mock': True,
            }
        logger.warning(
            "Stripe not configured and %s is not a mock — returning error",
            payment_intent_id,
        )
        return {
            'real': False,
            'id': payment_intent_id,
            'status': 'error',
            'error': 'stripe_not_configured',
        }

    try:
        intent = stripe.PaymentIntent.confirm(payment_intent_id)
        logger.info("PaymentIntent %s confirmed — status: %s", payment_intent_id, intent['status'])
        result = dict(intent)
        result['real'] = True
        return result
    except Exception:
        logger.exception("Failed to confirm PaymentIntent %s", payment_intent_id)
        raise


# ---------------------------------------------------------------------------
# 4. process_webhook
# ---------------------------------------------------------------------------

def process_webhook(payload, sig_header):
    """
    Process a Stripe webhook event.

    Verifies the webhook signature using Config.STRIPE_WEBHOOK_SECRET,
    then handles:
        - payment_intent.succeeded
        - payment_intent.payment_failed

    Updates payment records in the database accordingly.

    Parameters
    ----------
    payload : bytes — raw request body
    sig_header : str — Stripe-Signature header value

    Returns
    -------
    dict with keys: status, event_type, details
    """
    stripe = _get_stripe()
    webhook_secret = _get_config_value('STRIPE_WEBHOOK_SECRET', '')

    if not webhook_secret or 'placeholder' in webhook_secret:
        logger.warning("STRIPE_WEBHOOK_SECRET not configured — skipping webhook verification")
        return {'real': False, 'status': 'skipped', 'reason': 'webhook_secret_not_configured'}

    if stripe is None:
        logger.warning("Stripe not configured — cannot verify webhook")
        return {'real': False, 'status': 'skipped', 'reason': 'stripe_not_configured'}

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, webhook_secret
        )
    except ValueError:
        logger.exception("Invalid webhook payload")
        return {'real': False, 'status': 'error', 'reason': 'invalid_payload'}
    except stripe.error.SignatureVerificationError:
        logger.exception("Invalid webhook signature")
        return {'real': False, 'status': 'error', 'reason': 'invalid_signature'}

    event_type = event['type']
    event_data = event['data']['object']
    logger.info("Webhook received: %s — ID: %s", event_type, event_data.get('id', ''))

    result = {'real': True, 'status': 'processed', 'event_type': event_type, 'details': {}}

    if event_type == 'payment_intent.succeeded':
        result['details'] = _handle_payment_succeeded(event_data)
    elif event_type == 'payment_intent.payment_failed':
        result['details'] = _handle_payment_failed(event_data)
    else:
        logger.info("Unhandled webhook event type: %s", event_type)
        result['details'] = {'info': f'Unhandled event type: {event_type}'}

    return result


def _handle_payment_succeeded(event_data):
    """Update payment record when a PaymentIntent succeeds."""
    intent_id = event_data.get('id', '')
    metadata = event_data.get('metadata', {})
    loan_id = metadata.get('loan_id', '0')
    borrower_id = metadata.get('borrower_id', '0')
    amount_received = event_data.get('amount_received', 0)

    conn = _get_connection()
    try:
        # Update the payment record in the payments table
        conn.execute(
            "UPDATE payments SET status = 'completed', "
            "  stripe_payment_intent = ?, paid_at = CURRENT_TIMESTAMP "
            "WHERE stripe_payment_intent = ?",
            (intent_id, intent_id),
        )

        # Also update the payment_schedules record
        conn.execute(
            "UPDATE payment_schedules SET status = 'paid' "
            "WHERE loan_id = ? AND status = 'pending'",
            (int(loan_id),),
        )

        # Update loan remaining balance
        conn.execute(
            "UPDATE loans SET remaining_balance = remaining_balance - ? "
            "WHERE id = ? AND status = 'active'",
            (amount_received / 100.0, int(loan_id)),
        )

        conn.commit()
        logger.info(
            "Payment %s succeeded for loan %s — amount $%.2f",
            intent_id, loan_id, amount_received / 100.0,
        )

        _log_audit(
            'payment_succeeded',
            int(borrower_id) if borrower_id else 0,
            actor='stripe_webhook',
            details={
                'payment_intent_id': intent_id,
                'loan_id': loan_id,
                'amount_cents': amount_received,
            },
        )

        return {
            'real': True,
            'payment_intent_id': intent_id,
            'loan_id': int(loan_id),
            'amount_cents': amount_received,
            'status': 'completed',
        }
    except Exception:
        conn.rollback()
        logger.exception("Failed to process successful payment %s", intent_id)
        return {
            'real': False,
            'payment_intent_id': intent_id,
            'status': 'error',
            'error': 'database_update_failed',
        }
    finally:
        conn.close()


def _handle_payment_failed(event_data):
    """Update payment record when a PaymentIntent fails."""
    intent_id = event_data.get('id', '')
    metadata = event_data.get('metadata', {})
    loan_id = metadata.get('loan_id', '0')
    borrower_id = metadata.get('borrower_id', '0')
    failure_message = event_data.get('failure_message', 'Unknown error')
    failure_code = event_data.get('failure_code', '')

    conn = _get_connection()
    try:
        conn.execute(
            "UPDATE payments SET status = 'failed', stripe_payment_intent = ? "
            "WHERE stripe_payment_intent = ?",
            (intent_id, intent_id),
        )
        conn.commit()

        logger.warning(
            "Payment %s failed for loan %s: %s (%s)",
            intent_id, loan_id, failure_message, failure_code,
        )

        _log_audit(
            'payment_failed',
            int(borrower_id) if borrower_id else 0,
            actor='stripe_webhook',
            details={
                'payment_intent_id': intent_id,
                'loan_id': loan_id,
                'failure_message': failure_message,
                'failure_code': failure_code,
            },
        )

        return {
            'real': True,
            'payment_intent_id': intent_id,
            'loan_id': int(loan_id) if loan_id else 0,
            'failure_message': failure_message,
            'failure_code': failure_code,
            'status': 'failed',
        }
    except Exception:
        conn.rollback()
        logger.exception("Failed to process failed payment %s", intent_id)
        return {
            'real': False,
            'payment_intent_id': intent_id,
            'status': 'error',
            'error': 'database_update_failed',
        }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 5. process_scheduled_payment
# ---------------------------------------------------------------------------

def process_scheduled_payment(loan_id, payment_number):
    """
    Process a single payment from the payment schedule.

    Gets the payment_schedule record, creates a PaymentIntent,
    and updates the database accordingly.

    Parameters
    ----------
    loan_id : int
    payment_number : int — which payment in the schedule (1-indexed)

    Returns
    -------
    dict with status information and payment intent details.
    """
    conn = _get_connection()
    try:
        schedule_row = _to_dict(conn.execute(
            "SELECT * FROM payment_schedules "
            "WHERE loan_id = ? AND payment_number = ?",
            (loan_id, payment_number),
        ).fetchone())
    finally:
        conn.close()

    stripe = _get_stripe()
    if schedule_row is None:
        logger.warning(
            "process_scheduled_payment: no schedule entry for loan %s payment %s",
            loan_id, payment_number,
        )
        return {'real': False, 'status': 'error', 'reason': 'schedule_entry_not_found'}

    if schedule_row.get('status') == 'paid':
        logger.info(
            "process_scheduled_payment: loan %s payment %s already paid",
            loan_id, payment_number,
        )
        return {'real': bool(stripe), 'status': 'skipped', 'reason': 'already_paid'}

    # Get the borrower_id from the loan record
    conn = _get_connection()
    try:
        loan_row = _to_dict(conn.execute(
            "SELECT borrower_id FROM loans WHERE id = ?",
            (loan_id,),
        ).fetchone())
    finally:
        conn.close()

    if loan_row is None:
        return {'real': bool(stripe), 'status': 'error', 'reason': 'loan_not_found'}

    borrower_id = loan_row['borrower_id']
    amount_cents = schedule_row['amount_cents']
    due_date = schedule_row.get('due_date', '')

    # Create the payment intent
    payment_result = create_payment_intent(
        amount_cents=amount_cents,
        borrower_id=borrower_id,
        loan_id=loan_id,
        metadata={
            'payment_number': str(payment_number),
            'due_date': due_date,
        },
    )

    # Record in payments table
    conn = _get_connection()
    try:
        conn.execute(
            "INSERT INTO payments (loan_id, borrower_id, amount_cents, "
            "  payment_type, status, due_date, stripe_payment_intent) "
            "VALUES (?, ?, ?, 'scheduled', 'pending', ?, ?)",
            (loan_id, borrower_id, amount_cents, due_date, payment_result['id']),
        )
        conn.commit()
    finally:
        conn.close()

    logger.info(
        "Scheduled payment %s for loan %s processed — PI: %s ($%.2f)",
        payment_number, loan_id, payment_result['id'], amount_cents / 100.0,
    )

    return {
        'real': bool(stripe),
        'status': 'initiated',
        'loan_id': loan_id,
        'payment_number': payment_number,
        'amount_cents': amount_cents,
        'due_date': due_date,
        'payment_intent': payment_result,
    }


# ---------------------------------------------------------------------------
# 6. process_payment_batch
# ---------------------------------------------------------------------------

def process_payment_batch():
    """
    Loop all active loans with due dates today or in the past,
    and create payment intents for each unpaid schedule item.

    Returns
    -------
    dict — summary with counts and per-item results.
    """
    stripe = _get_stripe()
    today_str = date.today().isoformat()
    results = []
    stats = {'processed': 0, 'skipped': 0, 'errors': 0, 'total_amount_cents': 0}

    conn = _get_connection()
    try:
        # Find all payment_schedule items that are due and unpaid
        rows = conn.execute(
            """
            SELECT ps.id, ps.loan_id, ps.payment_number, ps.due_date,
                   ps.amount_cents, l.borrower_id
            FROM payment_schedules ps
            JOIN loans l ON ps.loan_id = l.id
            WHERE l.status = 'active'
              AND ps.status = 'pending'
              AND ps.due_date <= ?
            ORDER BY ps.loan_id, ps.payment_number
            """,
            (today_str,),
        ).fetchall()
    finally:
        conn.close()

    schedule_items = [_to_dict(r) for r in rows]

    if not schedule_items:
        logger.info("process_payment_batch: no due payments found")
        return {
            'real': bool(stripe),
            'total_due': 0,
            'processed': 0,
            'skipped': 0,
            'errors': 0,
            'total_amount_cents': 0,
            'results': [],
        }

    logger.info("process_payment_batch: found %d due payment(s)", len(schedule_items))

    for item in schedule_items:
        try:
            result = process_scheduled_payment(
                loan_id=item['loan_id'],
                payment_number=item['payment_number'],
            )
            results.append(result)

            if result['status'] == 'initiated':
                stats['processed'] += 1
                stats['total_amount_cents'] += result.get('amount_cents', 0)
            elif result['status'] == 'skipped':
                stats['skipped'] += 1
            else:
                stats['errors'] += 1

        except Exception:
            logger.exception(
                "Failed to process payment for loan %s payment %s",
                item['loan_id'], item['payment_number'],
            )
            stats['errors'] += 1
            results.append({
                'status': 'error',
                'loan_id': item['loan_id'],
                'payment_number': item['payment_number'],
                'error': 'unexpected_error',
            })

    total_amount_dollars = stats['total_amount_cents'] / 100.0
    summary = {
        'real': bool(stripe),
        'total_due': len(schedule_items),
        'processed': stats['processed'],
        'skipped': stats['skipped'],
        'errors': stats['errors'],
        'total_amount_cents': stats['total_amount_cents'],
        'total_amount_dollars': total_amount_dollars,
        'results': results,
    }

    logger.info(
        "Payment batch complete: %d due, %d processed ($%.2f), %d skipped, %d errors",
        len(schedule_items), stats['processed'], total_amount_dollars,
        stats['skipped'], stats['errors'],
    )

    return summary


# ---------------------------------------------------------------------------
# 7. refund_payment
# ---------------------------------------------------------------------------

def refund_payment(payment_id):
    """
    Issue a refund for a payment.

    Parameters
    ----------
    payment_id : int — the ID in the payments table

    Returns
    -------
    dict with refund status details.
    """
    conn = _get_connection()
    try:
        payment = _to_dict(conn.execute(
            "SELECT * FROM payments WHERE id = ?", (payment_id,)
        ).fetchone())
    finally:
        conn.close()

    if payment is None:
        return {'real': False, 'status': 'error', 'reason': 'payment_not_found'}

    stripe_pi = payment.get('stripe_payment_intent', '')
    amount_cents = payment['amount_cents']
    borrower_id = payment['borrower_id']
    loan_id = payment['loan_id']

    stripe = _get_stripe()
    if stripe is None:
        logger.warning("Stripe not configured — simulating refund for payment %s", payment_id)
        refund_result = {
            'real': False,
            'id': _mock_id('re'),
            'payment_intent': stripe_pi or f'pi_mock_refund_{payment_id}',
            'status': 'succeeded',
            'mock': True,
        }
    else:
        try:
            refund = stripe.Refund.create(
                payment_intent=stripe_pi,
                amount=amount_cents,
            )
            refund_result = dict(refund)
            refund_result['real'] = True
        except Exception:
            logger.exception("Failed to refund payment %s", payment_id)
            return {'real': False, 'status': 'error', 'reason': 'refund_failed'}

    conn = _get_connection()
    try:
        conn.execute(
            "UPDATE payments SET status = 'refunded' WHERE id = ?",
            (payment_id,),
        )
        conn.execute(
            "UPDATE loans SET remaining_balance = remaining_balance + ? "
            "WHERE id = ? AND status IN ('active', 'paid_off')",
            (amount_cents / 100.0, loan_id),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        logger.exception("Failed to update DB for refund %s", payment_id)
    finally:
        conn.close()

    _log_audit('payment_refunded', borrower_id, actor='system', details={
        'payment_id': payment_id, 'loan_id': loan_id, 'amount_cents': amount_cents,
        'refund_id': refund_result.get('id', ''),
    })

    return {
        'real': bool(stripe),
        'status': 'succeeded' if refund_result.get('status') == 'succeeded' else 'processing',
        'refund_id': refund_result.get('id', ''),
        'payment_intent': stripe_pi,
        'amount_cents': amount_cents,
    }


# ---------------------------------------------------------------------------
# 8. save_payment_method
# ---------------------------------------------------------------------------

def save_payment_method(borrower_id, payment_method_id):
    """
    Attach a Stripe PaymentMethod to a customer and save details locally.

    Parameters
    ----------
    borrower_id : int
    payment_method_id : str — Stripe PM ID (pm_...)

    Returns
    -------
    dict with saved method details.
    """
    stripe = _get_stripe()
    real = bool(stripe)

    if stripe is None:
        logger.warning("Stripe not configured — simulating payment method save for borrower %s", borrower_id)
        card_last4 = '4242'
        card_brand = 'visa'
        exp_month = 12
        exp_year = 2028
        pm_id = payment_method_id or _mock_id('pm')
    else:
        try:
            pm = stripe.PaymentMethod.retrieve(payment_method_id)
            card = pm.get('card', {})
            card_last4 = card.get('last4', '0000')
            card_brand = card.get('brand', 'unknown')
            exp_month = card.get('exp_month', 0)
            exp_year = card.get('exp_year', 0)
            pm_id = payment_method_id

            # Get customer ID
            conn = _get_connection()
            try:
                borrower = _to_dict(conn.execute(
                    "SELECT stripe_customer_id FROM borrowers WHERE id = ?", (borrower_id,)
                ).fetchone())
            finally:
                conn.close()

            customer_id = borrower.get('stripe_customer_id', '') if borrower else ''
            if customer_id:
                stripe.PaymentMethod.attach(payment_method_id, customer=customer_id)
                # Set as default payment method on customer
                stripe.Customer.modify(
                    customer_id,
                    invoice_settings={'default_payment_method': payment_method_id},
                )
        except Exception:
            logger.exception("Failed to retrieve/attach PaymentMethod %s", payment_method_id)
            return {'real': real, 'status': 'error', 'reason': 'payment_method_retrieve_failed'}

    conn = _get_connection()
    try:
        # Set all existing methods as non-default
        conn.execute(
            "UPDATE payment_methods SET is_default = 0 WHERE borrower_id = ?",
            (borrower_id,),
        )
        # Insert or update
        existing = conn.execute(
            "SELECT id FROM payment_methods WHERE stripe_payment_method_id = ?",
            (pm_id,),
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE payment_methods SET card_last4=?, card_brand=?, exp_month=?, exp_year=?, is_default=1 WHERE id=?",
                (card_last4, card_brand, exp_month, exp_year, existing['id']),
            )
        else:
            conn.execute(
                "INSERT INTO payment_methods (borrower_id, stripe_payment_method_id, card_last4, card_brand, exp_month, exp_year, is_default) VALUES (?, ?, ?, ?, ?, ?, 1)",
                (borrower_id, pm_id, card_last4, card_brand, exp_month, exp_year),
            )
        conn.commit()
        pm_db_id = conn.execute(
            "SELECT id FROM payment_methods WHERE stripe_payment_method_id = ?",
            (pm_id,),
        ).fetchone()['id']
    except Exception:
        conn.rollback()
        logger.exception("Failed to save payment method to DB")
        return {'real': real, 'status': 'error', 'reason': 'db_save_failed'}
    finally:
        conn.close()

    _log_audit('payment_method_saved', borrower_id, actor='system', details={
        'payment_method_id': pm_id, 'card_last4': card_last4, 'card_brand': card_brand,
    })

    return {
        'real': real,
        'status': 'succeeded',
        'id': pm_id,
        'db_id': pm_db_id if not isinstance(pm_db_id, dict) else None,
        'card_last4': card_last4,
        'card_brand': card_brand,
        'exp_month': exp_month,
        'exp_year': exp_year,
    }


# ---------------------------------------------------------------------------
# 9. setup_auto_pay
# ---------------------------------------------------------------------------

def setup_auto_pay(borrower_id, loan_id, payment_method_id):
    """
    Enable auto-pay for a loan using a saved payment method.

    Parameters
    ----------
    borrower_id : int
    loan_id : int
    payment_method_id : str — Stripe PaymentMethod ID

    Returns
    -------
    dict with status of auto-pay setup.
    """
    stripe = _get_stripe()
    conn = _get_connection()
    try:
        existing = conn.execute(
            "SELECT id FROM auto_pay WHERE borrower_id = ? AND loan_id = ?",
            (borrower_id, loan_id),
        ).fetchone()

        if existing:
            conn.execute(
                "UPDATE auto_pay SET payment_method_id = ?, active = 1 WHERE id = ?",
                (payment_method_id, existing['id']),
            )
        else:
            conn.execute(
                "INSERT INTO auto_pay (borrower_id, loan_id, payment_method_id, active) VALUES (?, ?, ?, 1)",
                (borrower_id, loan_id, payment_method_id),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        logger.exception("Failed to set up auto-pay for borrower %s loan %s", borrower_id, loan_id)
        return {'real': bool(stripe), 'status': 'error', 'reason': 'db_update_failed'}
    finally:
        conn.close()

    _log_audit('auto_pay_enabled', borrower_id, actor='system', details={
        'loan_id': loan_id, 'payment_method_id': payment_method_id,
    })

    return {'real': bool(stripe), 'status': 'succeeded', 'loan_id': loan_id, 'active': True}


def cancel_auto_pay(borrower_id, loan_id):
    """
    Disable auto-pay for a loan.

    Parameters
    ----------
    borrower_id : int
    loan_id : int

    Returns
    -------
    dict with status.
    """
    stripe = _get_stripe()
    conn = _get_connection()
    try:
        conn.execute(
            "UPDATE auto_pay SET active = 0 WHERE borrower_id = ? AND loan_id = ?",
            (borrower_id, loan_id),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        logger.exception("Failed to cancel auto-pay for borrower %s loan %s", borrower_id, loan_id)
        return {'real': bool(stripe), 'status': 'error', 'reason': 'db_update_failed'}
    finally:
        conn.close()

    _log_audit('auto_pay_disabled', borrower_id, actor='system', details={
        'loan_id': loan_id,
    })

    return {'real': bool(stripe), 'status': 'succeeded', 'loan_id': loan_id, 'active': False}


def get_auto_pay_status(borrower_id, loan_id):
    """
    Check whether auto-pay is active for a loan.

    Parameters
    ----------
    borrower_id : int
    loan_id : int

    Returns
    -------
    dict with auto_pay status.
    """
    stripe = _get_stripe()
    conn = _get_connection()
    try:
        row = _to_dict(conn.execute(
            "SELECT * FROM auto_pay WHERE borrower_id = ? AND loan_id = ?",
            (borrower_id, loan_id),
        ).fetchone())
    finally:
        conn.close()

    if row:
        return {
            'real': bool(stripe),
            'active': bool(row['active']),
            'payment_method_id': row['payment_method_id'],
            'created_at': row['created_at'],
        }
    return {'real': bool(stripe), 'active': False, 'payment_method_id': None, 'created_at': None}


def get_payment_methods(borrower_id):
    """
    Get all saved payment methods for a borrower.

    Parameters
    ----------
    borrower_id : int

    Returns
    -------
    dict with keys: real, methods (list of dicts), count (int)
    """
    stripe = _get_stripe()
    conn = _get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM payment_methods WHERE borrower_id = ? ORDER BY is_default DESC, created_at DESC",
            (borrower_id,),
        ).fetchall()
    finally:
        conn.close()

    methods = [_to_dict(r) for r in rows]
    return {'real': bool(stripe), 'methods': methods, 'count': len(methods)}
