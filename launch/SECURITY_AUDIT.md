# PalmFi Security Audit Report
**Date:** May 9, 2026  
**Methodology:** Full codebase line-by-line review  
**Files scanned:** 46 Python, 30 HTML templates, Docker config  
**Total findings:** 35 vulnerabilities

---

## 🚨 CRITICAL (7 — Fix Immediately)

| # | File:Line | Issue | Impact | Fix |
|---|-----------|-------|--------|-----|
| C1 | app.py:1232 | **Debug mode enabled in production** (`debug=True`) | Remote code execution via Werkzeug console | `app.run(debug=os.getenv('FLASK_DEBUG','false').lower()=='true')` |
| C2 | config.py:9-20 | **Hardcoded secrets** — weak defaults for SECRET_KEY, JWT_SECRET, ENCRYPTION_KEY, ADMIN_PASSWORD | Full platform compromise | Remove defaults; raise ValueError if env vars missing in prod |
| C3 | app.py:37 | **Weak password hashing** — single SHA-256, no salt | Password reversal in seconds | Use `werkzeug.security.generate_password_hash()` |
| C4 | extended.py:113 | **Path traversal in KYC upload** — file extension not sanitized | Write arbitrary files to filesystem | Use `werkzeug.utils.secure_filename()` + magic byte validation |
| C5 | app.py:767 | **Unauthenticated scoring API** — no login_required on /api/score-application | Information leakage, DoS | Add `@login_required` |
| C6 | app.py:593 | **Unauthenticated rate improvement API** — no auth on /api/rate-improvement/<id> | Loan data enumeration | Add `@admin_required` |
| C7 | extended.py:479 | **Webhook signature bypass** — construct_event() exception silently passed | Forge Stripe events, bypass KYC/payments | Remove outer try/except; always validate signature |

## 🔴 HIGH (10 — Fix This Week)

| # | File:Line | Issue | Impact | Fix |
|---|-----------|-------|--------|-----|
| H1 | app.py:168 | **Mass assignment** — all form fields stored in session blindly | Users inject their own credit score, income | Whitelist allowed application fields |
| H2-H4 | Various templates | **Stored XSS** — user-supplied data in name, address, niches, testimonials | Script execution in admin/borrower browsers | Apply `|e` filter on all dynamic content |
| H5 | extended.py:699 | **Unauthenticated payment API** — /api/create-payment-intent | Anyone can initiate payments | Add `@login_required` + ownership check |
| H6 | extended.py:714 | **Unauthenticated niche API** - internal data enumeration | Information disclosure | Add authentication |
| H7 | app.py:1217 | **Default admin password** falls back to 'admin123' | Brute-force admin access | Force strong password on first run |
| H8 | app.py:705 | **No rate limiting on admin login** | Brute force attacks | Use flask-limiter or account lockout |
| H9 | launch/settings.json | **Secrets stored unencrypted** in world-readable JSON file | All API keys readable if server compromised | Encrypt sensitive values at rest |
| H10 | notifications.py | **PII in console logs** - email body and SMS content printed to stdout | PII leakage | Log metadata only |

## 🟡 MEDIUM (10 — Fix Before Going Live)

| # | Issue | Fix |
|---|-------|-----|
| M1 | **No CSRF protection** on any form — all POST endpoints vulnerable | Flask-WTF CSRFProtect |
| M2 | **No CORS configuration** — any origin can make API calls | Flask-CORS with origin whitelist |
| M3 | **No security headers** — clickjacking, MIME sniffing, no HSTS | Flask-Talisman or custom @after_request |
| M4 | **Session cookie insecure** — no HttpOnly, Secure, SameSite | `SESSION_COOKIE_HTTPONLY=True` + SameSite='Lax' |
| M5 | **JWT not invalidated on logout** — token valid for 24h after logout | JWT blacklist or short-lived tokens + refresh |
| M6 | **24h JWT expiry too long** — no nbf/aud claims | Reduce to 15-60 min; add refresh tokens |
| M7 | **Admin bulk action ID injection** — no ownership validation | Validate IDs exist + belong to valid set |
| M8 | **CSV export formula injection** — names/emails starting with `=` | Sanitize formula prefix characters |
| M9 | **Audit log IP not validated** — accepts IP as parameter | Derive from `request.remote_addr` at call site |
| M10 | **Secrets in docker-compose.yml** | Use env var references + .env file |

## 🟢 LOW (8 — Fix Over Time)

| # | Issue | Fix |
|---|-------|-----|
| L1 | Verbose error messages leak internals | Return generic errors; log details server-side |
| L2 | IDOR on loan detail API | Auth + ownership check |
| L3 | Health endpoint leaks version info | Remove version from public endpoint |
| L4 | System health exposes architecture | Limit info fields |
| L5 | "placeholder" string check is fragile | Check for empty/mock keys differently |
| L6 | CDN resources without SRI | Add integrity hashes to script/link tags |
| L7 | No MAX_CONTENT_LENGTH on Flask app | `app.config['MAX_CONTENT_LENGTH'] = 16MB` |
| L8 | No HTTP→HTTPS redirect | Flask-Talisman force_https or nginx redirect |

---

## Immediate Action Plan

```
Priority 1 (30 min):
  □ Disable debug mode in app.py:1232
  □ Replace SHA-256 password hashing with bcrypt
  □ Remove hardcoded secret defaults from config.py
  □ Add @login_required to /api/score-application

Priority 2 (1 hr):
  □ Add CSRF protection via Flask-WTF
  □ Fix path traversal in KYC upload (secure_filename)
  □ Add rate limiting to admin login
  □ Remove default admin123 password fallback

Priority 3 (2 hr):
  □ Add security headers (Flask-Talisman)
  □ Configure session cookie flags
  □ Fix webhook signature verification
  □ Add CORS configuration
```
