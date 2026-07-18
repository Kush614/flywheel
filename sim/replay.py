"""Historical replay — streams a real/realistic 12-month campaign CSV through
the SAME marketing plugin, one period every few seconds (§5.2, the credibility
slide).

The point isn't optimization here — the numbers are recorded history — it's that
the identical loop (plan/act/observe/correct, Pomerium gate, creative discovery,
Loop B trigger) runs end-to-end on real data with no code change. ReplaySimulator
exposes the exact same surface as MarketSimulator, so MarketingPlugin can't tell
the difference.
"""
from __future__ import annotations

import csv
import os

from sim.market import PeriodResult

DEFAULT_CSV = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "campaign_12mo.csv")


class ReplaySimulator:
    def __init__(self, csv_path: str = DEFAULT_CSV):
        self.csv_path = csv_path
        self._by_period: dict[int, list[dict]] = {}
        self._keywords: list[str] = []
        self._load()
        self._period = 0
        self._poison: dict[str, tuple[str, object]] = {}

    def _load(self) -> None:
        seen: list[str] = []
        with open(self.csv_path, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                p = int(row["period"])
                self._by_period.setdefault(p, []).append(row)
                if row["keyword"] not in seen:
                    seen.append(row["keyword"])
        self._keywords = seen
        self._periods = sorted(self._by_period)

    def keyword_names(self) -> list[str]:
        return list(self._keywords)

    # same signature as MarketSimulator.query — bids are recorded, not applied
    def query(self, bids: dict[str, float], period: int | None = None) -> list[PeriodResult]:
        idx = self._period if period is None else period
        # loop the year so the demo can run continuously
        p = self._periods[idx % len(self._periods)]
        results = []
        for row in self._by_period[p]:
            name = row["keyword"]
            clicks = int(row["clicks"])
            conversions = int(row["conversions"])
            cost = float(row["cost"])
            cpa = row.get("cost_per_conversion") or ""
            # synthesize a plausible win_rate for the classifier (not recorded)
            win = 0.5
            raw = {"keyword": name, "bid": float(row["bid"]), "win_rate": win,
                   "cpc": round(cost / clicks, 3) if clicks else 0.0, "replay": True}
            if name in self._poison:
                fname, fval = self._poison[name]
                raw[fname] = fval
            results.append(PeriodResult(
                keyword=name, bid=float(row["bid"]),
                impressions=int(row["impressions"]), clicks=clicks,
                conversions=conversions, cost=round(cost, 2),
                cost_per_conversion=(float(cpa) if cpa else float("inf")),
                raw=raw,
            ))
        self._period = idx + 1
        return results

    # --- curveball interface (kept identical so Session code is mode-agnostic)
    # replay is recorded history, so the market-shaping knobs are no-ops; only
    # poison rides along on the raw payload (the injection demo works in replay).
    def start_bid_war(self, keyword, intensity=0.5): pass
    def stop_bid_war(self, keyword): pass
    def start_seasonal_spike(self, magnitude=0.6): pass
    def stop_seasonal_spike(self): pass
    def mark_dud(self, keyword): pass

    def poison(self, keyword, field_name, value):
        self._poison[keyword] = (field_name, value)

    def clear_poison(self, keyword):
        self._poison.pop(keyword, None)
