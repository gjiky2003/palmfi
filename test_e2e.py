#!/usr/bin/env python3
"""Comprehensive E2E test suite for PalmFi — no -L flag, checks real responses."""
import subprocess, sys, json, re, os

BASE = "http://localhost:8085"
C = "/tmp/lf_test_cookies.txt"
AC = "/tmp/lf_admin_cookies.txt"
results = {"passed": 0, "failed": 0, "errors": []}

def req(method, path, data=None, cookie=None, json_data=None):
    cmd = ["curl", "-s", "-w", "\n%{http_code}", "-o", "/tmp/lf_resp_body.txt"]
    if cookie:
        cmd += ["-b", cookie, "-c", cookie]
    if method == "POST":
        cmd += ["-X", "POST"]
    if data:
        cmd += ["-d", data]
    if json_data:
        cmd += ["-H", "Content-Type: application/json", "-d", json.dumps(json_data)]
    cmd.append(BASE + path)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        stdout = result.stdout
        lines = stdout.rsplit("\n", 1)
        code = int(lines[1].strip()) if len(lines) == 2 else 0
        body = open("/tmp/lf_resp_body.txt").read() if os.path.exists("/tmp/lf_resp_body.txt") else ""
        return code, body
    except Exception as e:
        return 0, str(e)

def check(name, condition, detail=""):
    if condition:
        results["passed"] += 1
        print(f"  [PASS] {name}")
    else:
        results["failed"] += 1
        results["errors"].append(f"{name}: {detail}")
        print(f"  [FAIL] {name} - {detail}")

print("=" * 60)
print("PalmFi Test Suite v2")
print("=" * 60)

# ── 1. STATIC PAGES ──
print("\n--- 1. Static Pages ---")
for name, url in [("Landing","/"),("Register","/register"),("Login","/login"),
                   ("About","/about"),("Terms","/terms"),("Admin Login","/admin/login")]:
    c, b = req("GET", url)
    check(name, c == 200, f"Got {c}")

# ── 2. REGISTRATION ──
print("\n--- 2. Registration ---")
c, b = req("POST", "/register", data="email=alice_unique@test.com&password=pass123&first_name=Alice&last_name=Smith", cookie=C)
check("Register new user (302 or exists 200)", c in (200, 302), f"Got {c}")
c, b = req("POST", "/register", data="email=alice@test.com&password=pass123&first_name=Alice&last_name=Smith")
check("Duplicate email rejected (200 with form)", c == 200, f"Got {c}")
check("Duplicate shows flash msg", "already registered" in b.lower() or "already" in b.lower(), "No flash msg")

# ── 3. AUTH PROTECTED (after register, cookie exists) ──
print("\n--- 3. Auth-protected Pages ---")
for name, url in [("Dashboard","/dashboard"),("KYC","/kyc")]:
    c, b = req("GET", url, cookie=C)
    check(name, c == 200, f"Got {c}")

# ── 4. LOAN APPLICATION ──
print("\n--- 4. Loan Application ---")
# Step 2 - personal
c, b = req("POST", "/apply", data="step=2&age=35&annual_income=65000&employment_length=5&credit_score=720&dti=0.28&utilization=0.2&num_derogatory=0&num_credit_lines=10&home_ownership=rent&employment_status=employed", cookie=C)
check("Step 2 (personal info)", c == 200, f"Got {c}")
# Step 3 - loan
c, b = req("POST", "/apply", data="step=3&loan_amount=10000&loan_purpose=personal&term_months=24", cookie=C)
check("Step 3 (loan details)", c == 200, f"Got {c}")
# Step 4 - review
c, b = req("POST", "/apply", data="step=4", cookie=C)
check("Step 4 (review)", c == 200, f"Got {c}")
# Submit
c, b = req("POST", "/apply", data="submit=1", cookie=C)
check("Submit application (200)", c == 200, f"Got {c}")
check("Decision shows approval", "Congratulations" in b, "Not approved!")
check("Decision shows risk score", "Risk Score" in b, "No risk score display")
check("Decision has tier", "Tier" in b, "No sk Tier")
app_id = re.search(r'value="(\d+)"', b)
check("Has application_id", app_id is not None, "Not found")
APP_ID = app_id.group(1) if app_id else None
print(f"  Application ID: {APP_ID}")

# ── 5. ACCEPT TERMS ──
print("\n--- 5. Accept Terms & Fund ---")
if APP_ID:
    c, b = req("POST", "/accept-terms", data=f"application_id={APP_ID}", cookie=C)
    check("Accept terms (302 redirect)", c == 302, f"Got {c}")

# ── 6. DASHBOARD WITH LOAN ──
print("\n--- 6. Dashboard ---")
c, b = req("GET", "/dashboard", cookie=C)
check("Dashboard loads", c == 200, f"Got {c}")
check("Shows Total Borrowed", "Total Borrowed" in b, "Not found")
check("Shows payment form", "quick-payment" in b.lower() or "make-payment" in b.lower() or "Quick Payment" in b, "Not found")
loan_match = re.search(r'loan/(\d+)', b)
check("Loan ID present", loan_match is not None, "Not found")
LOAN_ID = loan_match.group(1) if loan_match else None
print(f"  Loan ID: {LOAN_ID}")

# ── 7. LOAN DETAIL ──
print("\n--- 7. Loan Detail ---")
if LOAN_ID:
    c, b = req("GET", f"/dashboard/loan/{LOAN_ID}", cookie=C)
    check("Loan detail loads", c == 200, f"Got {c}")
    check("Shows amortization", "Amortization" in b or "payment_number" in b, "No schedule")
    check("Shows payment history", "Payment History" in b, "No history")

# ── 8. PAYMENT ──
print("\n--- 8. Make Payment ---")
if LOAN_ID:
    c, b = req("POST", "/dashboard/make-payment", data=f"loan_id={LOAN_ID}&amount=507.36", cookie=C)
    check("Payment (302 redirect)", c == 302, f"Got {c}")

# ── 9. KYC ──
print("\n--- 9. KYC ---")
c, b = req("GET", "/kyc", cookie=C)
check("KYC loads", c == 200, f"Got {c}")
check("KYC has doc types", "government_id" in b, "Missing government_id")
check("KYC has upload forms", "type=\"file\"" in b or "enctype" in b, "No file upload forms")

# ── 10. ADMIN ──
print("\n--- 10. Admin Routes ---")
c, b = req("POST", "/admin/login", data="email=admin@ailending.com&password=admin123", cookie=AC)
check("Admin POST login (302)", c == 302, f"Got {c}")
for name, url in [("Dashboard","/admin/dashboard"),("Collections","/admin/collections"),("KYC","/admin/kyc")]:
    c, b = req("GET", url, cookie=AC)
    check(f"Admin {name}", c == 200, f"Got {c}")

# ── 11. COLLECTIONS CYCLE ──
print("\n--- 11. Collections Cycle ---")
c, b = req("POST", "/admin/collections/run-cycle", cookie=AC)
check("Run collections (302)", c == 302, f"Got {c}")

# ── 12. ADMIN APPROVE/DECLINE ──
print("\n--- 12. Admin Actions ---")
# Check there are pending apps to test approve/decline
c, b = req("GET", "/admin/dashboard", cookie=AC)
pending_match = re.search(r'/admin/decline/(\d+)', b)
if pending_match:
    did = pending_match.group(1)
    c, b2 = req("POST", f"/admin/decline/{did}", cookie=AC)
    check(f"Decline app #{did} (302)", c == 302, f"Got {c}")

# ── 13. API ──
print("\n--- 13. API ---")
c, b = req("GET", "/api/health")
check("Health API", c == 200, f"Got {c}")
d = json.loads(b) if c == 200 else {}
check("Health status=ok", d.get("status") == "ok", str(d.get("status")))

c, b = req("POST", "/api/score-application", cookie=C, json_data={
    "credit_score":720,"annual_income":65000,"loan_amount":10000,
    "age":35,"employment_length":5,"dti_ratio":0.28,"utilization":0.2,
    "num_derogatory":0,"num_credit_lines":10,"home_ownership":"rent",
    "loan_purpose":"personal"})
check("Score API (200)", c == 200, f"Got {c}")
if c == 200:
    d = json.loads(b)
    check("Score has risk_score", "risk_score" in d, "Missing")
    check("Score has risk_tier", "risk_tier" in d, "Missing")
    check("Score has interest_rate", "interest_rate" in d, "Missing")
    print(f"  Risk {d['risk_score']} -> Tier {d['risk_tier']} -> {d.get('interest_rate','?')}% APR")
    check("Score is approved", d.get("approved", False), "Declined!")

c, b = req("POST", "/api/score-application", cookie=C, json_data={})
check("Score empty (400)", c == 400, f"Got {c}")

# ── SUMMARY ──
total = results["passed"] + results["failed"]
print(f"\n{'='*60}")
print(f"RESULTS: {results['passed']}/{total} passed, {results['failed']} failed")
if results["errors"]:
    print("\nFAILURES:")
    for e in results["errors"]:
        print(f"  - {e}")
print(f"{'='*60}")
sys.exit(0 if results["failed"] == 0 else 1)
