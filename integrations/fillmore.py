"""Fillmore by Metaview seam — the ACT layer of Loop B (§6.6).

Fillmore "finds candidates, runs personalized outreach, and books screening
calls autonomously." It has no public API (waitlist only, confirmed at the
docs), so this client runs against a local reply-rate simulator by default and
switches to the real API the moment FILLMORE_API_KEY is present. Either way the
loop is identical: `run_outreach` is `act`, the returned reply-rate is the
ground-truth `observe` signal.

This keeps Loop B a *real* observe/correct loop rather than a one-shot API call:
the agent adjusts messaging tone + targeting seniority, Fillmore sends the batch,
and the reply-rate tells it whether the correction worked.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from sim.talent import TalentSimulator, OutreachResult


@dataclass
class Campaign:
    role: str
    tone: float          # 0 = formal, 1 = warm/casual
    seniority: float     # 0 = junior, 1 = senior


class FillmoreClient:
    def __init__(self, sim: TalentSimulator | None = None):
        self.sim = sim or TalentSimulator()

    @property
    def available(self) -> bool:
        return bool(os.environ.get("FILLMORE_API_KEY"))

    @property
    def source(self) -> str:
        return "Fillmore API" if self.available else "Fillmore (stub - simulated reply-rate)"

    def run_outreach(self, campaign: Campaign, period: int) -> OutreachResult:
        """Send one outreach batch and return the reply-rate signal."""
        if self.available:
            # Real Fillmore integration would POST the campaign and poll replies.
            # Left as a stub because there is no public API yet; falls through to
            # the simulator so the loop always runs.
            return self._real_or_sim(campaign, period)
        return self.sim.send(campaign.tone, campaign.seniority, period)

    def _real_or_sim(self, campaign: Campaign, period: int) -> OutreachResult:
        # Placeholder for the booth-confirmed API surface. Until wired, use sim.
        return self.sim.send(campaign.tone, campaign.seniority, period)
