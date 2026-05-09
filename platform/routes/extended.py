"""
KYC, Payment, Collections, and misc routes for AI Lending Platform.
Imported by app.py to keep main file manageable.
"""
import sys, os, json, time
from datetime import datetime, timedelta, timezone
from functools import wraps

UNDERWRITING_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'underwriting')
AUTOMATION_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'automation')
sys.path.insert(0, UNDERWRITING_DIR)
sys.path.insert(0, AUTOMATION_DIR)


def register_routes(app, get_db, login_required, admin_required, audit_log, hash_password, check_password, generate_jwt, decode_jwt):
    """
    Register all extended routes on the Flask app.
    """
    log = app.logger
    TEMPLATE_DIR = app.template_folder
    from flask import request, jsonify, redirect, url_for, render_template, make_response, session, g, flash
    from config import Config

    # ── Settings-aware helper for routes ──

    _SETTINGS_CACHE = {}

    def _get_settings_value(*keys, default=''):
        """Read from launch/settings.json with dot-notation key path."""
        nonlocal _SETTINGS_CACHE
        if not _SETTINGS_CACHE:
            settings_path = os.path.join(os.path.dirname(__file__), '..', '..', 'launch', 'settings.json')
            if os.path.isfile(settings_path):
                try:
                    with open(settings_path) as f:
                        _SETTINGS_CACHE = json.load(f)
                except Exception:
                    _SETTINGS_CACHE = {}
            else:
                _SETTINGS_CACHE = {}
        val = _SETTINGS_CACHE
        for key in keys:
            if isinstance(val, dict):
                val = val.get(key)
            else:
                val = None
                break
        if val is not None and val != '':
            return val
        return default

    # ── KYC Routes ──

    @app.route('/kyc', methods=['GET', 'POST'])
    @login_required
    def kyc_page(user):
        bid = g.borrower_id
        db = get_db()
        borrower = db.execute("SELECT * FROM borrowers WHERE id=?", (bid,)).fetchone()
        docs = db.execute("SELECT * FROM kyc_documents WHERE borrower_id=?", (bid,)).fetchall()
        db.close()

        # Check if Stripe Identity is the configured KYC provider
        stripe_identity_enabled = False
        client_secret = None
        try:
            provider = _get_settings_value('kyc', 'provider', default='mock')
            if provider == 'stripe-identity':
                stripe_identity_enabled = True
                # Only create a new session if borrower doesn't already have a
                # pending stripe_identity document
                has_stripe_identity = any(
                    d['document_type'] == 'stripe_identity'
                    for d in docs
                )
                if not has_stripe_identity:
                    from kyc import stripe_identity_verify
                    result = stripe_identity_verify(bid)
                    if result.get('success') and result.get('client_secret'):
                        client_secret = result['client_secret']
                    elif result.get('fallback'):
                        # Stripe not configured — fall back to traditional upload UI
                        stripe_identity_enabled = False
        except Exception as e:
            log.warning("Stripe Identity setup error: %s", e)
            stripe_identity_enabled = False

        return render_template(
            'kyc.html',
            borrower=borrower,
            docs=docs,
            stripe_identity_enabled=stripe_identity_enabled,
            stripe_client_secret=client_secret,
            stripe_publishable_key=_get_settings_value('stripe',
                'publishable_key',
                default=Config.STRIPE_PUBLISHABLE_KEY if hasattr(Config, 'STRIPE_PUBLISHABLE_KEY') else '',
            ),
        )

    @app.route('/kyc/upload', methods=['POST'])
    @login_required
    def kyc_upload(user):
        bid = g.borrower_id
        doc_type = request.form.get('document_type', '')
        if doc_type not in ['government_id', 'proof_of_address', 'selfie', 'bank_statement']:
            flash('Invalid document type', 'error')
            return redirect('/kyc')
        file = request.files.get('document')
        if not file or file.filename == '':
            flash('No file selected', 'error')
            return redirect('/kyc')
        # Security: validate MIME type server-side
        allowed_mimes = {'application/pdf', 'image/jpeg', 'image/png'}
        if file.content_type not in allowed_mimes and file.content_type:
            flash('Invalid file type. Allowed: PDF, JPEG, PNG', 'error')
            return redirect('/kyc')
        upload_dir = os.path.join(os.path.dirname(__file__), '..', 'static', 'uploads', str(bid))
        os.makedirs(upload_dir, exist_ok=True)
        import werkzeug
        safe_name = werkzeug.utils.secure_filename(file.filename)
        # Generate a sanitized name that's impossible to traverse
        ext = safe_name.rsplit('.', 1)[-1] if '.' in safe_name else 'bin'
        # Validate extension
        if ext.lower() not in ('pdf', 'jpg', 'jpeg', 'png'):
            ext = 'bin'
        safe_name = f"{doc_type}_{int(time.time())}.{ext}"
        file_path = os.path.join(upload_dir, safe_name)
        file.save(file_path)
        db = get_db()
        db.execute(
            "INSERT INTO kyc_documents (borrower_id, document_type, file_path, verification_status) VALUES (?, ?, ?, 'pending')",
            (bid, doc_type, file_path)
        )
        db.commit()
        db.close()
        flash('Document uploaded! Under review.', 'success')
        return redirect('/kyc')

    @app.route('/kyc/auto-verify', methods=['POST'])
    @login_required
    def kyc_auto_verify(user):
        bid = g.borrower_id
        try:
            from kyc import auto_verify_kyc
            result = auto_verify_kyc(bid)
            if result.get('approved'):
                flash('KYC verified automatically!', 'success')
            else:
                flash(f"KYC pending: {result.get('reason', 'Additional docs needed')}", 'info')
        except Exception as e:
            log.error("KYC auto-verify error: %s", e)
            flash('Verification unavailable. Try again.', 'error')
        return redirect('/kyc')

    # ── Payment Routes ──

    @app.route('/payments')
    @login_required
    def payments_portal(user):
        """Full payment portal page."""
        bid = g.borrower_id
        db = get_db()

        # Get active loan
        loan = db.execute(
            "SELECT * FROM loans WHERE borrower_id=? AND status='active' ORDER BY id DESC LIMIT 1",
            (bid,),
        ).fetchone()

        # Get payments history
        payments = db.execute(
            "SELECT * FROM payments WHERE borrower_id=? ORDER BY created_at DESC LIMIT 50",
            (bid,),
        ).fetchall()

        # Get borrower name
        borrower = db.execute(
            "SELECT first_name, last_name FROM borrowers WHERE id=?",
            (bid,),
        ).fetchone()

        borrower_name = f"{borrower['first_name']} {borrower['last_name']}" if borrower else ''

        db.close()

        # Get saved payment methods
        from stripe_payments import get_payment_methods
        payment_methods = get_payment_methods(bid).get('methods', [])

        # Get auto-pay status
        auto_pay = None
        if loan:
            from stripe_payments import get_auto_pay_status
            auto_pay = get_auto_pay_status(bid, loan['id'])

        return render_template(
            'payments.html',
            loan=loan,
            payments=payments,
            payment_methods=payment_methods,
            auto_pay=auto_pay,
            now=datetime.now(timezone.utc).strftime('%Y-%m-%d'),
            borrower_name=borrower_name,
            stripe_publishable_key=Config.STRIPE_PUBLISHABLE_KEY,
        )

    @app.route('/payments/create-intent', methods=['POST'])
    @login_required
    def payments_create_intent(user):
        """AJAX endpoint: create a Stripe PaymentIntent and return client_secret."""
        bid = g.borrower_id
        loan_id = request.form.get('loan_id', type=int)
        amount_cents = int(float(request.form.get('amount', 0)) * 100)
        payment_method_id = request.form.get('payment_method_id', '')

        if amount_cents < 100:
            return jsonify({'error': 'Minimum payment is $1.00'}), 400

        db = get_db()
        loan = db.execute(
            "SELECT * FROM loans WHERE id=? AND borrower_id=? AND status='active'",
            (loan_id, bid),
        ).fetchone()
        db.close()

        if not loan:
            return jsonify({'error': 'Loan not found'}), 404

        from stripe_payments import create_payment_intent
        try:
            pi = create_payment_intent(
                amount_cents=amount_cents,
                borrower_id=bid,
                loan_id=loan_id,
                metadata={
                    'type': 'manual_payment',
                    'payment_method_id': payment_method_id,
                },
            )
            return jsonify({
                'client_secret': pi['client_secret'],
                'intent_id': pi['id'],
                'status': pi['status'],
            })
        except Exception as e:
            log.error("Create PaymentIntent error: %s", e)
            return jsonify({'error': 'Failed to create payment. Please try again.'}), 500

    @app.route('/payments/complete', methods=['POST'])
    @login_required
    def payments_complete(user):
        """AJAX endpoint: record a completed payment in the database."""
        bid = g.borrower_id
        loan_id = request.form.get('loan_id', type=int)
        amount_cents = int(request.form.get('amount_cents', 0))
        payment_intent_id = request.form.get('payment_intent_id', '')
        payment_method_id = request.form.get('payment_method_id', '')

        if not payment_intent_id or amount_cents <= 0:
            return jsonify({'error': 'Invalid payment data'}), 400

        db = get_db()
        loan = db.execute(
            "SELECT * FROM loans WHERE id=? AND borrower_id=? AND status='active'",
            (loan_id, bid),
        ).fetchone()

        if not loan:
            db.close()
            return jsonify({'error': 'Loan not found'}), 404

        try:
            # Record the payment
            db.execute(
                "INSERT INTO payments (loan_id, borrower_id, amount_cents, payment_type, status, stripe_payment_intent, paid_at) "
                "VALUES (?,?,?,'manual','completed',?,datetime('now'))",
                (loan_id, bid, amount_cents, payment_intent_id),
            )

            # Update loan balance
            new_balance = max(0, loan['remaining_balance'] - (amount_cents / 100))
            db.execute(
                "UPDATE loans SET remaining_balance=?, next_payment_date=? WHERE id=?",
                (new_balance, (datetime.now(timezone.utc) + timedelta(days=30)).strftime('%Y-%m-%d'), loan_id),
            )
            if new_balance <= 0:
                db.execute(
                    "UPDATE loans SET status='paid_off', paid_off_at=datetime('now') WHERE id=?",
                    (loan_id,),
                )

            # Update payment schedule if applicable
            db.execute(
                "UPDATE payment_schedules SET status='paid' "
                "WHERE loan_id=? AND status='pending' ORDER BY payment_number LIMIT 1",
                (loan_id,),
            )

            db.commit()

            audit_log('payment_received', bid, 'system', {
                'loan_id': loan_id,
                'amount_cents': amount_cents,
                'payment_intent': payment_intent_id,
            })

            # Save payment method if provided
            if payment_method_id:
                try:
                    from stripe_payments import save_payment_method
                    save_payment_method(bid, payment_method_id)
                except Exception as e:
                    log.warning("Failed to save payment method: %s", e)

        except Exception as e:
            db.rollback()
            log.error("Complete payment DB error: %s", e)
            return jsonify({'error': 'Database error'}), 500
        finally:
            db.close()

        return jsonify({'status': 'ok', 'new_balance': new_balance})

    @app.route('/payments/make', methods=['POST'])
    @login_required
    def payments_make(user):
        """Make a payment: create PaymentIntent, redirect to success."""
        bid = g.borrower_id
        loan_id = request.form.get('loan_id', type=int)
        amount_cents = int(float(request.form.get('amount', 0)) * 100)
        payment_method_id = request.form.get('payment_method_id', '')

        if amount_cents < 100:
            flash('Minimum payment is $1.00', 'error')
            return redirect('/payments')

        db = get_db()
        loan = db.execute(
            "SELECT * FROM loans WHERE id=? AND borrower_id=? AND status='active'",
            (loan_id, bid),
        ).fetchone()
        db.close()

        if not loan:
            flash('Loan not found', 'error')
            return redirect('/payments')

        from stripe_payments import create_payment_intent
        try:
            pi = create_payment_intent(
                amount_cents=amount_cents,
                borrower_id=bid,
                loan_id=loan_id,
                metadata={
                    'type': 'manual_payment',
                    'payment_method_id': payment_method_id,
                },
            )

            # In test mode without real Stripe, the mock PI is immediately usable
            # Record the payment directly for mock mode
            db = get_db()
            try:
                db.execute(
                    "INSERT INTO payments (loan_id, borrower_id, amount_cents, payment_type, status, stripe_payment_intent, paid_at) "
                    "VALUES (?,?,?,'manual','completed',?,datetime('now'))",
                    (loan_id, bid, amount_cents, pi['id']),
                )
                new_balance = max(0, loan['remaining_balance'] - (amount_cents / 100))
                db.execute(
                    "UPDATE loans SET remaining_balance=?, next_payment_date=? WHERE id=?",
                    (new_balance, (datetime.now(timezone.utc) + timedelta(days=30)).strftime('%Y-%m-%d'), loan_id),
                )
                if new_balance <= 0:
                    db.execute(
                        "UPDATE loans SET status='paid_off', paid_off_at=datetime('now') WHERE id=?",
                        (loan_id,),
                    )
                db.execute(
                    "UPDATE payment_schedules SET status='paid' "
                    "WHERE loan_id=? AND status='pending' ORDER BY payment_number LIMIT 1",
                    (loan_id,),
                )
                db.commit()
                audit_log('payment_received', bid, 'system', {
                    'loan_id': loan_id, 'amount_cents': amount_cents, 'payment_intent': pi['id'],
                })
            finally:
                db.close()

            return redirect(f'/payments/success?amount={amount_cents/100:.2f}&intent={pi["id"]}')

        except Exception as e:
            log.error("Payment error: %s", e)
            flash('Payment processing error', 'error')
            return redirect('/payments')

    @app.route('/payments/success')
    @login_required
    def payment_success(user):
        """Payment success confirmation page."""
        amount = request.args.get('amount', '0.00')
        intent_id = request.args.get('intent', '')
        return render_template('payment_success.html', amount=amount, intent_id=intent_id)

    @app.route('/payments/history')
    @login_required
    def payment_history_json(user):
        """JSON endpoint for payment history."""
        bid = g.borrower_id
        db = get_db()
        payments = db.execute(
            "SELECT * FROM payments WHERE borrower_id=? ORDER BY created_at DESC LIMIT 100",
            (bid,),
        ).fetchall()
        db.close()
        return jsonify([dict(p) for p in payments])

    @app.route('/payments/setup-auto-pay', methods=['POST'])
    @login_required
    def setup_auto_pay(user):
        """Enable auto-pay for a loan."""
        bid = g.borrower_id
        loan_id = request.form.get('loan_id', type=int)
        payment_method_id = request.form.get('payment_method_id', '')

        if not loan_id:
            flash('Loan ID required', 'error')
            return redirect('/payments')

        from stripe_payments import setup_auto_pay as sap, get_payment_methods

        # If no payment method specified, use the default
        if not payment_method_id:
            methods = get_payment_methods(bid).get('methods', [])
            if methods:
                payment_method_id = methods[0]['stripe_payment_method_id']

        if not payment_method_id:
            flash('Please save a payment method first', 'error')
            return redirect('/payments')

        result = sap(bid, loan_id, payment_method_id)

        if result.get('status') == 'succeeded':
            # Get card details for the confirmation screen
            methods = get_payment_methods(bid).get('methods', [])
            card_brand = ''
            card_last4 = ''
            for m in methods:
                if m['stripe_payment_method_id'] == payment_method_id:
                    card_brand = m['card_brand']
                    card_last4 = m['card_last4']
                    break
            return render_template(
                'auto_pay.html',
                success=True,
                card_brand=card_brand,
                card_last4=card_last4,
            )
        else:
            flash('Failed to set up auto-pay', 'error')
            return redirect('/payments')

    @app.route('/payments/cancel-auto-pay', methods=['POST'])
    @login_required
    def cancel_auto_pay(user):
        """Disable auto-pay for a loan."""
        bid = g.borrower_id
        loan_id = request.form.get('loan_id', type=int)

        if not loan_id:
            flash('Loan ID required', 'error')
            return redirect('/payments')

        from stripe_payments import cancel_auto_pay as cap
        result = cap(bid, loan_id)

        return render_template('auto_pay.html', success=False)

    @app.route('/stripe/webhook', methods=['POST'])
    def stripe_webhook():
        """Handle Stripe webhook events (payments + identity)."""
        payload = request.get_data()
        sig = request.headers.get('Stripe-Signature', '')
        webhook_secret = _get_settings_value('stripe', 'webhook_secret', default='')

        # Verify webhook signature when secret is configured
        if webhook_secret:
            try:
                import stripe
                event = stripe.Webhook.construct_event(payload, sig, webhook_secret)
            except Exception as e:
                log.error("Webhook signature verification failed: %s", e)
                return jsonify({'status': 'error', 'message': 'Invalid signature'}), 400
        else:
            log.warning("Webhook secret not configured — accepting unverified events (mock mode)")
            # Parse event without verification for mock/development
            try:
                import stripe
                event = stripe.Event.construct_from(json.loads(payload), stripe.api_key)
            except Exception as e:
                log.error("Webhook parse error (mock): %s", e)
                return jsonify({'status': 'error', 'message': 'Invalid payload'}), 400

        # Process the event
        result = {'status': 'received', 'type': event.type}
        try:
            from stripe_payments import process_webhook
            result = process_webhook(payload, sig)
        except Exception as e:
            log.error("process_webhook error: %s", e)

        # Handle identity verification events
        if event.type in (
            'identity.verification_session.verified',
            'identity.verification_session.processing',
        ):
            try:
                from kyc import handle_stripe_identity_completed
                identity_result = handle_stripe_identity_completed(event.data.object)
                result['identity'] = identity_result
                log.info("Stripe Identity webhook: %s — %s", event.type, identity_result)
            except Exception as e:
                log.error("Stripe Identity webhook handler error: %s", e)

        return jsonify(result)

    @app.route('/dashboard/make-payment', methods=['POST'])
    @login_required
    def make_payment(user):
        bid = g.borrower_id
        loan_id = request.form.get('loan_id', type=int)
        amount_cents = int(float(request.form.get('amount', 0)) * 100)
        if amount_cents < 100:
            flash('Minimum payment is $1.00', 'error')
            return redirect('/dashboard')
        db = get_db()
        loan = db.execute("SELECT * FROM loans WHERE id=? AND borrower_id=? AND status='active'", (loan_id, bid)).fetchone()
        if not loan:
            db.close()
            flash('Loan not found', 'error')
            return redirect('/dashboard')
        try:
            from stripe_payments import create_payment_intent
            pi = create_payment_intent(amount_cents, bid, loan_id, {'type': 'manual_payment'})
            pi_id = pi.get('id', '')

            # Always record payment in DB (mock or real)
            db.execute(
                "INSERT INTO payments (loan_id, borrower_id, amount_cents, payment_type, status, stripe_payment_intent, paid_at) VALUES (?,?,?,?,'completed',?,datetime('now'))",
                (loan_id, bid, amount_cents, 'manual', pi_id)
            )

            new_balance = max(0, loan['remaining_balance'] - (amount_cents / 100))
            db.execute("UPDATE loans SET remaining_balance=?, next_payment_date=? WHERE id=?",
                       (new_balance, (datetime.now(timezone.utc) + timedelta(days=30)).strftime('%Y-%m-%d'), loan_id))
            if new_balance <= 0:
                db.execute("UPDATE loans SET status='paid_off', paid_off_at=datetime('now') WHERE id=?", (loan_id,))

            # Try to confirm the payment if it's a mock (or real with payment method)
            try:
                from stripe_payments import confirm_payment
                confirm_payment(pi_id)
            except Exception:
                pass

            db.commit()
        except Exception as e:
            log.error("Payment error: %s", e)
            db.close()
            flash('Payment processing error', 'error')
            return redirect('/dashboard')

        audit_log('payment_received', bid, 'system', {'loan_id': loan_id, 'amount_cents': amount_cents})
        db.close()
        flash(f'Payment of ${amount_cents/100:.2f} applied!', 'success')
        return redirect('/dashboard')

    @app.route('/dashboard/loan/<int:loan_id>')
    @login_required
    def loan_detail(user, loan_id):
        bid = g.borrower_id
        db = get_db()
        loan = db.execute("SELECT * FROM loans WHERE id=? AND borrower_id=?", (loan_id, bid)).fetchone()
        if not loan:
            db.close()
            flash('Loan not found', 'error')
            return redirect('/dashboard')
        schedule = db.execute("SELECT * FROM payment_schedules WHERE loan_id=? ORDER BY payment_number", (loan_id,)).fetchall()
        payments = db.execute("SELECT * FROM payments WHERE loan_id=? ORDER BY paid_at DESC LIMIT 20", (loan_id,)).fetchall()
        db.close()
        return render_template('loan_detail.html', loan=loan, schedule=schedule, payments=payments)

    # ── Collections (Admin) ──

    @app.route('/admin/collections')
    @admin_required
    def admin_collections(admin):
        try:
            from loan_collections import get_collection_stats
            stats = get_collection_stats()
        except Exception as e:
            log.error("Collections stats error: %s", e)
            stats = {'total_overdue': 0, 'stage_counts': {}, 'total_at_risk': 0, 'total_charged_off': 0}
        db = get_db()
        overdue = db.execute("""
            SELECT l.*, b.first_name, b.last_name, b.email, b.phone
            FROM loans l JOIN borrowers b ON l.borrower_id = b.id
            WHERE l.status='active' AND l.next_payment_date < date('now')
            ORDER BY l.next_payment_date
        """).fetchall()
        coll = db.execute("""
            SELECT c.*, b.first_name, b.last_name
            FROM collections c JOIN borrowers b ON c.borrower_id = b.id
            ORDER BY c.created_at DESC LIMIT 50
        """).fetchall()
        db.close()
        return render_template('collections_dash.html', stats=stats, overdue=overdue, records=coll)

    @app.route('/admin/collections/run-cycle', methods=['POST'])
    @admin_required
    def admin_run_collections(admin):
        try:
            from loan_collections import run_collections_cycle
            result = run_collections_cycle()
            flash(f"Collections: {result.get('total_processed', 0)} loans processed", 'info')
        except Exception as e:
            log.error("Collections cycle error: %s", e)
            flash(f"Collections error: {e}", 'error')
        return redirect('/admin/collections')

    @app.route('/admin/kyc')
    @admin_required
    def admin_kyc_list(admin):
        try:
            from kyc import list_all_pending_kyc
            pending = list_all_pending_kyc()
        except:
            pending = []
        db = get_db()
        all_docs = db.execute("""
            SELECT k.*, b.first_name, b.last_name, b.email
            FROM kyc_documents k JOIN borrowers b ON k.borrower_id = b.id
            ORDER BY k.created_at DESC LIMIT 50
        """).fetchall()
        db.close()
        return render_template('kyc_admin.html', pending=pending, all_docs=all_docs)

    @app.route('/admin/kyc/verify/<int:doc_id>', methods=['POST'])
    @admin_required
    def admin_kyc_verify(admin, doc_id):
        db = get_db()
        doc = db.execute("SELECT * FROM kyc_documents WHERE id=?", (doc_id,)).fetchone()
        if doc:
            db.execute("UPDATE kyc_documents SET verification_status='verified' WHERE id=?", (doc_id,))
            bid = doc['borrower_id']
            docs = db.execute("SELECT verification_status FROM kyc_documents WHERE borrower_id=?", (bid,)).fetchall()
            all_verified = all(d['verification_status'] == 'verified' for d in docs)
            if all_verified:
                db.execute("UPDATE borrowers SET kyc_status='approved' WHERE id=?", (bid,))
                audit_log('kyc_approved', bid, 'admin', {'auto': False})
            db.commit()
            flash(f'Document #{doc_id} verified', 'success')
        else:
            flash('Document not found', 'error')
        db.close()
        return redirect('/admin/kyc')

    @app.route('/admin/kyc/reject/<int:doc_id>', methods=['POST'])
    @admin_required
    def admin_kyc_reject(admin, doc_id):
        db = get_db()
        doc = db.execute("SELECT * FROM kyc_documents WHERE id=?", (doc_id,)).fetchone()
        if doc:
            db.execute("UPDATE kyc_documents SET verification_status='rejected' WHERE id=?", (doc_id,))
            db.execute("UPDATE borrowers SET kyc_status='denied' WHERE id=?", (doc['borrower_id'],))
            db.commit()
            flash(f'Document #{doc_id} rejected', 'info')
        else:
            flash('Document not found', 'error')
        db.close()
        return redirect('/admin/kyc')

    # ── Static Pages ──

    @app.route('/about')
    def about():
        return render_template('about.html')

    @app.route('/terms')
    def terms():
        return render_template('terms.html')

    # ── Dashboard payments history (used by dashboard.html) ──

    @app.route('/dashboard/payments')
    @login_required
    def payment_history(user):
        """Legacy redirect to new payment portal."""
        return redirect('/payments')

    # ── API enhancements ──

    @app.route('/api/create-payment-intent', methods=['POST'])
    def api_create_payment():
        from stripe_payments import create_payment_intent as cpi
        data = request.get_json(silent=True) or {}
        try:
            pi = cpi(data.get('amount_cents', 1000), data.get('borrower_id', 0), data.get('loan_id', 0))
            return jsonify(pi)
        except Exception as e:
            return jsonify({
                'client_secret': 'pi_demo_' + str(int(time.time())),
                'id': 'pi_demo_' + str(int(time.time())),
                'status': 'requires_payment_method',
                'fallback': True
            })

    @app.route('/api/stripe-webhook', methods=['POST'])
    def api_stripe_webhook():
        try:
            from stripe_payments import process_webhook
            payload = request.get_data(as_text=True)
            sig = request.headers.get('Stripe-Signature', '')
            result = process_webhook(payload, sig)
            return jsonify(result)
        except Exception as e:
            log.info("Webhook received (fallback): %s bytes", len(request.get_data(as_text=True)))
            return jsonify({'status': 'received'})

    # ── Admin Settings routes ──

    @app.route('/admin/settings')
    @admin_required
    def admin_settings(admin):
        try:
            sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'launch'))
            sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'automation'))
            from automation.settings import load_settings, get_config_dict
            s = load_settings()
            cfg = get_config_dict()
            return render_template('admin_settings.html', settings=s, config=cfg)
        except Exception as e:
            log.error("Settings page error: %s", e)
            flash(f'Settings error: {e}', 'error')
            return redirect('/admin/dashboard')

    @app.route('/admin/settings/stripe', methods=['POST'])
    @admin_required
    def admin_settings_stripe(admin):
        try:
            from automation.settings import load_settings, save_settings
            s = load_settings()
            pk = request.form.get('publishable_key', '').strip()
            sk = request.form.get('secret_key', '').strip()
            ws = request.form.get('webhook_secret', '').strip()
            mode = 'live' if (pk and sk) else 'mock'
            s['stripe'].update({
                'publishable_key': pk,
                'secret_key': sk,
                'webhook_secret': ws,
                'mode': mode,
            })
            s['applied'] = False
            save_settings(s)
            flash('✅ Stripe credentials saved. Click "Apply Settings" to activate.', 'success')
        except Exception as e:
            log.error("Save Stripe error: %s", e)
            flash(f'Error: {e}', 'error')
        return redirect('/admin/settings')

    @app.route('/admin/settings/email', methods=['POST'])
    @admin_required
    def admin_settings_email(admin):
        try:
            from automation.settings import load_settings, save_settings
            s = load_settings()
            s['email'].update({
                'provider': request.form.get('provider', 'log'),
                'api_key': request.form.get('api_key', ''),
                'from_address': request.form.get('from_address', 'noreply@palmfi.com'),
            })
            s['applied'] = False
            save_settings(s)
            flash('✅ Email settings saved.', 'success')
        except Exception as e:
            flash(f'Error: {e}', 'error')
        return redirect('/admin/settings')

    @app.route('/admin/settings/kyc', methods=['POST'])
    @admin_required
    def admin_settings_kyc(admin):
        try:
            from automation.settings import load_settings, save_settings
            s = load_settings()
            s['kyc'].update({
                'provider': request.form.get('provider', 'mock'),
                'api_key': request.form.get('api_key', ''),
            })
            s['applied'] = False
            save_settings(s)
            flash('✅ KYC settings saved.', 'success')
        except Exception as e:
            flash(f'Error: {e}', 'error')
        return redirect('/admin/settings')

    @app.route('/admin/settings/domain', methods=['POST'])
    @admin_required
    def admin_settings_domain(admin):
        try:
            from automation.settings import load_settings, save_settings
            s = load_settings()
            s['domain'].update({
                'url': request.form.get('url', 'https://palm.ngrok.app').rstrip('/'),
                'stripe_webhook_path': request.form.get('stripe_webhook_path', '/stripe/webhook'),
            })
            s['applied'] = False
            save_settings(s)
            flash('✅ Domain settings saved.', 'success')
        except Exception as e:
            flash(f'Error: {e}', 'error')
        return redirect('/admin/settings')

    @app.route('/admin/settings/apply', methods=['POST'])
    @admin_required
    def admin_settings_apply(admin):
        try:
            from automation.settings import load_settings, save_settings
            s = load_settings()
            s['applied'] = True
            save_settings(s)
            if s['stripe']['secret_key']:
                os.environ['STRIPE_SECRET_KEY'] = s['stripe']['secret_key']
                os.environ['STRIPE_PUBLISHABLE_KEY'] = s['stripe']['publishable_key']
            if s['email']['api_key']:
                os.environ['EMAIL_API_KEY'] = s['email']['api_key']
            flash('✅ Settings applied! Live mode activated.', 'success')
        except Exception as e:
            flash(f'Error: {e}', 'error')
        return redirect('/admin/settings')

    log.info("Extended routes registered: KYC, Payments, Collections, About, Terms, Settings")
    return app
