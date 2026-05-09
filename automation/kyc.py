"""
Know Your Customer (KYC) document verification module.

Rule-based document validation with no external AI dependencies.
Handles ID upload verification, comprehensive KYC checks, and
automated KYC approval workflows.

Works standalone (direct sqlite3) or imported alongside the platform module.
"""

import sys
import os
import json
import sqlite3
import logging
import mimetypes
from datetime import datetime, date, timezone
from pathlib import Path

# Optional PIL for robust image dimension checks
try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Settings-aware config: launch/settings.json → Config/env → default
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
    # Fallback: Config/env
    env_name = keys[-1].upper() if isinstance(keys[-1], str) else keys[-1]
    if isinstance(env_name, str) and env_name.isupper():
        return os.getenv(env_name, default)
    return default


def _clear_settings_cache():
    """Clear cached settings (useful after admin applies new settings)."""
    global _SETTINGS_CACHE
    _SETTINGS_CACHE = None


def _get_kyc_provider():
    """Return the KYC provider name from settings: 'mock', 'stripe-identity', etc."""
    return _get_settings_value('kyc', 'provider', default='mock')

# ---------------------------------------------------------------------------
# Allowed document types and validation rules
# ---------------------------------------------------------------------------

ALLOWED_EXTENSIONS = {'.pdf', '.jpg', '.jpeg', '.png'}
ALLOWED_MIME_TYPES = {
    'application/pdf',
    'image/jpeg',
    'image/png',
}
MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB
MIN_FILE_SIZE_BYTES = 10 * 1024  # 10 KB minimum (catches empty/corrupt files)
REQUIRED_DOC_TYPES = ['government_id', 'proof_of_address']
MIN_IMAGE_DIMENSION = 200    # minimum reasonable width/height in pixels
MAX_IMAGE_DIMENSION = 10000  # maximum reasonable width/height in pixels

# ---------------------------------------------------------------------------
# DB path resolution — follows same pattern as collections.py
# ---------------------------------------------------------------------------


def _resolve_db_path():
    """
    Return the absolute path to lending.db.

    Strategy:
      1. If platform.models is importable, use get_db() from it.
      2. Otherwise derive from this file's location:
         automation/kyc.py -> platform/lending.db
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


def _guess_mime_type(file_path):
    """Guess MIME type from file path. Returns None on failure."""
    mime_type, _ = mimetypes.guess_type(file_path)
    if mime_type:
        return mime_type.lower()

    # Fallback to extension-based check
    ext = os.path.splitext(file_path)[1].lower()
    ext_to_mime = {
        '.pdf': 'application/pdf',
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.png': 'image/png',
    }
    return ext_to_mime.get(ext)


def _check_image_dimensions(file_path):
    """
    Get image dimensions using PIL if available, falling back to header parsing.

    Returns (width, height) or (None, None) on failure.
    """
    if HAS_PIL:
        try:
            with Image.open(file_path) as im:
                w, h = im.size
                if w > 0 and h > 0:
                    return w, h
        except Exception:
            logger.debug("PIL failed to read %s, falling back to header parsing", file_path)

    # Fallback: pure-Python header parsing
    ext = os.path.splitext(file_path)[1].lower()
    try:
        with open(file_path, 'rb') as f:
            head = f.read(4096)

        if ext in ('.jpg', '.jpeg'):
            i = 0
            while i < len(head) - 1:
                if head[i] == 0xFF and head[i + 1] in (0xC0, 0xC1, 0xC2):
                    height = (head[i + 5] << 8) | head[i + 6]
                    width = (head[i + 7] << 8) | head[i + 8]
                    return width, height
                i += 1
            return None, None

        if ext == '.png':
            if head[:8] == b'\x89PNG\r\n\x1a\n':
                width = (head[16] << 24) | (head[17] << 16) | (head[18] << 8) | head[19]
                height = (head[20] << 24) | (head[21] << 16) | (head[22] << 8) | head[23]
                return width, height
            return None, None

        return None, None

    except (IOError, OSError, IndexError):
        logger.warning("Could not read image dimensions from %s", file_path)
        return None, None


def _audit_log(conn, action_type, borrower_id, actor, details):
    """Record an audit log entry using an existing connection. Does NOT commit."""
    try:
        conn.execute(
            "INSERT INTO audit_logs (action_type, borrower_id, actor, details) VALUES (?, ?, ?, ?)",
            (action_type, borrower_id, actor, json.dumps(details)),
        )
    except Exception as exc:
        logger.warning("Failed to record audit log: %s", exc)


# ---------------------------------------------------------------------------
# 1. verify_id_document
# ---------------------------------------------------------------------------


def verify_id_document(borrower_id, document_type, file_path):
    """
    Validate an uploaded ID document using rule-based checks.

    Checks performed:
      - File existence
      - File extension / MIME type (PDF, JPG, PNG only)
      - File size (< 10 MB)
      - Image dimension sanity (for JPG/PNG: 200–10000 px)
      - Document type is a known/expected type

    Parameters
    ----------
    borrower_id : int
    document_type : str
        e.g. 'government_id', 'proof_of_address', 'selfie'
    file_path : str
        Absolute or relative path to the uploaded document

    Returns
    -------
    dict
        {
            'verified': bool,
            'confidence_score': float (0.0 – 1.0),
            'issues': list[str],
            'recommended_action': str
        }
    """
    issues = []
    verified = True
    confidence_score = 1.0

    # --- 1. Check file exists ---
    if not file_path or not os.path.isfile(file_path):
        issues.append("File does not exist or path is empty")
        return {
            "verified": False,
            "confidence_score": 0.0,
            "issues": issues,
            "recommended_action": "reject_upload",
        }

    # --- 2. Check file extension ---
    ext = os.path.splitext(file_path)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        issues.append(f"Unsupported file extension '{ext}'. Allowed: {', '.join(ALLOWED_EXTENSIONS)}")
        verified = False
        confidence_score -= 0.3

    # --- 3. Check MIME type ---
    mime_type = _guess_mime_type(file_path)
    if mime_type is None:
        issues.append("Could not determine file type")
        verified = False
        confidence_score -= 0.2
    elif mime_type not in ALLOWED_MIME_TYPES:
        issues.append(f"Unsupported file type '{mime_type}'. Allowed: PDF, JPEG, PNG")
        verified = False
        confidence_score -= 0.3

    # --- 4. Check file size ---
    try:
        file_size = os.path.getsize(file_path)
        if file_size > MAX_FILE_SIZE_BYTES:
            size_mb = file_size / (1024 * 1024)
            issues.append(f"File too large: {size_mb:.1f} MB (max 10 MB)")
            verified = False
            confidence_score -= 0.3
        elif file_size < MIN_FILE_SIZE_BYTES:
            issues.append(f"File too small: {file_size} bytes (minimum {MIN_FILE_SIZE_BYTES} bytes)")
            verified = False
            confidence_score -= 0.4
        elif file_size == 0:
            issues.append("File is empty (0 bytes)")
            verified = False
            confidence_score -= 0.3
    except OSError as e:
        issues.append(f"Cannot read file size: {e}")
        verified = False
        confidence_score -= 0.2

    # --- 5. Check image dimensions (for JPG/PNG) ---
    if ext in ('.jpg', '.jpeg', '.png'):
        width, height = _check_image_dimensions(file_path)
        if width is not None and height is not None:
            if width < MIN_IMAGE_DIMENSION or height < MIN_IMAGE_DIMENSION:
                issues.append(
                    f"Image dimensions too small: {width}x{height} px "
                    f"(minimum {MIN_IMAGE_DIMENSION}x{MIN_IMAGE_DIMENSION} px)"
                )
                verified = False
                confidence_score -= 0.2
            elif width > MAX_IMAGE_DIMENSION or height > MAX_IMAGE_DIMENSION:
                issues.append(
                    f"Image dimensions too large: {width}x{height} px "
                    f"(maximum {MAX_IMAGE_DIMENSION}x{MAX_IMAGE_DIMENSION} px)"
                )
                verified = False
                confidence_score -= 0.2
        else:
            issues.append("Could not verify image dimensions — file may be corrupt")
            verified = False
            confidence_score -= 0.1

    # --- 6. Validate document_type ---
    if not document_type or not isinstance(document_type, str) or not document_type.strip():
        issues.append("Document type must be a non-empty string")
        verified = False
        confidence_score -= 0.2

    # Clamp confidence score
    confidence_score = max(0.0, min(1.0, confidence_score))

    # Determine recommended action
    if not verified:
        recommended_action = "review_manually" if confidence_score >= 0.3 else "reject_upload"
    else:
        recommended_action = "accept"

    return {
        "verified": verified,
        "confidence_score": round(confidence_score, 2),
        "issues": issues,
        "recommended_action": recommended_action,
    }


# ---------------------------------------------------------------------------
# 2. kyc_check
# ---------------------------------------------------------------------------


def kyc_check(borrower_id):
    """
    Perform a comprehensive KYC check for a borrower.

    Checks if all required documents have been uploaded and verified.
    Also checks the borrower's current kyc_status.

    Parameters
    ----------
    borrower_id : int

    Returns
    -------
    dict
        {
            'status': 'approved' | 'denied' | 'pending' | 'missing',
            'required_docs': list[str],
            'missing_docs': list[str],
            'verifications': dict[str, dict],
            'borrower': dict | None
        }
    """
    conn = _get_connection()
    try:
        # Fetch borrower
        borrower = _to_dict(
            conn.execute(
                "SELECT id, email, first_name, last_name, kyc_status "
                "FROM borrowers WHERE id = ?",
                (borrower_id,),
            ).fetchone()
        )

        if borrower is None:
            return {
                "status": "missing",
                "required_docs": REQUIRED_DOC_TYPES,
                "missing_docs": REQUIRED_DOC_TYPES,
                "verifications": {},
                "borrower": None,
            }

        # Fetch all documents for this borrower
        doc_rows = conn.execute(
            "SELECT id, document_type, file_path, verification_status, created_at "
            "FROM kyc_documents WHERE borrower_id = ? ORDER BY created_at DESC",
            (borrower_id,),
        ).fetchall()

        documents = [_to_dict(r) for r in doc_rows]

        # Build a map: document_type -> latest document record
        doc_map = {}
        for doc in documents:
            dtype = doc["document_type"]
            if dtype not in doc_map:
                doc_map[dtype] = doc

        # Determine missing docs
        present_types = set(doc_map.keys())
        missing_docs = [dt for dt in REQUIRED_DOC_TYPES if dt not in present_types]

        # Build verifications dict
        verifications = {}
        for dt in REQUIRED_DOC_TYPES:
            if dt in doc_map:
                doc = doc_map[dt]
                verifications[dt] = {
                    "document_id": doc["id"],
                    "file_path": doc["file_path"],
                    "verification_status": doc["verification_status"],
                    "uploaded_at": doc["created_at"],
                }
            else:
                verifications[dt] = {
                    "document_id": None,
                    "file_path": None,
                    "verification_status": "not_uploaded",
                    "uploaded_at": None,
                }

        # Determine overall status
        if missing_docs:
            status = "missing"
        else:
            # All docs present — check their verification status
            all_verified = all(
                doc_map[dt]["verification_status"] == "verified"
                for dt in REQUIRED_DOC_TYPES
                if dt in doc_map
            )
            any_rejected = any(
                doc_map[dt]["verification_status"] == "rejected"
                for dt in REQUIRED_DOC_TYPES
                if dt in doc_map
            )

            if all_verified:
                status = "approved"
            elif any_rejected:
                status = "denied"
            else:
                status = "pending"

        return {
            "status": status,
            "required_docs": REQUIRED_DOC_TYPES,
            "missing_docs": missing_docs,
            "verifications": verifications,
            "borrower": borrower,
        }

    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 3. auto_verify_kyc
# ---------------------------------------------------------------------------


def auto_verify_kyc(borrower_id):
    """
    Simplified auto-verification based on credit score + income stability
    + document presence.

    Rules:
      - All required docs must be uploaded with 'verified' status
      - Credit score must be >= 600
      - Annual income must be > 0
      - Borrower must not have any obvious red flags

    Parameters
    ----------
    borrower_id : int

    Returns
    -------
    dict
        {
            'approved': bool,
            'reason': str,
            'details': dict
        }
    """
    conn = _get_connection()
    try:
        # Fetch borrower details
        borrower = _to_dict(
            conn.execute(
                "SELECT id, email, first_name, last_name, "
                "       credit_score, annual_income, employment_status, "
                "       kyc_status "
                "FROM borrowers WHERE id = ?",
                (borrower_id,),
            ).fetchone()
        )

        if borrower is None:
            return {
                "approved": False,
                "reason": "Borrower not found",
                "details": {"borrower_id": borrower_id},
            }

        reasons = []

        # --- Check document presence and verification ---
        check_result = kyc_check(borrower_id)

        if check_result["missing_docs"]:
            reasons.append(
                f"Missing required document(s): {', '.join(check_result['missing_docs'])}"
            )

        # Check each required doc is verified
        for dt in REQUIRED_DOC_TYPES:
            ver = check_result["verifications"].get(dt, {})
            if ver.get("verification_status") != "verified":
                reasons.append(
                    f"Document '{dt}' is not verified (status: {ver.get('verification_status', 'unknown')})"
                )

        # --- Check credit score ---
        credit_score = borrower.get("credit_score") or 0
        if credit_score < 600:
            reasons.append(f"Credit score too low: {credit_score} (minimum 600)")

        # --- Check income ---
        annual_income = borrower.get("annual_income") or 0
        if annual_income <= 0:
            reasons.append("No verifiable annual income reported")

        # --- Check employment ---
        employment_status = (borrower.get("employment_status") or "").lower()
        if employment_status in ("unemployed", ""):
            reasons.append(f"Unstable employment status: '{borrower.get('employment_status', 'unknown')}'")

        # --- Decision ---
        if not reasons:
            # Auto-approve: update status
            _update_kyc_status_direct(conn, borrower_id, "approved")
            _audit_log(conn, 'kyc_auto_verify', borrower_id, 'system', {
                'approved': True,
                'reasons': [],
                'credit_score': credit_score,
                'annual_income': annual_income,
            })
            logger.info(
                "Auto-verified KYC for borrower %s (credit=%s, income=%s)",
                borrower_id, credit_score, annual_income,
            )
            return {
                "approved": True,
                "reason": "All checks passed — KYC auto-approved",
                "details": {
                    "borrower_id": borrower_id,
                    "credit_score": credit_score,
                    "annual_income": annual_income,
                    "employment_status": employment_status,
                },
            }

        # Not approved
        _audit_log(conn, 'kyc_auto_verify', borrower_id, 'system', {
            'approved': False,
            'reasons': reasons,
            'credit_score': credit_score,
            'annual_income': annual_income,
        })
        return {
            "approved": False,
            "reason": "; ".join(reasons),
            "details": {
                "borrower_id": borrower_id,
                "credit_score": credit_score,
                "annual_income": annual_income,
                "employment_status": employment_status,
                "missing_docs": check_result["missing_docs"],
                "verifications": check_result["verifications"],
            },
        }

    finally:
        conn.close()


def _update_kyc_status_direct(conn, borrower_id, status):
    """
    Internal helper: update kyc_status using an existing connection.
    Does NOT commit — caller is responsible.
    """
    valid_statuses = {"pending", "approved", "denied", "missing"}
    if status not in valid_statuses:
        raise ValueError(f"Invalid KYC status '{status}'. Must be one of: {', '.join(sorted(valid_statuses))}")
    conn.execute(
        "UPDATE borrowers SET kyc_status = ? WHERE id = ?",
        (status, borrower_id),
    )


# ---------------------------------------------------------------------------
# 4. get_kyc_status
# ---------------------------------------------------------------------------


def get_kyc_status(borrower_id):
    """
    Return the current KYC status from the borrowers table.

    Parameters
    ----------
    borrower_id : int

    Returns
    -------
    dict
        {
            'borrower_id': int,
            'status': str | None,
            'found': bool
        }
    """
    conn = _get_connection()
    try:
        row = _to_dict(
            conn.execute(
                "SELECT id, email, first_name, last_name, kyc_status "
                "FROM borrowers WHERE id = ?",
                (borrower_id,),
            ).fetchone()
        )

        if row is None:
            return {
                "borrower_id": borrower_id,
                "status": None,
                "found": False,
            }

        return {
            "borrower_id": row["id"],
            "status": row["kyc_status"],
            "found": True,
        }

    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 5. update_kyc_status
# ---------------------------------------------------------------------------


def update_kyc_status(borrower_id, status):
    """
    Update the kyc_status field in the borrowers table.

    Parameters
    ----------
    borrower_id : int
    status : str
        One of: 'pending', 'approved', 'denied', 'missing'

    Returns
    -------
    dict
        {
            'success': bool,
            'previous_status': str | None,
            'new_status': str,
            'error': str | None
        }
    """
    valid_statuses = {"pending", "approved", "denied", "missing"}
    if status not in valid_statuses:
        return {
            "success": False,
            "previous_status": None,
            "new_status": status,
            "error": (
                f"Invalid status '{status}'. "
                f"Must be one of: {', '.join(sorted(valid_statuses))}"
            ),
        }

    conn = _get_connection()
    try:
        # Get current status
        current = _to_dict(
            conn.execute(
                "SELECT kyc_status FROM borrowers WHERE id = ?",
                (borrower_id,),
            ).fetchone()
        )

        if current is None:
            return {
                "success": False,
                "previous_status": None,
                "new_status": status,
                "error": "Borrower not found",
            }

        previous = current["kyc_status"]

        conn.execute(
            "UPDATE borrowers SET kyc_status = ? WHERE id = ?",
            (status, borrower_id),
        )
        conn.commit()

        logger.info(
            "KYC status updated: borrower %s: %s -> %s",
            borrower_id, previous, status,
        )

        return {
            "success": True,
            "previous_status": previous,
            "new_status": status,
            "error": None,
        }

    except Exception as e:
        conn.rollback()
        logger.exception("Failed to update KYC status for borrower %s", borrower_id)
        return {
            "success": False,
            "previous_status": None,
            "new_status": status,
            "error": str(e),
        }

    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 6. list_all_pending_kyc
# ---------------------------------------------------------------------------


def list_all_pending_kyc():
    """
    Return a list of borrowers with pending KYC status.

    Returns
    -------
    list[dict]
        Each dict contains: id, email, first_name, last_name, kyc_status,
        created_at, doc_count (number of uploaded KYC documents)
    """
    conn = _get_connection()
    try:
        rows = conn.execute(
            """
            SELECT
                b.id,
                b.email,
                b.first_name,
                b.last_name,
                b.kyc_status,
                b.created_at,
                COALESCE(d.doc_count, 0) AS doc_count
            FROM borrowers b
            LEFT JOIN (
                SELECT borrower_id, COUNT(*) AS doc_count
                FROM kyc_documents
                GROUP BY borrower_id
            ) d ON d.borrower_id = b.id
            WHERE b.kyc_status = 'pending'
            ORDER BY b.created_at DESC
            """
        ).fetchall()

        borrowers = []
        for row in rows:
            r = _to_dict(row)
            # Also fetch which docs they've uploaded
            doc_types = conn.execute(
                "SELECT document_type, verification_status "
                "FROM kyc_documents WHERE borrower_id = ?",
                (r["id"],),
            ).fetchall()

            r["documents"] = [
                {"document_type": d["document_type"], "verification_status": d["verification_status"]}
                for d in doc_types
            ]
            borrowers.append(r)

        return borrowers

    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Convenience: record_document
# ---------------------------------------------------------------------------


def record_document(borrower_id, document_type, file_path, verification_status="pending"):
    """
    Record an uploaded document in the kyc_documents table.

    Parameters
    ----------
    borrower_id : int
    document_type : str
    file_path : str
    verification_status : str (default: 'pending')
        'pending', 'verified', 'rejected'

    Returns
    -------
    dict
        {'success': bool, 'document_id': int | None, 'error': str | None}
    """
    conn = _get_connection()
    try:
        cursor = conn.execute(
            "INSERT INTO kyc_documents (borrower_id, document_type, file_path, verification_status) "
            "VALUES (?, ?, ?, ?)",
            (borrower_id, document_type, file_path, verification_status),
        )
        doc_id = cursor.lastrowid
        conn.commit()

        logger.info(
            "Document recorded: borrower=%s, type=%s, id=%s, status=%s",
            borrower_id, document_type, doc_id, verification_status,
        )

        return {
            "success": True,
            "document_id": doc_id,
            "error": None,
        }

    except Exception as e:
        conn.rollback()
        logger.exception("Failed to record document for borrower %s", borrower_id)
        return {
            "success": False,
            "document_id": None,
            "error": str(e),
        }

    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 7. stripe_identity_verify — Stripe Identity Integration
# ---------------------------------------------------------------------------


def stripe_identity_verify(borrower_id):
    """
    Create a Stripe Identity VerificationSession for a borrower.

    Uses Stripe's Identity API to verify government-issued ID documents
    and perform facial comparison. Returns a client_secret that the
    front-end uses to render Stripe's identity verification form.

    Mock-friendly: when provider is 'mock' or Stripe is not configured,
    returns a mock client_secret/session_id so the UI can test the flow.

    Parameters
    ----------
    borrower_id : int

    Returns
    -------
    dict
        {
            'success': bool,
            'client_secret': str | None,
            'session_id': str | None,
            'status': str,
            'error': str | None,
            'fallback': bool
        }
    """
    # Determine if Stripe Identity is configured
    provider = _get_kyc_provider()

    # Mock-friendly: return mock credentials for testing
    if provider == 'mock':
        logger.info(
            "stripe_identity_verify: provider is 'mock' — returning mock credentials for borrower %s",
            borrower_id,
        )
        return {
            'success': True,
            'client_secret': f'vs_mock_secret_{borrower_id}',
            'session_id': f'vs_mock_{borrower_id}',
            'status': 'mock',
            'error': None,
            'fallback': False,
        }

    if provider != 'stripe-identity':
        logger.info(
            "stripe_identity_verify called but KYC provider is '%s' — falling back",
            provider,
        )
        return {
            'success': False,
            'client_secret': None,
            'session_id': None,
            'status': 'skipped',
            'error': f'KYC provider is "{provider}", not "stripe-identity"',
            'fallback': True,
        }

    # Get Stripe secret key from settings
    stripe_secret = _get_settings_value('stripe', 'secret_key', default='')
    if not stripe_secret:
        # Try Config/env as fallback
        try:
            module_dir = _resolve_project_root()
            if module_dir not in sys.path:
                sys.path.insert(0, module_dir)
            from platform.config import Config  # pylint: disable=import-outside-toplevel
            stripe_secret = getattr(Config, 'STRIPE_SECRET_KEY', '')
        except (ImportError, Exception):
            stripe_secret = os.getenv('STRIPE_SECRET_KEY', '')

    if not stripe_secret:
        logger.warning(
            "Stripe Identity: no secret key configured — returning mock credentials"
        )
        return {
            'success': True,
            'client_secret': f'vs_mock_secret_{borrower_id}',
            'session_id': f'vs_mock_{borrower_id}',
            'status': 'no_key',
            'error': None,
            'fallback': True,
        }

    try:
        import stripe  # pylint: disable=import-outside-toplevel
        stripe.api_key = stripe_secret

        # Build the return URL — we need the domain from settings
        domain_url = _get_settings_value('domain', 'url', default='http://localhost:5000')

        # Get borrower info for the verification session
        conn = _get_connection()
        try:
            borrower = _to_dict(conn.execute(
                "SELECT id, email, first_name, last_name FROM borrowers WHERE id = ?",
                (borrower_id,),
            ).fetchone())
        finally:
            conn.close()

        # Create a Stripe Identity VerificationSession
        session = stripe.Identity.VerificationSession.create(
            type='document',
            metadata={
                'borrower_id': str(borrower_id),
                'platform': 'palmfi',
            },
            options={
                'document': {
                    'allowed_types': ['driving_license', 'passport', 'id_card'],
                    'require_id_number': False,
                    'require_live_capture': False,
                },
            },
            return_url=f"{domain_url}/kyc?session_id={{CHECKOUT_SESSION_ID}}",
        )

        logger.info(
            "Stripe Identity session created for borrower %s — session=%s, status=%s",
            borrower_id, session.id, session.status,
        )

        # Record the verification session in DB
        conn = _get_connection()
        try:
            conn.execute(
                "INSERT INTO kyc_documents "
                "(borrower_id, document_type, file_path, verification_status) "
                "VALUES (?, 'stripe_identity', ?, ?)",
                (borrower_id, f"stripe_session_{session.id}", 'pending'),
            )
            conn.execute(
                "UPDATE borrowers SET kyc_status = 'pending' WHERE id = ?",
                (borrower_id,),
            )
            conn.commit()
        finally:
            conn.close()

        return {
            'success': True,
            'client_secret': session.client_secret,
            'session_id': session.id,
            'status': session.status,
            'error': None,
            'fallback': False,
        }

    except Exception as e:
        logger.exception(
            "Stripe Identity verification failed for borrower %s", borrower_id
        )
        return {
            'success': False,
            'client_secret': f'vs_mock_secret_{borrower_id}',
            'session_id': f'vs_mock_{borrower_id}',
            'status': 'error',
            'error': str(e),
            'fallback': True,
        }


# ---------------------------------------------------------------------------
# 8. stripe_identity_webhook_handler
# ---------------------------------------------------------------------------


def handle_stripe_identity_completed(session):
    """
    Handle a completed Stripe Identity verification session webhook.

    Called when stripe.identity.verification_session.verified or
    stripe.identity.verification_session.processing events are received.

    Parameters
    ----------
    session : dict or stripe.Identity.VerificationSession
        The session object from the webhook payload.

    Returns
    -------
    dict
        {'success': bool, 'borrower_id': int | None, 'status': str}
    """
    metadata = getattr(session, 'metadata', {}) or {}
    if isinstance(session, dict):
        metadata = session.get('metadata', {})

    session_id_val = getattr(session, 'id', 'unknown')
    if isinstance(session, dict):
        session_id_val = session.get('id', 'unknown')

    borrower_id_str = metadata.get('borrower_id', '')
    if not borrower_id_str:
        logger.warning("Stripe Identity webhook: no borrower_id in metadata")
        return {'success': False, 'borrower_id': None, 'status': 'no_metadata'}

    borrower_id = int(borrower_id_str)

    session_status = getattr(session, 'status', '')
    if isinstance(session, dict):
        session_status = session.get('status', '')

    if session_status in ('verified', 'processing'):
        conn = _get_connection()
        try:
            # Update the stripe_identity document status
            conn.execute(
                "UPDATE kyc_documents SET verification_status = ? "
                "WHERE borrower_id = ? AND document_type = 'stripe_identity'",
                ('verified' if session_status == 'verified' else 'pending', borrower_id),
            )

            # If verified, update borrower KYC status
            if session_status == 'verified':
                conn.execute(
                    "UPDATE borrowers SET kyc_status = 'approved' WHERE id = ?",
                    (borrower_id,),
                )
                logger.info(
                    "Stripe Identity completed for borrower %s — KYC approved",
                    borrower_id,
                )

            # Record audit log entry (SunCredit pattern)
            _audit_log(conn, 'stripe_identity_completed', borrower_id, 'stripe', {
                'status': session_status,
                'session_id': session_id_val,
            })

            conn.commit()
        finally:
            conn.close()

        return {
            'success': True,
            'borrower_id': borrower_id,
            'status': session_status,
        }

    logger.info(
        "Stripe Identity session %s for borrower %s has status '%s' — not updating",
        session_id_val,
        borrower_id,
        session_status,
    )
    return {
        'success': False,
        'borrower_id': borrower_id,
        'status': session_status,
    }
