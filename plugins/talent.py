"""Loop B — Talent plugin (M6). Runs on the SAME loopkit engine as marketing.

Objective: maximize reply-rate on outbound recruiting by adjusting the message
tone and the seniority it targets. This is a 2-D hill-climb over a hidden
response surface (sim/talent.py), with Fillmore as the `act` layer and reply-
rate as the ground-truth `observe` signal.

The point of Loop B is generality: the engine, the event bus, the detectors,
the four-step contract — all unchanged from Loop A. Only the domain differs.
"""
from __future__ import annotations

from loopkit.core import Plan, ActResult, Observation, Correction, LoopState
from integrations.fillmore import FillmoreClient, Campaign

STEP = 0.10
IMPROVE_TOL = 1e-4


class TalentPlugin:
    name = "talent"

    def __init__(self, fillmore: FillmoreClient, role: str = "Senior Growth Engineer"):
        self.fillmore = fillmore
        self.role = role

    def _state(self, state: LoopState) -> dict:
        return state.memory.setdefault(
            "talent",
            # start off the sweet spot so the climb is visible
            {"tone": 0.20, "seniority": 0.85, "dir_tone": +1, "dir_sen": -1, "last_obj": None},
        )

    # ------------------------------------------------------------------ PLAN
    def plan(self, state: LoopState) -> Plan:
        t = self._state(state)
        old_tone, old_sen = t["tone"], t["seniority"]
        new_tone = min(1.0, max(0.0, old_tone + t["dir_tone"] * STEP))
        new_sen = min(1.0, max(0.0, old_sen + t["dir_sen"] * STEP))
        t["tone"], t["seniority"] = round(new_tone, 3), round(new_sen, 3)

        tone_word = "warmer" if t["dir_tone"] > 0 else "more formal"
        sen_word = "more senior" if t["dir_sen"] > 0 else "more junior"
        rationale = (
            f"Staffing '{self.role}'. Tuning outreach: message {tone_word} "
            f"(tone {new_tone:.2f}), targeting {sen_word} (seniority {new_sen:.2f}) "
            f"to lift reply-rate."
        )
        actions = [
            {"target": "message_tone", "delta": round(new_tone - old_tone, 3), "new_bid": new_tone,
             "issued_period": state.period},
            {"target": "targeting_seniority", "delta": round(new_sen - old_sen, 3), "new_bid": new_sen,
             "issued_period": state.period},
        ]
        return Plan(
            actions=actions,
            rationale=rationale,
            cause_hypotheses={
                "message_tone": f"reply-rate gradient says go {tone_word}",
                "targeting_seniority": f"reply-rate gradient says target {sen_word}",
            },
            explore=[], exploit=[self.role],
            meta={"role": self.role, "source": self.fillmore.source},
        )

    # ------------------------------------------------------------------- ACT
    def act(self, plan: Plan, state: LoopState) -> ActResult:
        t = self._state(state)
        campaign = Campaign(role=self.role, tone=t["tone"], seniority=t["seniority"])
        result = self.fillmore.run_outreach(campaign, state.period)
        state.memory["talent_last"] = result
        return ActResult(
            applied=plan.actions, blocked=[],
            detail={"sent": result.sent, "role": self.role, "via": self.fillmore.source},
        )

    # --------------------------------------------------------------- OBSERVE
    def observe(self, act_result: ActResult, state: LoopState) -> Observation:
        r = state.memory["talent_last"]
        return Observation(
            objective=r.reply_rate,
            signals={
                "outreach": {
                    "sent": r.sent, "replies": r.replies, "reply_rate": r.reply_rate,
                    "tone": r.tone, "seniority": r.seniority,
                }
            },
            classifications={"outreach": "healthy" if r.reply_rate > 0.2 else "warming_up"},
            raw={"reply_rate": r.reply_rate, "role": self.role},
        )

    # --------------------------------------------------------------- CORRECT
    def correct(self, state: LoopState, obs: Observation) -> Correction:
        """Reverse a dimension's direction when the last move hurt reply-rate —
        2-D coordinate ascent toward the hidden optimum."""
        t = self._state(state)
        obj = obs.objective
        strategy_shift = None
        if t["last_obj"] is not None and obj + IMPROVE_TOL < t["last_obj"]:
            # last move made replies worse — turn both dials around
            t["dir_tone"] *= -1
            t["dir_sen"] *= -1
            strategy_shift = (f"reply-rate dropped {t['last_obj']:.3f}→{obj:.3f} — reversing "
                              f"messaging + targeting direction")
        t["last_obj"] = obj

        reason = (f"reply-rate {obj:.1%}; "
                  f"{'reversing — last tweak hurt' if strategy_shift else 'continuing — last tweak helped'}")
        return Correction(
            adjustments={
                "message_tone": {"move": "warmer" if t["dir_tone"] > 0 else "formal", "reason": reason},
                "targeting_seniority": {"move": "senior" if t["dir_sen"] > 0 else "junior", "reason": reason},
            },
            rationale=reason,
            strategy_shift=strategy_shift,
        )
