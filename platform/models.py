"""SQLite database models for the lending platform."""
import sqlite3
import json
import os
from config import Config


def get_db():
    """Get a database connection."""
    conn = sqlite3.connect(Config.DATABASE)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """Initialize database tables."""
    conn = get_db()
    cursor = conn.cursor()

    cursor.executescript("""
        CREATE TABLE IF NOT EXISTS borrowers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            first_name TEXT NOT NULL,
            last_name TEXT NOT NULL,
            phone TEXT DEFAULT '',
            date_of_birth TEXT DEFAULT '',
            ssn_last4 TEXT DEFAULT '',
            address TEXT DEFAULT '',
            city TEXT DEFAULT '',
            state TEXT DEFAULT '',
            zip_code TEXT DEFAULT '',
            home_ownership TEXT DEFAULT 'rent',
            employment_status TEXT DEFAULT 'employed',
            employer_name TEXT DEFAULT '',
            employer_phone TEXT DEFAULT '',
            employment_length_months INTEGER DEFAULT 0,
            housing_payment REAL DEFAULT 0,
            annual_income REAL DEFAULT 0,
            credit_score INTEGER DEFAULT 0,
            kyc_status TEXT DEFAULT 'pending',
            stripe_customer_id TEXT DEFAULT '',
            cash_flow_data TEXT DEFAULT '{}',
            cash_flow_score INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_login TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS applications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            borrower_id INTEGER NOT NULL,
            loan_amount REAL NOT NULL DEFAULT 0,
            loan_purpose TEXT DEFAULT 'other',
            term_months INTEGER DEFAULT 36,
            bank_routing TEXT DEFAULT '',
            bank_account TEXT DEFAULT '',
            risk_score INTEGER DEFAULT 0,
            risk_tier TEXT DEFAULT '',
            interest_rate REAL DEFAULT 0,
            monthly_payment REAL DEFAULT 0,
            origination_fee REAL DEFAULT 0,
            status TEXT DEFAULT 'draft',
            decision_explanation TEXT DEFAULT '{}',
            submitted_at TIMESTAMP,
            decided_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (borrower_id) REFERENCES borrowers(id)
        );

        CREATE TABLE IF NOT EXISTS loans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            application_id INTEGER NOT NULL,
            borrower_id INTEGER NOT NULL,
            principal REAL NOT NULL,
            interest_rate REAL NOT NULL,
            term_months INTEGER NOT NULL,
            monthly_payment REAL NOT NULL,
            origination_fee REAL NOT NULL,
            remaining_balance REAL NOT NULL,
            status TEXT DEFAULT 'active',
            disbursed_at TIMESTAMP,
            next_payment_date TEXT,
            paid_off_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (application_id) REFERENCES applications(id),
            FOREIGN KEY (borrower_id) REFERENCES borrowers(id)
        );

        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            loan_id INTEGER NOT NULL,
            borrower_id INTEGER NOT NULL,
            amount_cents INTEGER NOT NULL DEFAULT 0,
            payment_type TEXT DEFAULT 'scheduled',
            status TEXT DEFAULT 'pending',
            due_date TEXT,
            paid_at TIMESTAMP,
            stripe_payment_intent TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (loan_id) REFERENCES loans(id),
            FOREIGN KEY (borrower_id) REFERENCES borrowers(id)
        );

        CREATE TABLE IF NOT EXISTS payment_schedules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            loan_id INTEGER NOT NULL,
            payment_number INTEGER NOT NULL,
            due_date TEXT,
            amount_cents INTEGER NOT NULL DEFAULT 0,
            principal_cents INTEGER NOT NULL DEFAULT 0,
            interest_cents INTEGER NOT NULL DEFAULT 0,
            remaining_balance_cents INTEGER NOT NULL DEFAULT 0,
            status TEXT DEFAULT 'pending',
            FOREIGN KEY (loan_id) REFERENCES loans(id)
        );

        CREATE TABLE IF NOT EXISTS collections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            loan_id INTEGER NOT NULL,
            borrower_id INTEGER NOT NULL,
            collection_stage INTEGER DEFAULT 0,
            days_past_due INTEGER DEFAULT 0,
            action_taken TEXT DEFAULT '',
            communication_channel TEXT DEFAULT '',
            response TEXT DEFAULT '',
            outcome TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (loan_id) REFERENCES loans(id),
            FOREIGN KEY (borrower_id) REFERENCES borrowers(id)
        );

        CREATE TABLE IF NOT EXISTS audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action_type TEXT NOT NULL,
            borrower_id INTEGER DEFAULT 0,
            actor TEXT DEFAULT 'system',
            details TEXT DEFAULT '{}',
            ip_address TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS kyc_documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            borrower_id INTEGER NOT NULL,
            document_type TEXT NOT NULL,
            file_path TEXT DEFAULT '',
            verification_status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (borrower_id) REFERENCES borrowers(id)
        );

        CREATE TABLE IF NOT EXISTS auto_pay (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            borrower_id INTEGER NOT NULL,
            loan_id INTEGER NOT NULL,
            payment_method_id TEXT DEFAULT '',
            active INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (borrower_id) REFERENCES borrowers(id),
            FOREIGN KEY (loan_id) REFERENCES loans(id)
        );

        CREATE TABLE IF NOT EXISTS payment_methods (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            borrower_id INTEGER NOT NULL,
            stripe_payment_method_id TEXT NOT NULL,
            card_last4 TEXT DEFAULT '',
            card_brand TEXT DEFAULT '',
            exp_month INTEGER DEFAULT 0,
            exp_year INTEGER DEFAULT 0,
            is_default INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (borrower_id) REFERENCES borrowers(id)
        );

        CREATE TABLE IF NOT EXISTS admin_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    conn.commit()
    conn.close()


def audit_log(action_type, borrower_id=0, actor='system', details=None, ip_address=''):
    """Add an entry to the audit log."""
    try:
        conn = get_db()
        conn.execute(
            "INSERT INTO audit_logs (action_type, borrower_id, actor, details, ip_address) "
            "VALUES (?, ?, ?, ?, ?)",
            (action_type, borrower_id, actor, json.dumps(details or {}), ip_address)
        )
        conn.commit()
        conn.close()
    except Exception:
        pass
