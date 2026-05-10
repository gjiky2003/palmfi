"""Application configuration loaded from environment variables."""
import os
from pathlib import Path

from dotenv import load_dotenv

# Project root = parent of this platform/ directory
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / '.env')


class Config:
    """Application configuration. All secrets MUST come from environment."""

    # ── Required secrets — raises if missing ──
    SECRET_KEY = os.getenv('SECRET_KEY')
    if not SECRET_KEY:
        raise ValueError(
            "SECRET_KEY environment variable is required. "
            "Generate one: python3 -c 'import secrets; print(secrets.token_hex(32))'"
        )

    JWT_SECRET = os.getenv('JWT_SECRET')
    if not JWT_SECRET:
        raise ValueError("JWT_SECRET environment variable is required")

    # ── Database ──
    DATABASE = str(BASE_DIR / 'platform' / 'lending.db')

    # ── Optional: Stripe ──
    STRIPE_SECRET_KEY = os.getenv('STRIPE_SECRET_KEY', '')
    STRIPE_PUBLISHABLE_KEY = os.getenv('STRIPE_PUBLISHABLE_KEY', '')
    STRIPE_WEBHOOK_SECRET = os.getenv('STRIPE_WEBHOOK_SECRET', '')

    # ── Optional: Email/SMS ──
    SENDGRID_API_KEY = os.getenv('SENDGRID_API_KEY', '')
    SENDGRID_FROM_EMAIL = os.getenv('SENDGRID_FROM_EMAIL', 'noreply@ailending.com')
    TWILIO_ACCOUNT_SID = os.getenv('TWILIO_ACCOUNT_SID', '')
    TWILIO_AUTH_TOKEN = os.getenv('TWILIO_AUTH_TOKEN', '')
    TWILIO_FROM_NUMBER = os.getenv('TWILIO_FROM_NUMBER', '')

    # ── Optional: Credit Bureau (Stipula) ──
    STIPULA_API_KEY = os.getenv('STIPULA_API_KEY', '')
    STIPULA_BASE_URL = os.getenv('STIPULA_BASE_URL', 'https://api.stipula.io/v1')

    # ── Optional: Bank Linking (Plaid) ──
    PLAID_CLIENT_ID = os.getenv('PLAID_CLIENT_ID', '')
    PLAID_SECRET = os.getenv('PLAID_SECRET', '')
    PLAID_ENV = os.getenv('PLAID_ENV', 'sandbox')

    # ── Optional: KYC (Persona) ──
    PERSONA_API_KEY = os.getenv('PERSONA_API_KEY', '')
    PERSONA_TEMPLATE_ID = os.getenv('PERSONA_TEMPLATE_ID', '')

    # ── JWT ──
    JWT_ALGORITHM = 'HS256'
    JWT_EXPIRY_HOURS = int(os.getenv('JWT_EXPIRY_HOURS', '168'))  # 7 days

    # ── Encryption / Admin ──
    ENCRYPTION_KEY = os.getenv('ENCRYPTION_KEY', '')
    UNDERWRITING_DIR = str(BASE_DIR / 'underwriting')
    ADMIN_EMAIL = os.getenv('ADMIN_EMAIL', 'admin@ailending.com')
    ADMIN_PASSWORD_HASH = os.getenv('ADMIN_PASSWORD_HASH', '')

    # ── Flask runtime ──
    DEBUG = os.getenv('FLASK_DEBUG', 'false').lower() == 'true'
    HOST = os.getenv('FLASK_HOST', '0.0.0.0')
    PORT = int(os.getenv('FLASK_PORT', os.getenv('PORT', '8085')))

    # ── Security ──
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    SESSION_COOKIE_SECURE = os.getenv('FLASK_HTTPS', 'false').lower() == 'true'
    PERMANENT_SESSION_LIFETIME = 60 * 60 * 24 * 7  # 7 days
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16 MB
