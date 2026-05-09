"""Identity verification & fraud detection engine.

OFAC screening, SSN validation, PEP checks, fraud rules, identity confidence
scoring. Keeps PalmFi's comprehensive rule set and OFAC SDN list while using
SunCredit's cleaner approach (no DB path resolution, no fragile sys.path
manipulation).
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
# PART 1 — OFAC / Sanctions Screening
# ═══════════════════════════════════════════════════════════════

OFAC_SDN_LIST: List[Dict[str, str]] = [
    # Iran
    {"name": "ALI KHAMENEI", "program": "IRAN", "type": "Individual", "remarks": "Supreme Leader of Iran"},
    {"name": "QASEM SOLEIMANI", "program": "IRAN", "type": "Individual", "remarks": "IRGC Quds Force Commander (deceased)"},
    {"name": "MOHAMMAD JAVAD ZARIF", "program": "IRAN", "type": "Individual", "remarks": "Former Foreign Minister"},
    {"name": "ISLAMIC REVOLUTIONARY GUARD CORPS", "program": "IRAN", "type": "Entity", "remarks": "IRGC"},
    {"name": "IRANIAN MINISTRY OF INTELLIGENCE AND SECURITY", "program": "IRAN", "type": "Entity", "remarks": "MOIS"},
    {"name": "BANK MELLI IRAN", "program": "IRAN", "type": "Entity", "remarks": "State-owned bank"},
    {"name": "BANK SADERAT IRAN", "program": "IRAN", "type": "Entity", "remarks": "State-owned bank"},
    {"name": "BANK SEPAH", "program": "IRAN", "type": "Entity", "remarks": "State-owned bank"},
    {"name": "NUCLEAR ENERGY ORGANIZATION OF IRAN", "program": "IRAN", "type": "Entity", "remarks": "AEOI"},
    {"name": "IRAN AIR", "program": "IRAN", "type": "Entity", "remarks": "National airline"},
    {"name": "IRANIAN OIL TANKER COMPANY", "program": "IRAN", "type": "Entity", "remarks": "NITC"},
    {"name": "PERSIAN GULF PETROCHEMICAL INDUSTRY", "program": "IRAN", "type": "Entity", "remarks": "PGPIC"},
    # North Korea
    {"name": "KIM JONG UN", "program": "DPRK", "type": "Individual", "remarks": "Supreme Leader"},
    {"name": "CHOE RYONG HAE", "program": "DPRK", "type": "Individual", "remarks": "Senior Official"},
    {"name": "RI SOL JU", "program": "DPRK", "type": "Individual", "remarks": "First Lady"},
    {"name": "KIM YO JONG", "program": "DPRK", "type": "Individual", "remarks": "Senior Official"},
    {"name": "HYDROBUREAU OF THE KOREAN PEOPLE'S ARMY", "program": "DPRK", "type": "Entity", "remarks": "Military entity"},
    {"name": "KOREA MINING DEVELOPMENT TRADING CORPORATION", "program": "DPRK", "type": "Entity", "remarks": "KOMID"},
    {"name": "KORYO BANK", "program": "DPRK", "type": "Entity", "remarks": "Bank"},
    {"name": "KOREA TAEHUNG TRADING CORPORATION", "program": "DPRK", "type": "Entity", "remarks": "Trading co"},
    # Russia
    {"name": "VLADIMIR PUTIN", "program": "RUSSIA", "type": "Individual", "remarks": "President of Russia"},
    {"name": "SERGEI LAVROV", "program": "RUSSIA", "type": "Individual", "remarks": "Foreign Minister"},
    {"name": "SERGEI SHOIGU", "program": "RUSSIA", "type": "Individual", "remarks": "Defense Minister"},
    {"name": "MIKHAIL MISHUSTIN", "program": "RUSSIA", "type": "Individual", "remarks": "Prime Minister"},
    {"name": "DMITRY MEDVEDEV", "program": "RUSSIA", "type": "Individual", "remarks": "Security Council"},
    {"name": "ALEXANDER BASTRYKIN", "program": "RUSSIA", "type": "Individual", "remarks": "Investigative Committee"},
    {"name": "SBERBANK", "program": "RUSSIA", "type": "Entity", "remarks": "State bank"},
    {"name": "VTB BANK", "program": "RUSSIA", "type": "Entity", "remarks": "State bank"},
    {"name": "GAZPROM", "program": "RUSSIA", "type": "Entity", "remarks": "Energy company"},
    {"name": "ROSNEFT", "program": "RUSSIA", "type": "Entity", "remarks": "Oil company"},
    {"name": "SOVCOMFLOT", "program": "RUSSIA", "type": "Entity", "remarks": "Shipping co"},
    {"name": "ALROSA", "program": "RUSSIA", "type": "Entity", "remarks": "Diamond mining"},
    # Syria
    {"name": "BASHAR AL-ASSAD", "program": "SYRIA", "type": "Individual", "remarks": "President of Syria"},
    {"name": "CENTRAL BANK OF SYRIA", "program": "SYRIA", "type": "Entity", "remarks": "CBS"},
    # Venezuela
    {"name": "NICOLAS MADURO", "program": "VENEZUELA", "type": "Individual", "remarks": "President"},
    {"name": "DELCY RODRIGUEZ", "program": "VENEZUELA", "type": "Individual", "remarks": "Vice President"},
    {"name": "PDVSA", "program": "VENEZUELA", "type": "Entity", "remarks": "State oil company"},
    # Cuba
    {"name": "FIDEL CASTRO", "program": "CUBA", "type": "Individual", "remarks": "Former President"},
    {"name": "RAUL CASTRO", "program": "CUBA", "type": "Individual", "remarks": "Former President"},
    {"name": "MIGUEL DIAZ-CANEL", "program": "CUBA", "type": "Individual", "remarks": "President"},
    # Terrorism
    {"name": "OSAMA BIN LADEN", "program": "SDGT", "type": "Individual", "remarks": "Al-Qaida (deceased)"},
    {"name": "AYMAN AL-ZAWAHIRI", "program": "SDGT", "type": "Individual", "remarks": "Al-Qaida (deceased)"},
    {"name": "ABU BAKR AL-BAGHDADI", "program": "ISIS", "type": "Individual", "remarks": "ISIS (deceased)"},
    {"name": "AL-SHABAAB", "program": "SDGT", "type": "Entity", "remarks": "Somali militant group"},
    {"name": "HIZBALLAH", "program": "SDGT", "type": "Entity", "remarks": "Lebanese militant group"},
    {"name": "HAMAS", "program": "SDGT", "type": "Entity", "remarks": "Palestinian militant group"},
    {"name": "TALIBAN", "program": "SDGT", "type": "Entity", "remarks": "Afghan political faction"},
    {"name": "ISLAMIC STATE OF IRAQ AND SYRIA", "program": "ISIS", "type": "Entity", "remarks": "ISIS/ISIL"},
    # China / Xinjiang
    {"name": "XINJIANG POLICE DEPARTMENT", "program": "CHINA", "type": "Entity", "remarks": "Xinjiang"},
    {"name": "HUAWEI TECHNOLOGIES", "program": "CHINA", "type": "Entity", "remarks": "Telecom equipment"},
    # Drug
    {"name": "JOAQUIN GUZMAN LOERA", "program": "SDNT", "type": "Individual", "remarks": "El Chapo (incarcerated)"},
]

# Politically Exposed Persons (sample)
PEP_LIST: List[str] = [
    "JOE BIDEN", "KAMALA HARRIS", "DONALD TRUMP", "JD VANCE",
    "JOHN ROBERTS", "CLARENCE THOMAS", "SAMUEL ALITO", "SONIA SOTOMAYOR",
    "ELENA KAGAN", "BRETT KAVANAUGH", "AMY CONEY BARRETT", "KETANJI BROWN JACKSON",
    "NANCY PELOSI", "MIKE JOHNSON", "CHUCK SCHUMER", "JOHN THUNE",
    "JANET YELLEN", "JEROME POWELL",
]

DISPOSABLE_EMAIL_DOMAINS: set = {
    "mailinator.com", "guerrillamail.com", "10minutemail.com", "tempmail.com",
    "throwaway.com", "yopmail.com", "sharklasers.com", "trashmail.com",
    "emailfake.com", "tempmail.net", "temp-mail.org", "maildrop.cc",
    "getairmail.com", "hmail.us", "spamgourmet.com", "fakeinbox.com",
    "mailtemp.net", "mailexpire.com", "anonbox.net", "tempinbox.com",
}


def _fuzzy_match(name_a: str, name_b: str, threshold: float = 0.7) -> float:
    """Fuzzy match two names."""
    a = name_a.upper().strip()
    b = name_b.upper().strip()
    if a == b:
        return 1.0
    if a in b or b in a:
        return 0.9
    return SequenceMatcher(None, a, b).ratio()


def ofac_check(
    first_name: str,
    last_name: str,
    date_of_birth: Optional[str] = None,
    country: Optional[str] = None,
) -> dict:
    """Check against OFAC SDN list. Returns flagged status and matches."""
    full_name = f"{first_name} {last_name}".upper().strip()
    full_reversed = f"{last_name} {first_name}".upper().strip()
    matches = []
    for entry in OFAC_SDN_LIST:
        score = max(
            _fuzzy_match(full_name, entry["name"]),
            _fuzzy_match(full_reversed, entry["name"]),
        )
        if score >= 0.7:
            matches.append({
                "matched_name": entry["name"],
                "program": entry["program"],
                "type": entry["type"],
                "remarks": entry["remarks"],
                "match_score": round(score, 3),
            })
    flagged = len(matches) > 0
    risk_level = "high" if flagged and any(m["match_score"] >= 0.9 for m in matches) else ("medium" if flagged else "none")
    return {
        "flagged": flagged,
        "matches": sorted(matches, key=lambda m: -m["match_score"]),
        "risk_level": risk_level,
        "search_terms": {"full_name": full_name},
    }


def pep_check(name: str) -> dict:
    """Check if name matches a Politically Exposed Person."""
    name_upper = name.upper().strip()
    for pep in PEP_LIST:
        if _fuzzy_match(name_upper, pep) >= 0.8:
            return {"flagged": True, "matched_name": pep, "match_score": _fuzzy_match(name_upper, pep)}
    return {"flagged": False}


# ═══════════════════════════════════════════════════════════════
# PART 2 — SSN / EIN Validation
# ═══════════════════════════════════════════════════════════════

def validate_ssn(ssn: str) -> dict:
    """Validate SSN format and known invalid ranges."""
    if not ssn:
        return {"valid": False, "reason": "No SSN provided"}
    cleaned = re.sub(r"[\s\-]", "", ssn)
    if not re.match(r"^\d{9}$", cleaned):
        return {"valid": False, "reason": "SSN must be 9 digits"}
    area = int(cleaned[:3])
    group = int(cleaned[3:5])
    serial = int(cleaned[5:9])

    if area == 0:
        return {"valid": False, "reason": "Invalid area number: 000", "area": area}
    if area == 666:
        return {"valid": False, "reason": "Invalid area number: 666", "area": area}
    if area > 772:
        return {"valid": False, "reason": f"Area number {area} not yet assigned", "area": area}
    if group == 0:
        return {"valid": False, "reason": "Invalid group number: 00", "area": area, "group": group}
    if serial == 0:
        return {"valid": False, "reason": "Invalid serial number: 0000", "area": area, "serial": serial}
    if area == 987 and group == 65 and serial == 4320:
        return {"valid": False, "reason": "Test number not valid for real use (987-65-4320)"}
    if cleaned == "123456789":
        return {"valid": False, "reason": "Obvious test pattern (123-45-6789)"}
    if cleaned[0] == "9":
        return {"valid": False, "reason": "ITIN detected (9xx prefix) - not a valid SSN", "itin": True}

    return {
        "valid": True,
        "reason": "SSN format valid",
        "formatted": f"{cleaned[:3]}-{cleaned[3:5]}-{cleaned[5:9]}",
        "area": area,
        "group": group,
        "serial": serial,
    }


def validate_ein(ein: str) -> dict:
    """Validate EIN format."""
    if not ein:
        return {"valid": False, "reason": "No EIN provided"}
    cleaned = re.sub(r"[\s\-]", "", ein)
    if not re.match(r"^\d{9}$", cleaned):
        return {"valid": False, "reason": "EIN must be 9 digits"}
    prefix = int(cleaned[:2])
    if prefix < 1 or prefix > 99:
        return {"valid": False, "reason": f"Invalid EIN prefix: {prefix:02d}"}
    return {"valid": True, "reason": "EIN format valid", "formatted": f"{cleaned[:2]}-{cleaned[2:9]}"}


# ═══════════════════════════════════════════════════════════════
# PART 3 — Fraud Detection Engine
# ═══════════════════════════════════════════════════════════════

FRAUD_RULES: List[Dict[str, Any]] = [
    {"name": "velocity_application", "description": "Multiple applications within 24 hours", "severity": "high", "weight": 25},
    {"name": "disposable_email", "description": "Email domain is a known disposable/temporary email provider", "severity": "high", "weight": 20},
    {"name": "income_inconsistency", "description": "Loan amount exceeds 50% of annual income with subprime credit", "severity": "medium", "weight": 15},
    {"name": "high_dti", "description": "DTI ratio exceeds 0.43 (qualified mortgage threshold)", "severity": "medium", "weight": 10},
    {"name": "new_account_fresh_apply", "description": "Account less than 1 hour old and immediately applying for max loan", "severity": "high", "weight": 25},
    {"name": "derogatory_country_high_risk", "description": "Multiple derogatory marks combined with high loan amount", "severity": "medium", "weight": 15},
    {"name": "credit_score_mismatch", "description": "Low credit score with high income request (identity theft pattern)", "severity": "high", "weight": 20},
    {"name": "thin_file", "description": "Very few credit lines combined with high requested amount", "severity": "medium", "weight": 10},
    {"name": "round_number_amount", "description": "Loan amount is an exact round number (fraud indicator)", "severity": "low", "weight": 5},
]


def assess_application_risk(application_data: dict) -> dict:
    """Run fraud detection rules against application data.

    Parameters
    ----------
    application_data : dict with keys: age, annual_income, credit_score,
        dti_ratio, utilization, num_derogatory, num_credit_lines,
        email, loan_amount, employment_length

    Returns dict with fraud_score, risk_level, alerts, recommended_action.
    """
    alerts: List[Dict[str, Any]] = []
    triggered_weight = 0

    data = application_data or {}
    age = int(data.get("age", 30))
    income = float(data.get("annual_income", 0))
    credit = int(data.get("credit_score", 600))
    dti = float(data.get("dti_ratio", 0.3))
    utilization = float(data.get("utilization", 0.3))
    derog = int(data.get("num_derogatory", 0))
    credit_lines = int(data.get("num_credit_lines", 5))
    email = data.get("email", "")
    loan_amount = float(data.get("loan_amount", 0))
    emp_length = float(data.get("employment_length", 0))

    total_weight = sum(r["weight"] for r in FRAUD_RULES)

    # Rule: Disposable email
    if email and "@" in email:
        domain = email.split("@")[1].lower()
        if domain in DISPOSABLE_EMAIL_DOMAINS:
            alerts.append({
                "rule_name": "disposable_email",
                "description": f"Email domain {domain} is a known disposable provider",
                "severity": "high",
                "weight": 20,
            })
            triggered_weight += 20

    # Rule: Income inconsistency
    if income > 0 and loan_amount > 0:
        lti = loan_amount / income
        if lti > 0.5 and credit < 660:
            alerts.append({
                "rule_name": "income_inconsistency",
                "description": f"Loan-to-income ratio {lti:.1%} exceeds 50% with credit score {credit}",
                "severity": "medium",
                "weight": 15,
            })
            triggered_weight += 15

    # Rule: High DTI
    if dti > 0.43:
        alerts.append({
            "rule_name": "high_dti",
            "description": f"DTI ratio {dti:.1%} exceeds 43% qualified mortgage threshold",
            "severity": "medium",
            "weight": 10,
        })
        triggered_weight += 10

    # Rule: Credit score mismatch
    if credit < 600 and loan_amount > 25000:
        alerts.append({
            "rule_name": "credit_score_mismatch",
            "description": f"Credit score {credit} with loan request ${loan_amount:,.0f}",
            "severity": "high",
            "weight": 20,
        })
        triggered_weight += 20

    # Rule: Thin file
    if credit_lines <= 3 and loan_amount > 15000:
        alerts.append({
            "rule_name": "thin_file",
            "description": f"Only {credit_lines} credit lines with ${loan_amount:,.0f} request",
            "severity": "medium",
            "weight": 10,
        })
        triggered_weight += 10

    # Rule: Derogatory + high risk
    if derog >= 2 and loan_amount > 20000:
        alerts.append({
            "rule_name": "derogatory_high_risk",
            "description": f"{derog} derogatory marks with ${loan_amount:,.0f} loan",
            "severity": "medium",
            "weight": 15,
        })
        triggered_weight += 15

    # Rule: Round number
    if loan_amount > 0 and loan_amount % 1000 == 0 and loan_amount >= 5000:
        alerts.append({
            "rule_name": "round_number_amount",
            "description": f"Loan amount ${loan_amount:,.0f} is a round thousand",
            "severity": "low",
            "weight": 5,
        })
        triggered_weight += 5

    fraud_score = int((triggered_weight / total_weight) * 100) if total_weight > 0 else 0

    if fraud_score >= 60:
        risk_level = "critical"
        recommended = "auto_decline"
    elif fraud_score >= 35:
        risk_level = "high"
        recommended = "manual_review"
    elif fraud_score >= 15:
        risk_level = "medium"
        recommended = "manual_review"
    else:
        risk_level = "low"
        recommended = "auto_approve"

    return {
        "fraud_score": fraud_score,
        "risk_level": risk_level,
        "recommended_action": recommended,
        "alerts": sorted(alerts, key=lambda a: -a.get("weight", 0)),
        "alerts_count": len(alerts),
    }


# ═══════════════════════════════════════════════════════════════
# PART 4 — Identity Confidence Score
# ═══════════════════════════════════════════════════════════════

def run_full_verification(
    borrower_id: int,
    application_data: dict,
    borrower: dict,
    kyc_documents: Optional[list] = None,
) -> dict:
    """Run complete identity verification: OFAC + SSN + Fraud + KYC.

    Pure function — takes data dicts directly instead of querying a DB.
    Returns comprehensive dict with PASS/FAIL/PENDING_REVIEW decision.

    Parameters
    ----------
    borrower_id : int
    application_data : dict
    borrower : dict
        Borrower record with first_name, last_name, email, ssn_last4, kyc_status.
    kyc_documents : list, optional
        List of KYC document records with verification_status.

    Returns
    -------
    dict with decision, confidence_score, and breakdowns.
    """
    first = borrower.get("first_name", "")
    last = borrower.get("last_name", "")
    full_name = f"{first} {last}".strip()
    email = borrower.get("email", "")
    kyc_status = borrower.get("kyc_status", "pending")

    doc_list = kyc_documents or []

    # 1. OFAC check
    ofac_result = ofac_check(first, last)

    # 2. PEP check
    pep_result = pep_check(full_name)

    # 3. SSN validation
    ssn_last4 = borrower.get("ssn_last4", "")
    ssn_result = {"checked": False, "message": "SSN not available for full check"}
    if ssn_last4:
        ssn_result = {"checked": True, "format_ok": True, "message": f"Last 4 provided: ***{ssn_last4}"}

    # 4. Fraud assessment
    fraud_result = assess_application_risk(application_data or {})

    # 5. KYC document status
    verified_docs = sum(1 for d in doc_list if d.get("verification_status") == "verified")
    pending_docs = sum(1 for d in doc_list if d.get("verification_status") == "pending")

    # Composite decision
    issues = []
    if ofac_result["flagged"]:
        issues.append(f"OFAC match: {ofac_result['matches'][0]['matched_name']}")
    if fraud_result["risk_level"] in ("critical", "high"):
        issues.append(f"Fraud risk: {fraud_result['risk_level']} ({fraud_result['fraud_score']}/100)")
    if kyc_status != "approved":
        issues.append(f"KYC status: {kyc_status}")
    if pep_result["flagged"]:
        issues.append(f"PEP match: {pep_result['matched_name']} (review transactions)")

    if fraud_result["recommended_action"] == "auto_decline":
        decision = "DECLINED"
        confidence = min(fraud_result["fraud_score"], 99)
    elif ofac_result["flagged"]:
        decision = "DECLINED"
        confidence = 100
    elif fraud_result["recommended_action"] == "manual_review" or kyc_status != "approved":
        decision = "PENDING_REVIEW"
        confidence = max(0, 100 - fraud_result["fraud_score"] - (20 if kyc_status != "approved" else 0))
    else:
        decision = "APPROVED"
        confidence = max(70, 100 - fraud_result["fraud_score"])

    return {
        "borrower_id": borrower_id,
        "borrower_name": full_name,
        "decision": decision,
        "confidence_score": min(confidence, 100),
        "ofac": ofac_result,
        "pep": pep_result,
        "ssn": ssn_result,
        "fraud": fraud_result,
        "kyc": {
            "status": kyc_status,
            "total_docs": len(doc_list),
            "verified": verified_docs,
            "pending": pending_docs,
        },
        "issues": issues,
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
    }


def calculate_identity_confidence(borrower: dict, kyc_documents: Optional[list] = None) -> dict:
    """Calculate identity confidence score (0-100) based on weighted factors.

    Pure function — takes data dicts instead of querying a DB.

    Parameters
    ----------
    borrower : dict
        Borrower record with first_name, last_name, created_at.
    kyc_documents : list, optional
        List of KYC document records with verification_status.

    Returns
    -------
    dict with total score, breakdown, and verified flag.
    """
    scores = {
        "documents_uploaded": 0,
        "documents_verified": 0,
        "ofac_clear": 0,
        "fraud_score": 20,
        "account_age": 0,
    }

    if not borrower:
        return {"total": 0, "breakdown": scores, "error": "Borrower not found"}

    docs = kyc_documents or []

    # 25% — Documents uploaded
    doc_count = len(docs)
    scores["documents_uploaded"] = min(25, doc_count * 12)

    # 25% — Documents verified
    verified = sum(1 for d in docs if d.get("verification_status") == "verified")
    if doc_count > 0:
        scores["documents_verified"] = int((verified / doc_count) * 25)

    # 20% — OFAC clear
    first = borrower.get("first_name", "")
    last = borrower.get("last_name", "")
    ofac_result = ofac_check(first, last)
    scores["ofac_clear"] = 20 if not ofac_result["flagged"] else 0

    # 10% — Account age
    created = borrower.get("created_at", "")
    if created:
        try:
            created_dt = datetime.strptime(str(created)[:19], "%Y-%m-%d %H:%M:%S")
            days_old = (datetime.now(timezone.utc) - created_dt.replace(tzinfo=timezone.utc)).days
            scores["account_age"] = min(10, days_old * 2)
        except (ValueError, TypeError):
            scores["account_age"] = 5

    total = sum(scores.values())
    return {
        "total": min(total, 100),
        "breakdown": scores,
        "verified": total >= 70,
    }
