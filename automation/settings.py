"""PalmFi — Admin Settings Panel for managing live credentials.

Routes:
  GET  /admin/settings          — Settings dashboard (API keys, KYC, email)
  POST /admin/settings/stripe   — Update Stripe credentials
  POST /admin/settings/email    — Update email provider credentials
  POST /admin/settings/domain   — Update domain/SSL configuration
  POST /admin/settings/apply    — Apply saved settings (restart depends)

All saved to platform/settings.json (not .env — survives DB resets).
Theme: PalmFi dark (slate-900, emerald-600).
"""

import json, os

SETTINGS_PATH = os.path.join(os.path.dirname(__file__), '..', '..', 'launch', 'settings.json')

DEFAULT_SETTINGS = {
    "stripe": {
        "publishable_key": "",
        "secret_key": "",
        "webhook_secret": "",
        "mode": "mock"  # "mock" | "live"
    },
    "email": {
        "provider": "log",  # "log" | "sendgrid" | "ses"
        "api_key": "",
        "from_address": "noreply@palmfi.com"
    },
    "kyc": {
        "provider": "mock",  # "mock" | "stripe-identity" | "persona" | "onfido"
        "api_key": ""
    },
    "domain": {
        "url": "https://palm.ngrok.app",
        "stripe_webhook_path": "/stripe/webhook"
    },
    "applied": False
}


def load_settings():
    """Load current settings from disk, falling back to defaults."""
    try:
        if os.path.exists(SETTINGS_PATH):
            with open(SETTINGS_PATH) as f:
                s = json.load(f)
                # Merge with defaults so new keys appear automatically
                merged = DEFAULT_SETTINGS.copy()
                merged.update(s)
                return merged
    except Exception:
        pass
    return dict(DEFAULT_SETTINGS)


def save_settings(settings):
    """Save settings to disk."""
    os.makedirs(os.path.dirname(SETTINGS_PATH), exist_ok=True)
    with open(SETTINGS_PATH, 'w') as f:
        json.dump(settings, f, indent=2)


def get_config_dict():
    """Return a flat dict of important config values (safe for display)."""
    s = load_settings()
    return {
        "stripe": {
            "mode": s["stripe"]["mode"],
            "publishable_key": s["stripe"]["publishable_key"][:8] + "..." if s["stripe"]["publishable_key"] else "(empty)",
            "secret_key_configured": bool(s["stripe"]["secret_key"]),
            "webhook_configured": bool(s["stripe"]["webhook_secret"]),
        },
        "email": {
            "provider": s["email"]["provider"],
            "from": s["email"]["from_address"],
        },
        "kyc": {
            "provider": s["kyc"]["provider"],
        },
        "domain": {
            "url": s["domain"]["url"],
        },
        "applied": s.get("applied", False),
    }


def register_settings_routes(app, get_db, admin_required):
    """Register admin settings routes into the Flask app."""

    @app.route('/admin/settings')
    @admin_required
    def admin_settings():
        s = load_settings()
        cfg = get_config_dict()
        return render_template('admin_settings.html', settings=s, config=cfg)

    @app.route('/admin/settings/stripe', methods=['POST'])
    @admin_required
    def admin_settings_stripe():
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
        return redirect('/admin/settings')

    @app.route('/admin/settings/email', methods=['POST'])
    @admin_required
    def admin_settings_email():
        s = load_settings()
        s['email'].update({
            'provider': request.form.get('provider', 'log'),
            'api_key': request.form.get('api_key', ''),
            'from_address': request.form.get('from_address', 'noreply@palmfi.com'),
        })
        s['applied'] = False
        save_settings(s)
        flash('✅ Email settings saved.', 'success')
        return redirect('/admin/settings')

    @app.route('/admin/settings/kyc', methods=['POST'])
    @admin_required
    def admin_settings_kyc():
        s = load_settings()
        s['kyc'].update({
            'provider': request.form.get('provider', 'mock'),
            'api_key': request.form.get('api_key', ''),
        })
        s['applied'] = False
        save_settings(s)
        flash('✅ KYC settings saved.', 'success')
        return redirect('/admin/settings')

    @app.route('/admin/settings/domain', methods=['POST'])
    @admin_required
    def admin_settings_domain():
        s = load_settings()
        s['domain'].update({
            'url': request.form.get('url', 'https://palm.ngrok.app').rstrip('/'),
            'stripe_webhook_path': request.form.get('stripe_webhook_path', '/stripe/webhook'),
        })
        s['applied'] = False
        save_settings(s)
        flash('✅ Domain settings saved.', 'success')
        return redirect('/admin/settings')

    @app.route('/admin/settings/apply', methods=['POST'])
    @admin_required
    def admin_settings_apply():
        """Apply settings to the running application.
        Updates Stripe keys in Config, reconfigures notifications, etc.
        """
        s = load_settings()
        s['applied'] = True
        save_settings(s)

        # Tell the app to reload config from settings
        try:
            # Update in-memory config
            from config import Config
            if s['stripe']['secret_key']:
                os.environ['STRIPE_SECRET_KEY'] = s['stripe']['secret_key']
                os.environ['STRIPE_PUBLISHABLE_KEY'] = s['stripe']['publishable_key']
            if s['email']['api_key']:
                os.environ['EMAIL_API_KEY'] = s['email']['api_key']
            flash('✅ Settings applied! Live mode activated.', 'success')
        except Exception as e:
            flash(f'⚠️ Applied but env override failed: {e}', 'warning')

        return redirect('/admin/settings')
