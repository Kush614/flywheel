"""Explicit explore/exploit budgeter.

Spending to *learn* about an untested target competes with spending on a known
winner. The engine surfaces this tradeoff so a plugin's Plan can say, out loud,
"probing 1 unknown keyword at 10% of budget; exploiting the top 3." A pure
exploit loop looks smart until the winner decays and it never noticed a better
option existed.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Allocation:
    explore: list          # targets to probe (learn)
    exploit: list          # targets to bet on (earn)
    explore_fraction: float
    note: str


class ExploreExploitBudgeter:
    def __init__(self, explore_fraction: float = 0.10, top_k: int = 3):
        self.explore_fraction = explore_fraction
        self.top_k = top_k

    def allocate(self, known_value: dict[str, float], untested: list[str]) -> Allocation:
        """Pick winners to exploit and (at most one) unknown to probe.

        known_value: target -> observed value-per-dollar so far (higher better)
        untested:    targets we have no signal on yet
        """
        ranked = sorted(known_value.items(), key=lambda kv: kv[1], reverse=True)
        exploit = [t for t, _ in ranked[: self.top_k]]

        explore: list[str] = []
        if untested:
            # probe the single least-known target this period
            explore = [untested[0]]
            note = (
                f"probing 1 unknown target '{untested[0]}' at "
                f"{self.explore_fraction:.0%} of budget; exploiting top "
                f"{len(exploit)}: {', '.join(exploit) or '—'}"
            )
        else:
            note = (
                f"no untested targets — fully exploiting top {len(exploit)}: "
                f"{', '.join(exploit) or '—'}"
            )

        return Allocation(
            explore=explore,
            exploit=exploit,
            explore_fraction=self.explore_fraction if explore else 0.0,
            note=note,
        )
