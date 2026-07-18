"""Thrash / stop detection — the single most impressive demo beat.

An agent that catches *itself* is what separates loop engineering from a
while-loop with an LLM in it. Two independent triggers:

  1. Oscillation: the same target is pushed one way then reversed, twice,
     within a noise band. That is thrashing on noise, not signal. Freeze it.
  2. Stagnation: the objective has not improved (beyond a tolerance) for N
     consecutive periods. The current strategy is spent — halt or re-strategize.

The detector never silently stops. It returns a HaltDecision carrying a plain
reason string that goes straight onto the event bus and the dashboard.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class HaltDecision:
    halt: bool = False
    reason: str = ""
    detail: dict = field(default_factory=dict)


class ThrashDetector:
    def __init__(
        self,
        *,
        stagnation_periods: int = 4,
        stagnation_tol: float = 1e-3,
        oscillation_band: float = 0.05,
    ):
        # halt if objective fails to improve for this many consecutive periods
        self.stagnation_periods = stagnation_periods
        self.stagnation_tol = stagnation_tol
        # a reverse is "within noise" if the two moves are smaller than this
        # fraction of the value being adjusted
        self.oscillation_band = oscillation_band

    def evaluate(self, state) -> HaltDecision:
        osc = self._oscillation(state)
        if osc.halt:
            return osc
        return self._stagnation(state)

    # --- trigger 1: push-then-reverse-twice within a noise band -------------
    def _oscillation(self, state) -> HaltDecision:
        # each action is expected to be a dict with 'target' and 'delta'
        by_target: dict[str, list[float]] = {}
        for a in state.last_actions:
            if not isinstance(a, dict):
                continue
            target = a.get("target")
            delta = a.get("delta")
            if target is None or delta is None:
                continue
            by_target.setdefault(target, []).append(float(delta))

        for target, deltas in by_target.items():
            if len(deltas) < 4:
                continue
            recent = deltas[-4:]
            # sign changes = reversals
            reversals = sum(
                1
                for i in range(1, len(recent))
                if recent[i] * recent[i - 1] < 0
            )
            magnitude = max(abs(d) for d in recent)
            base = self._base_value(state, target)
            small = magnitude <= self.oscillation_band * base if base else False
            if reversals >= 2 and small:
                return HaltDecision(
                    halt=True,
                    reason=(
                        f"'{target}' raised then cut {reversals}x within the "
                        f"noise band (moves ≤ {self.oscillation_band:.0%} of "
                        f"value) — freezing it and reallocating attention."
                    ),
                    detail={"target": target, "recent_deltas": recent},
                )
        return HaltDecision()

    # --- trigger 2: objective flat for N periods ---------------------------
    def _stagnation(self, state) -> HaltDecision:
        hist = state.objective_history
        n = self.stagnation_periods
        if len(hist) < n + 1:
            return HaltDecision()
        window = hist[-(n + 1):]
        best_before = max(window[:-n]) if len(window) > n else window[0]
        improved = any(v > best_before + self.stagnation_tol for v in window[-n:])
        if not improved:
            return HaltDecision(
                halt=True,
                reason=(
                    f"objective has not improved for {n} periods "
                    f"(best {best_before:.3f}) — current strategy is spent, "
                    f"halting rather than burning budget."
                ),
                detail={"window": window},
            )
        return HaltDecision()

    def _base_value(self, state, target) -> float:
        """Best-effort current magnitude of a target, for the noise band."""
        bids = state.memory.get("bids") or {}
        if target in bids:
            try:
                return abs(float(bids[target])) or 1.0
            except (TypeError, ValueError):
                return 1.0
        return 1.0
