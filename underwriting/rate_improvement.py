#!/usr/bin/env python3
"""Dynamic Rate Improvement Engine.

On-time payments automatically reduce APR over the life of a loan.
Rewards good behavior without needing to refinance.

Key mechanics:
- Every 6 consecutive on-time payments = 0.5% APR reduction
- Max reduction: 3% (6 steps, 36 months of perfect payment)
- Missed payment resets the streak counter
- Borrower sees "Next rate drop in X payments" on dashboard
"""

import sqlite3
import json
import os
from datetime import datetime, timedelta


class RateImprovementEngine:
    """Manages dynamic APR reductions based on payment history."""

    MAX_STEPS = 6           # Max number of rate drops
    DROP_PER_STEP = 0.50    # 0.5% per 6 on-time payments
    PAYMENTS_PER_STEP = 6   # Consecutive on-time payments needed
    MAX_REDUCTION = 3.00    # 3% total max reduction

    def __init__(self, db_path=None):
        if db_path is None:
            # Default to platform/lending.db
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            db_path = os.path.join(project_root, 'platform', 'lending.db')
        self.db_path = db_path

    def get_conn(self):
        """Get a database connection with the platform's schema."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def get_loan_status(self, loan_id):
        """Get current rate improvement state for a loan.

        Returns dict with:
          current_rate, original_rate, reduction_applied,
          consecutive_on_time, next_drop_at, steps_completed, max_possible
        """
        conn = self.get_conn()
        loan = conn.execute(
            "SELECT id, borrower_id, interest_rate, principal, term_months, "
            "remaining_balance, status FROM loans WHERE id=?",
            (loan_id,)
        ).fetchone()

        if not loan:
            conn.close()
            return None

        loan = dict(loan)

        # Get original rate from applications table
        app = conn.execute(
            "SELECT interest_rate FROM applications WHERE id=(SELECT application_id FROM loans WHERE id=?)",
            (loan_id,)
        ).fetchone()

        original_rate = float(app['interest_rate']) if app else float(loan['interest_rate'])
        current_rate = float(loan['interest_rate'])

        # Count consecutive on-time payments (most recent PAYMENTS_PER_STEP * 2 payments)
        recent_payments = conn.execute(
            "SELECT status, paid_at FROM payments WHERE loan_id=? AND payment_type='scheduled' "
            "ORDER BY paid_at DESC LIMIT ?",
            (loan_id, self.PAYMENTS_PER_STEP * 2)
        ).fetchall()

        # Streak: count consecutive 'completed' payments from most recent
        consecutive_on_time = 0
        for p in recent_payments:
            p = dict(p)
            if p['status'] == 'completed' and p['paid_at']:
                consecutive_on_time += 1
            else:
                break

        # Calculate steps
        total_reduction = original_rate - current_rate
        steps_completed = int(total_reduction / self.DROP_PER_STEP)
        steps_remaining = self.MAX_STEPS - steps_completed
        next_drop_at = self.PAYMENTS_PER_STEP - (consecutive_on_time % self.PAYMENTS_PER_STEP)
        if next_drop_at == 0:
            next_drop_at = self.PAYMENTS_PER_STEP

        conn.close()

        return {
            'loan_id': loan_id,
            'original_rate': round(original_rate, 2),
            'current_rate': round(current_rate, 2),
            'total_reduction': round(total_reduction, 2),
            'consecutive_on_time': consecutive_on_time,
            'next_drop_at': next_drop_at,
            'steps_completed': steps_completed,
            'steps_remaining': max(0, steps_remaining),
            'max_possible_reduction': self.MAX_REDUCTION,
            'reduction_per_step': self.DROP_PER_STEP,
            'payments_per_step': self.PAYMENTS_PER_STEP,
            'can_improve': steps_completed < self.MAX_STEPS,
            'payment_streak_label': self._streak_label(consecutive_on_time),
        }

    def apply_payment_reward(self, loan_id, payment_id=None):
        """Check if a payment triggers a rate reduction and apply it.

        Call this AFTER a successful payment is recorded.
        Returns the reduction result or None if no reduction applies.
        """
        status = self.get_loan_status(loan_id)
        if not status:
            return None

        if status['steps_completed'] >= self.MAX_STEPS:
            return {'applied': False, 'reason': 'max_reduction_reached'}

        # Check if consecutive on-time payments hit the threshold
        if status['consecutive_on_time'] > 0 and status['consecutive_on_time'] % self.PAYMENTS_PER_STEP == 0:
            # Apply rate reduction
            new_rate = round(status['current_rate'] - self.DROP_PER_STEP, 2)

            # Floor check: don't go below 3.99%
            if new_rate < 3.99:
                new_rate = 3.99

            conn = self.get_conn()
            conn.execute(
                "UPDATE loans SET interest_rate=? WHERE id=?",
                (new_rate, loan_id)
            )

            # Recalculate monthly payment
            loan = conn.execute(
                "SELECT principal, remaining_balance, term_months FROM loans WHERE id=?",
                (loan_id,)
            ).fetchone()

            # For simplicity, recalculate monthly payment based on remaining balance
            remaining = float(loan['remaining_balance'])
            term_remaining = self._estimate_remaining_payments(conn, loan_id)

            if term_remaining > 0:
                from underwriting.pricing import PricingEngine
                new_payment = PricingEngine.calculate_monthly_payment(
                    remaining, new_rate, term_remaining
                )
                conn.execute(
                    "UPDATE loans SET monthly_payment=? WHERE id=?",
                    (new_payment, loan_id)
                )

            # Log the rate improvement
            conn.execute(
                "INSERT INTO audit_logs (action_type, borrower_id, actor, details) VALUES (?, ?, ?, ?)",
                (
                    'rate_improvement',
                    conn.execute("SELECT borrower_id FROM loans WHERE id=?", (loan_id,)).fetchone()['borrower_id'],
                    'system',
                    json.dumps({
                        'loan_id': loan_id,
                        'old_rate': status['current_rate'],
                        'new_rate': new_rate,
                        'reduction': self.DROP_PER_STEP,
                        'consecutive_payments': status['consecutive_on_time'],
                        'step': status['steps_completed'] + 1,
                    })
                )
            )

            conn.commit()
            conn.close()

            return {
                'applied': True,
                'old_rate': status['current_rate'],
                'new_rate': new_rate,
                'reduction': self.DROP_PER_STEP,
                'step': status['steps_completed'] + 1,
            }

        return {
            'applied': False,
            'reason': 'not_yet_eligible',
            'payments_needed': self.PAYMENTS_PER_STEP - (status['consecutive_on_time'] % self.PAYMENTS_PER_STEP),
            'consecutive': status['consecutive_on_time'],
        }

    def _estimate_remaining_payments(self, conn, loan_id):
        """Count remaining scheduled payments."""
        row = conn.execute(
            "SELECT COUNT(*) as c FROM payment_schedules WHERE loan_id=? AND status='pending'",
            (loan_id,)
        ).fetchone()
        return row['c'] if row else 12

    def _streak_label(self, count):
        """Human-friendly label for payment streak."""
        if count == 0:
            return 'Start your streak'
        elif count < 3:
            return 'Just getting started'
        elif count < 6:
            return 'Building momentum'
        elif count < 12:
            return 'On a roll'
        elif count < 18:
            return 'Payment machine'
        else:
            return '🏆 Elite payer'

    def get_all_active_loans_with_improvement_data(self):
        """Get rate improvement data for all active loans (admin view)."""
        conn = self.get_conn()
        loans = conn.execute(
            "SELECT id FROM loans WHERE status='active'"
        ).fetchall()
        conn.close()

        results = []
        for loan in loans:
            data = self.get_loan_status(loan['id'])
            if data:
                results.append(data)

        return sorted(results, key=lambda x: x['steps_completed'], reverse=True)


# Quick test
if __name__ == '__main__':
    ri = RateImprovementEngine()
    print("Rate Improvement Engine loaded.")
    print(f"Max reduction: {ri.MAX_REDUCTION}% over {ri.MAX_STEPS} steps")
    print(f"Each {ri.PAYMENTS_PER_STEP} on-time payments = {ri.DROP_PER_STEP}% drop")
