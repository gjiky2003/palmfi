"""Schema migration to add columns autopilot needs."""
import sqlite3, sys, os
DB = os.environ.get("PALMFI_DB", os.path.join(os.path.dirname(__file__), "..", "platform", "palmfi.db"))

ADD_COLUMNS = [
    ("borrowers", "autopay_enabled INTEGER DEFAULT 1"),
    ("applications", "decision_reason TEXT"),
    ("applications", "disbursed_at TIMESTAMP"),
    ("applications", "transfer_id TEXT"),
    ("applications", "contract_signed_at TIMESTAMP"),
    ("applications", "dti_ratio REAL DEFAULT 0.30"),
    ("applications", "prior_defaults INTEGER DEFAULT 0"),
    ("applications", "apr REAL"),
    ("applications", "amount REAL"),  # alias
    ("applications", "tier TEXT"),
    ("loans",        "rate_improved_at TIMESTAMP"),
    ("loans",        "originated_at TIMESTAMP"),
    ("payments",     "amount REAL"),  # alias amount_cents/100
]

def main():
    c = sqlite3.connect(DB)
    for table, coldef in ADD_COLUMNS:
        col = coldef.split()[0]
        cols = [r[1] for r in c.execute(f"PRAGMA table_info({table})").fetchall()]
        if col not in cols:
            c.execute(f"ALTER TABLE {table} ADD COLUMN {coldef}")
            print(f"+ {table}.{col}")
    # Sync alias columns
    c.execute("UPDATE applications SET amount = loan_amount WHERE amount IS NULL AND loan_amount IS NOT NULL")
    c.execute("UPDATE applications SET tier = risk_tier WHERE tier IS NULL AND risk_tier IS NOT NULL")
    c.execute("UPDATE applications SET apr = interest_rate WHERE apr IS NULL AND interest_rate IS NOT NULL")
    c.execute("UPDATE payments SET amount = amount_cents/100.0 WHERE amount IS NULL AND amount_cents IS NOT NULL")
    c.execute("UPDATE loans SET originated_at = disbursed_at WHERE originated_at IS NULL AND disbursed_at IS NOT NULL")
    c.commit()
    print("migration complete")

if __name__ == "__main__":
    main()
