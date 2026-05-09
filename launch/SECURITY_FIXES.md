# 🔐 PalmFi — Security Hardening Guide

This documents the changes made during the May 9 security audit.

## What Was Fixed

### C1 — Debug Mode (Critical)
- **Before:** `app.run(debug=True)` — Werkzeug console accessible
- **After:** `app.run(debug=os.getenv('FLASK_DEBUG', 'false').lower() == 'true')`
- **Set `FLASK_DEBUG=false` in production**

### C2 — Hardcoded Secrets (Critical)
- **Before:** Weak defaults in config.py: 'ai-lending-secret-key-change-in-prod', 'admin123', etc.
- **After:** All secrets must come from environment. Config.py raises ValueError if SECRET_KEY or JWT_SECRET are missing.

### C3 — Password Hashing (Critical)
- **Before:** SHA-256 with static "salt" — reversible in seconds
- **After:** bcrypt with per-password salt
- **Legacy support:** Old SHA-256 hashes still verified during migration

### C4 — Path Traversal in KYC Upload (Critical)
- **Before:** User-controlled extension + no MIME validation
- **After:** `werkzeug.utils.secure_filename()`, server-side MIME check, extension whitelist

### C5 — Unauthenticated Scoring API (Critical)
- **Before:** Anyone could hit `/api/score-application` without auth
- **After:** `@login_required` enforced

### C6 — Unauthenticated Rate Improvement API (Critical)
- **Before:** Anyone could query any loan's rate data via `/api/rate-improvement/<id>`
- **After:** `@admin_required` enforced

### C7 — Webhook Signature Bypass (Critical)
- **Before:** Silent `except: pass` on signature verification failures
- **After:** Signature required when webhook secret is configured; mock-mode fallback for dev

### H7 — Default Admin Password (High)
- **Before:** Falls back to 'admin123' if ADMIN_PASSWORD env var missing
- **After:** Generates a random 128-bit token_urlsafe password, logs it to console

## To Do (Not Yet Fixed)

These are documented in SECURITY_AUDIT.md as Medium/Low priority:

- **CSRF protection** — Add Flask-WTF CSRFProtect across all forms
- **Security headers** — Add Flask-Talisman for CSP, HSTS, XFO
- **Session cookie flags** — Set HttpOnly, Secure, SameSite in Config
- **CORS** — Restrict origins with flask-cors
- **Rate limiting** — Flask-Limiter on login endpoints
- **SRI on CDN assets** — Add integrity checks to tailwind/font-awesome
- **MAX_CONTENT_LENGTH** — Set global upload size limit
- **HTTPS redirect** — Add via reverse proxy or Flask-Talisman

## Quick Verification

```bash
# Check debug mode is off
grep 'debug=' platform/app.py | grep -v 'FLASK_DEBUG'

# Check no SHA-256 password hashing (should only be in check_password legacy path)
grep -n 'sha256' platform/app.py

# Check no hardcoded secrets in config
grep -E '(placeholder|change-in-prod|admin123)' platform/config.py

# Verify .env exists with required keys
grep -E '^(SECRET_KEY|JWT_SECRET)=' .env
```
