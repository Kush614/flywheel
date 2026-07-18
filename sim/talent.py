"""Reply-rate simulator for Loop B (talent) — the ground-truth signal the
recruiting loop optimizes, exactly analogous to the market simulator.

Outbound recruiting has a hidden response surface too: a message's tone and the
seniority it targets jointly determine reply-rate, with a sweet spot the agent
must *discover*. Too-casual or too-formal messaging, or targeting the wrong
seniority, converts poorly. The agent never sees this function — it sends
batches, observes the reply-rate, and hill-climbs.

Reply-rate is ground truth (a real reply either happens or it doesn't), so this
is a genuine observe/correct loop, not a tacked-on API call. Deterministic (no
wall-clock, no global RNG) so demos and tests replay identically.
"""
from __future__ import annotations

import math
from dataclasses import dataclass


def _lcg(seed: int) -> float:
    seed = (1103515245 * seed + 12345) & 0x7FFFFFFF
    return seed / 0x7FFFFFFF


@dataclass
class OutreachResult:
    sent: int
    replies: int
    reply_rate: float
    tone: float
    seniority: float


class TalentSimulator:
    """Hidden bell-shaped response surface over (tone, seniority)."""

    def __init__(self, seed: int = 11, batch_size: int = 60):
        self.seed = seed
        self.batch_size = batch_size
        self._period = 0
        # hidden optimum — the agent must find it
        self._best_tone = 0.65        # slightly warm, not stiff
        self._best_seniority = 0.55   # mid-senior candidates reply most
        self._scale = 0.28
        self._peak_rate = 0.36

    def send(self, tone: float, seniority: float, period: int | None = None) -> OutreachResult:
        p = self._period if period is None else period
        rnd = _lcg(self.seed * 1000003 + p * 131)
        noise = 0.9 + 0.2 * rnd  # +/-10%

        d2 = (tone - self._best_tone) ** 2 + (seniority - self._best_seniority) ** 2
        reply_rate = self._peak_rate * math.exp(-d2 / self._scale) * noise
        reply_rate = max(0.0, min(1.0, reply_rate))

        sent = self.batch_size
        replies = int(round(sent * reply_rate))
        self._period = p + 1
        return OutreachResult(
            sent=sent, replies=replies,
            reply_rate=round(replies / sent, 4) if sent else 0.0,
            tone=round(tone, 3), seniority=round(seniority, 3),
        )
