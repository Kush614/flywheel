"""Ground-truth market simulator — the reward model the agent must *discover*.

The agent bids on keywords and observes impressions / clicks / conversions /
cost. It never sees this function. It has to learn, by bidding and watching,
that:

  * each keyword has a hidden `quality` (relevance) and a hidden `value`
    (conversion rate) — a keyword can be cheap to win yet never convert;
  * clicks rise with bid but with diminishing returns (an auction curve);
  * competitor pressure raises the price of a click without improving it;
  * a "dud" keyword gets clicks but converts near zero — the correct fix is
    *not* a higher bid (that's the cause-hypothesis test in the spec).

Curveball knobs (this is the stage magic — toggle live and the agent reacts):
  * start_bid_war(keyword)   — a competitor floods one keyword; CPC spikes.
  * start_seasonal_spike()   — demand surges everywhere; conversions jump.
  * mark_dud(keyword)        — kill a keyword's conversion value silently.
  * poison(keyword, field, value) — inject an adversarial data field that the
    downstream (Nexla/Pomerium) layers must refuse to act on. Here it just
    rides along on the raw payload so M4 can demonstrate the block.

Determinism: no wall-clock, no global RNG. A seeded LCG per (period, keyword)
gives reproducible noise so demos and tests replay identically.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


def _lcg(seed: int) -> float:
    """Deterministic pseudo-random float in [0,1) from an integer seed."""
    seed = (1103515245 * seed + 12345) & 0x7FFFFFFF
    return seed / 0x7FFFFFFF


def _shash(s: str) -> int:
    """Stable string hash. Python's built-in hash() is per-process randomized,
    which would make the 'ground truth' non-reproducible. This one isn't."""
    h = 2166136261
    for ch in s:
        h = (h ^ ord(ch)) * 16777619 & 0xFFFFFFFF
    return h


@dataclass
class Keyword:
    name: str
    quality: float          # 0..1 relevance — how easily bids win the auction
    value: float            # 0..1 conversion propensity of a click
    base_competition: float # 0..1 baseline competitor pressure


@dataclass
class PeriodResult:
    keyword: str
    bid: float
    impressions: int
    clicks: int
    conversions: int
    cost: float
    cost_per_conversion: float
    raw: dict = field(default_factory=dict)


DEFAULT_KEYWORDS = [
    # name,             quality, value, competition
    Keyword("running-shoes",     0.75, 0.65, 0.40),   # strong all-rounder
    Keyword("cheap-widgets",     0.55, 0.10, 0.30),   # clicky but a dud value
    Keyword("premium-watches",   0.60, 0.80, 0.55),   # high value, contested
    Keyword("blue-sneakers",     0.45, 0.50, 0.20),   # sleeper, undervalued
    Keyword("luxury-handbags",   0.50, 0.90, 0.70),   # gold if you can afford it
]


class MarketSimulator:
    def __init__(self, keywords: Optional[list[Keyword]] = None, seed: int = 7):
        self.keywords = {k.name: k for k in (keywords or DEFAULT_KEYWORDS)}
        self.seed = seed
        self._period = 0
        # live curveball state
        self._bid_war: dict[str, float] = {}      # keyword -> extra competition
        self._seasonal = 0.0                       # additive demand multiplier
        self._duds: set[str] = set()
        self._poison: dict[str, tuple[str, object]] = {}

    # --- curveball controls (call these live on stage) ---------------------
    def start_bid_war(self, keyword: str, intensity: float = 0.5) -> None:
        self._bid_war[keyword] = intensity

    def stop_bid_war(self, keyword: str) -> None:
        self._bid_war.pop(keyword, None)

    def start_seasonal_spike(self, magnitude: float = 0.6) -> None:
        self._seasonal = magnitude

    def stop_seasonal_spike(self) -> None:
        self._seasonal = 0.0

    def mark_dud(self, keyword: str) -> None:
        self._duds.add(keyword)

    def poison(self, keyword: str, field_name: str, value: object) -> None:
        """Inject an adversarial field onto a keyword's raw payload."""
        self._poison[keyword] = (field_name, value)

    def clear_poison(self, keyword: str) -> None:
        self._poison.pop(keyword, None)

    def keyword_names(self) -> list[str]:
        return list(self.keywords)

    # --- the hidden response function --------------------------------------
    def query(self, bids: dict[str, float], period: Optional[int] = None) -> list[PeriodResult]:
        """Run one auction period given a bid per keyword."""
        p = self._period if period is None else period
        results = []
        for name, kw in self.keywords.items():
            bid = max(0.0, float(bids.get(name, 0.0)))
            results.append(self._simulate_keyword(kw, bid, p))
        self._period = p + 1
        return results

    def _simulate_keyword(self, kw: Keyword, bid: float, period: int) -> PeriodResult:
        rnd = _lcg(self.seed * 1000003 + period * 131 + _shash(kw.name) % 997)
        noise = 0.95 + 0.1 * rnd  # +/-5% multiplicative noise

        competition = kw.base_competition + self._bid_war.get(kw.name, 0.0)
        competition = min(0.95, competition)

        # impressions scale with quality; roughly fixed auction inventory
        impressions = int(1000 * (0.5 + 0.5 * kw.quality) * noise)

        # --- the auction: bid buys win-rate against a competition floor ----
        floor = 0.5 + 1.5 * competition
        win = bid / (bid + floor) if bid > 0 else 0.0            # 0..1

        # better ad position (higher win) buys more clicks AND better clicks,
        # so click-through rises with win rate
        ctr = (0.02 + 0.10 * kw.quality) * (0.4 + 0.6 * win)
        clicks = int(impressions * ctr * noise)

        # --- winner's curse: cost-per-click rises SUPER-linearly with win ---
        # this is what creates an interior optimum. Bidding to the top of the
        # page is expensive; the sweet spot is a middling win rate.
        cpc = floor * (1.0 + 1.8 * win * win) * (1.0 + 0.4 * competition)
        cost = clicks * cpc

        # --- conversions: value * placement-quality, killed if dud, +season -
        placement = 0.3 + 0.7 * win                     # top slots convert more
        value = 0.0 if kw.name in self._duds else kw.value
        conv_rate = value * (1.0 + self._seasonal) * placement
        conversions = int(clicks * conv_rate * (0.6 + 0.4 * noise))

        cpa = (cost / conversions) if conversions > 0 else float("inf")

        raw = {
            "keyword": kw.name,
            "bid": round(bid, 3),
            "win_rate": round(win, 3),
            "cpc": round(cpc, 3),
            "competition": round(competition, 3),
        }
        # ride-along adversarial field for the Pomerium/Nexla demo (M4)
        if kw.name in self._poison:
            fname, fval = self._poison[kw.name]
            raw[fname] = fval

        return PeriodResult(
            keyword=kw.name,
            bid=bid,
            impressions=impressions,
            clicks=clicks,
            conversions=conversions,
            cost=round(cost, 2),
            cost_per_conversion=(round(cpa, 2) if conversions else float("inf")),
            raw=raw,
        )
