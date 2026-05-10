#!/usr/bin/env python3
"""
Reconsideration Engine — Two-Stage Decision Flow

Implements the "second look" underwriting architecture described in
ARCHITECTURE_V2.md. Stage 1 classifies a bureau-only XGBoost score into
one of three zones. Stage 2 performs a blended reconsideration for
applicants who were not auto-approved, incorporating Plaid cash flow data
and an optional LLM document extraction boost.

Decision Zones:
    ┌──────────────┬──────────┬──────────────────────────────────┐
    │ Zone         │ Score    │ Action                           │
    ├──────────────┼──────────┼──────────────────────────────────┤
    │ Auto-Approve │ ≤ 50     │ Approved on bureau alone         │\n    │ Consideration│ 51–60    │ Second look: 50/50 bureau + CF   │\n    │ Decline      │ > 60     │ Second look: 40/60 bureau + CF   │
    └──────────────┴──────────┴──────────────────────────────────┘

Reconsideration blends the original bureau score with a cash flow score
(a lower blended score is better). An optional LLM boost (from document
extraction for self-employed applicants) further reduces the score.
"""

from __future__ import annotations

from typing import Any, Dict, Optional


class ReconsiderationEngine:
    """Two-stage underwriting decision engine.

    Stage 1 — Classification: Maps a bureau XGBoost score to a zone.
    Stage 2 — Reconsideration: Blends bureau + cash flow scores for
              non-auto-approved applicants, with optional LLM boost.

    Attributes
    ----------
    ZONES : dict
        Zone definitions with min/max score boundaries.
    RECONSIDERATION_THRESHOLD : int
        Maximum blended score for approval after reconsideration.
    """

    # Thresholds calibrated from XGBoost score distribution on LendingClub data:
    #   ≤ 50: 60.2% of population (auto-approve)
    #   51-60: 20.9% (consideration zone)
    #   > 60: 18.9% (decline zone)
    # Reconsideration threshold = 60 (same as consideration max)
    ZONES: Dict[str, Dict[str, Any]] = {
        "auto_approve": {
            "max_score": 50,
            "description": "Approved on credit data alone",
        },
        "consideration": {
            "min_score": 51,
            "max_score": 60,
            "description": "Need more info — cash flow review available",
        },
        "decline": {
            "min_score": 61,
            "description": "Not approved on credit alone — cash flow review available",
        },
    }

    RECONSIDERATION_THRESHOLD: int = 60

    # ------------------------------------------------------------------
    # Stage 1: Classification
    # ------------------------------------------------------------------

    def classify(self, bureau_score: int) -> str:
        """Classify a bureau-only XGBoost score into a decision zone.

        Parameters
        ----------
        bureau_score : int
            The raw score from the XGBoost bureau model (lower = better).

        Returns
        -------
        str
            One of ``'auto_approve'``, ``'consideration'``, or ``'decline'``.

        Raises
        ------
        ValueError
            If ``bureau_score`` is negative.
        """
        if bureau_score < 0:
            raise ValueError(
                f"bureau_score must be non-negative, got {bureau_score}"
            )

        if bureau_score <= self.ZONES["auto_approve"]["max_score"]:
            return "auto_approve"
        elif bureau_score <= self.ZONES["consideration"]["max_score"]:
            return "consideration"
        else:
            return "decline"

    # ------------------------------------------------------------------
    # Stage 2: Reconsideration
    # ------------------------------------------------------------------

    def reconsider(
        self,
        bureau_score: int,
        cash_flow_score: int,
        zone: str,
        llm_boost: int = 0,
    ) -> Dict[str, Any]:
        """Run the reconsideration (blended scoring) for a single applicant.

        Blends the bureau score with a Plaid cash flow score, applying
        different weights depending on the zone:

        * **consideration** — 50 % bureau / 50 % cash flow
        * **decline**       — 40 % bureau / 60 % cash flow (heavier CF)

        An optional ``llm_boost`` (from document extraction for
        self-employed applicants) is **subtracted** from the blended
        score — lower is better.

        Parameters
        ----------
        bureau_score : int
            Original bureau-only XGBoost score (0–100 scale).
        cash_flow_score : int
            Cash flow score from Plaid analysis (0–100 scale, lower = better).
        zone : str
            Zone returned by :meth:`classify` (``'consideration'`` or
            ``'decline'``). Passing ``'auto_approve'`` is a no-op.
        llm_boost : int, optional
            Points to subtract from the blended score based on LLM
            document extraction (default ``0``).

        Returns
        -------
        dict
            Dictionary with keys:

            - **blended_score** (*int*) — Final blended score after
              weighting and LLM boost.
            - **approved** (*bool*) — Whether the applicant is approved
              after reconsideration.
            - **reason** (*str*) — Human-readable decision reason.
            - **cash_flow_weight** (*float*) — Weight applied to the
              cash flow score in the blend.
            - **llm_boost_applied** (*bool*) — Whether an LLM boost
              value was provided.

        Raises
        ------
        ValueError
            If ``zone`` is not one of the recognised zones.
        """
        if zone not in self.ZONES:
            raise ValueError(
                f"Unknown zone '{zone}'. "
                f"Must be one of: {', '.join(self.ZONES)}"
            )

        # Auto-approved applicants bypass reconsideration.
        if zone == "auto_approve":
            return {
                "blended_score": bureau_score,
                "approved": True,
                "reason": "Auto-approved on bureau data alone; reconsideration not required.",
                "cash_flow_weight": 0.0,
                "llm_boost_applied": bool(llm_boost),
            }

        # Determine blend weights based on zone.
        if zone == "consideration":
            cash_flow_weight = 0.50
            bureau_weight = 0.50
        else:  # 'decline'
            cash_flow_weight = 0.60
            bureau_weight = 0.40

        # Blended score: weighted average, then subtract LLM boost.
        raw_blend = (bureau_weight * bureau_score) + (
            cash_flow_weight * cash_flow_score
        )
        blended_score = max(0, int(round(raw_blend)) - llm_boost)

        # Decision threshold.
        approved = blended_score <= self.RECONSIDERATION_THRESHOLD

        # Build a human-readable reason.
        if approved:
            reason = (
                f"Approved after reconsideration (blended score: "
                f"{blended_score}, threshold: {self.RECONSIDERATION_THRESHOLD}). "
                f"Weights: {bureau_weight*100:.0f}% bureau / "
                f"{cash_flow_weight*100:.0f}% cash flow."
            )
        else:
            reason = (
                f"Not approved after reconsideration (blended score: "
                f"{blended_score}, threshold: {self.RECONSIDERATION_THRESHOLD}). "
                f"Weights: {bureau_weight*100:.0f}% bureau / "
                f"{cash_flow_weight*100:.0f}% cash flow."
            )

        return {
            "blended_score": blended_score,
            "approved": approved,
            "reason": reason,
            "cash_flow_weight": cash_flow_weight,
            "llm_boost_applied": bool(llm_boost),
        }

    # ------------------------------------------------------------------
    # Formatting & Messaging
    # ------------------------------------------------------------------

    def format_decision(
        self,
        original_score: int,
        reconsideration_result: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Assemble a complete, self-contained decision dictionary.

        Parameters
        ----------
        original_score : int
            The original bureau-only XGBoost score.
        reconsideration_result : dict or None, optional
            The result dict from :meth:`reconsider`, or ``None`` if
            reconsideration was not performed (e.g. auto-approve).

        Returns
        -------
        dict
            Full decision payload with keys:

            - **original_score** (*int*)
            - **original_zone** (*str*)
            - **reconsidered** (*bool*)
            - **final_approved** (*bool*)
            - **blended_score** (*int* or *None*)
            - **cash_flow_weight** (*float*)
            - **llm_boost_applied** (*bool*)
            - **reason** (*str*)
        """
        zone = self.classify(original_score)

        if reconsideration_result is None or zone == "auto_approve":
            return {
                "original_score": original_score,
                "original_zone": zone,
                "reconsidered": False,
                "final_approved": True,
                "blended_score": None,
                "cash_flow_weight": 0.0,
                "llm_boost_applied": False,
                "reason": self.ZONES[zone]["description"],
            }

        return {
            "original_score": original_score,
            "original_zone": zone,
            "reconsidered": True,
            "final_approved": reconsideration_result["approved"],
            "blended_score": reconsideration_result["blended_score"],
            "cash_flow_weight": reconsideration_result["cash_flow_weight"],
            "llm_boost_applied": reconsideration_result["llm_boost_applied"],
            "reason": reconsideration_result["reason"],
        }

    def get_second_look_message(self, zone: str) -> str:
        """Return the borrower-facing message for a given decision zone.

        These messages are presented to the applicant in the UI to
        explain their current status and, where applicable, invite them
        to connect their bank via Plaid for a reconsideration.

        Parameters
        ----------
        zone : str
            One of ``'auto_approve'``, ``'consideration'``, or
            ``'decline'``.

        Returns
        -------
        str
            Human-readable message for display to the borrower.

        Raises
        ------
        ValueError
            If ``zone`` is not a recognised zone.
        """
        if zone not in self.ZONES:
            raise ValueError(
                f"Unknown zone '{zone}'. "
                f"Must be one of: {', '.join(self.ZONES)}"
            )

        messages = {
            "auto_approve": (
                "Great news! Your application has been approved based on "
                "your credit profile alone. You may optionally connect "
                "your bank account via Plaid to qualify for better rates."
            ),
            "consideration": (
                "Your credit profile looks promising. We need a bit more "
                "information to make a final decision. Please connect your "
                "bank account via Plaid so we can review your cash flow — "
                "this takes just a few minutes."
            ),
            "decline": (
                "We weren't able to approve your application based on "
                "credit data alone — but we'd like to give you a second "
                "look. Connect your bank account via Plaid so we can "
                "review your income and cash flow history."
            ),
        }
        return messages[zone]
