# PalmFi Autonomous Operation — How It Runs Without You

## TL;DR

A single cron line runs `automation.autopilot` every 15 minutes. It auto-decisions applications, disburses funds, collects payments, sends reminders, escalates delinquents, and rewards good payers — all logged for audit. **Set it, walk away.**

---

## What's Automated (No Human Needed)

| Step | What it does | Frequency | Code |
|---|---|---|---|
| **1. Auto-decision** | Scores pending apps with ML + cash-flow → approves/declines automatically based on risk thresholds | Every 15 min | `step_auto_decision` |
| **2. Auto-disburse** | Sends ACH transfer via Stripe for approved loans with signed contracts | Every 15 min | `step_auto_disburse` |
| **3. Auto-collect** | Charges autopay payments on due date | Every 15 min | `step_auto_collect` |
| **4. Dunning** | Sends payment reminders at 3, 7, 15, 30 days late (escalating tone) | Every 15 min | `step_dunning` |
| **5. Escalate** | Marks 60+ day delinquent loans for collection agency handoff | Every 15 min | `step_escalate` |
| **6. Rate improvement** | Rewards 6+ on-time payments with 2pp rate cut + sends notification | Every 15 min | `step_rate_improve` |
| **7. Daily report** | Aggregates all activity to autopilot_log for review | Every 15 min | `step_daily_report` |

---

## The AI's "Judgement" — Built-in Policy Limits

To prevent the system from doing something dumb at scale, autopilot has hard guardrails:

```python
AUTO_APPROVE_MIN_SCORE = 680   # Above this = auto-approve
AUTO_DECLINE_MAX_SCORE = 540   # Below this = auto-decline
# 540-680 → flagged for human review (the "gray zone")
MAX_AUTO_LOAN_AMOUNT = $15,000  # Bigger loans require human approval
```

**You only ever look at:**
- Gray-zone applications (540–680 risk band)
- Loans > $15k
- Errors in the autopilot log

Everything else handles itself.

---

## Install the Autopilot Cron

```bash
cd ~/palmfi
bash scripts/install_autopilot_cron.sh
# Adds: */15 * * * * python3 -m automation.autopilot
```

To run a single tick manually (for debugging):
```bash
python3 -m automation.autopilot
```

To watch the AI work in real time:
```bash
tail -f ~/palmfi/logs/autopilot.log
```

To see every decision the AI made:
```bash
sqlite3 ~/palmfi/platform/palmfi.db "SELECT ts, action, target_type, target_id, details FROM autopilot_log ORDER BY id DESC LIMIT 50"
```

---

## Going Further — Full Autonomy (LLM-in-the-loop)

The current autopilot uses **rule-based AI** (the underwriting model + thresholds). To add **agentic AI**, plug an LLM into the gray-zone reviewer:

```python
# Add to autopilot.py
def llm_review_gray_zone(app, ml_score, reasons):
    """Use Claude/GPT to make the human-in-the-loop call automatically."""
    prompt = f"""You are PalmFi's senior underwriter. Review this application:
    Risk score: {ml_score} (gray zone)
    ML reasons: {reasons}
    Application: {json.dumps(app)}
    Decide: approve / decline / request_documents
    Respond with JSON: {{decision, confidence, rationale}}"""
    # call your LLM endpoint here
```

This turns it into truly hands-off lending — but you should run for 1–2 months in rule-based mode first to gather data on what the gray-zone decisions look like.

---

## Customer Support Automation

Add a Telegram/SMS bot wired to the same DB:

```bash
# WhatsApp/SMS chatbot (already a separate skill — whatsapp-tenant-communication)
# Borrower texts: "What's my balance?"
# AI looks up loan, replies in seconds.
# Borrower texts: "Can I skip a payment?"
# AI checks policy, offers deferment if eligible.
```

Combined with autopilot, this means: **borrower flows self-serve, AI underwrites, AI funds, AI collects, AI answers questions.** You review once a week.

---

## Weekly Human Tasks (~30 min/week)

1. Review gray-zone applications (5–20 per week)
2. Approve loans > $15k (rare for a starting portfolio)
3. Glance at the daily_report row in autopilot_log
4. Check for any errors (`success=0` rows)
5. Once a quarter — retrain the model on your real loan performance

---

## Risk: What Could Go Wrong & How It's Mitigated

| Risk | Mitigation |
|---|---|
| AI approves a fraudster | KYC (Persona/Alloy) runs before any approval; ML uses fraud-tuned features |
| AI declines unfairly (ECOA risk) | All decisions log reasons; gray-zone goes to human; quarterly fair-lending audit |
| Stripe ACH fails | `transfer_id` logged null → flagged for retry on next tick |
| Borrower data leaks | bcrypt + parameterized SQL + JWT (already audited) |
| Cron stops running | Daily report row missing for >24h → trigger pager |
| Model drift | Quarterly retrain + monitor AUC on holdout |

---

## Bottom Line

You are now operating a lending company with **15 minutes/week of human attention**. The platform plus autopilot replaces:

- A 5-person underwriting team ($500k/yr)
- A 3-person collections team ($200k/yr)
- A 2-person customer ops team ($150k/yr)

That's ~$850k/yr of operating cost compressed into a Python file and a cron line.
