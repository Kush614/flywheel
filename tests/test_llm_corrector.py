"""M2 — Claude as the corrector. We inject a fake Anthropic client so the
wiring is tested without a live API key.

Acceptance (§9 M2): Plan events carry a stated cause per adjustment, and the
loop degrades to the rule-based brain when the LLM is unusable.
"""
from loopkit import LoopEngine, EventBus
from loopkit.core import LoopState
from loopkit.detectors import ThrashDetector
from loopkit.budget import ExploreExploitBudgeter
from plugins.marketing import MarketingPlugin
from sim.market import MarketSimulator


class FakeLLM:
    """Stands in for AnthropicClient. Returns a fixed decision for each keyword."""

    def __init__(self, move="hold", available=True, broken=False):
        self.move = move
        self.available = available
        self.broken = broken
        self.calls = 0

    def invoke_json(self, user, system="", max_tokens=700):
        self.calls += 1
        if self.broken:
            return None  # simulate a failed / unparseable reply
        import json
        data = json.loads(user)
        return {
            "keywords": {
                name: {"move": self.move, "cause": f"claude decided {self.move} on {name}"}
                for name in data["keywords"]
            },
            "strategy_shift": None,
        }


def _run(llm, periods=4):
    bus = EventBus()
    sim = MarketSimulator(seed=7)
    plugin = MarketingPlugin(sim, ExploreExploitBudgeter(), llm=llm)
    engine = LoopEngine(bus, detector=ThrashDetector(stagnation_periods=30),
                        budgeter=plugin.budgeter, initial_budget=3000.0)
    state = engine.run(plugin, periods)
    return bus, state


def test_claude_corrector_drives_causes():
    llm = FakeLLM(move="raise")
    bus, _ = _run(llm, periods=4)
    assert llm.calls >= 1, "Claude corrector should have been called"
    corrections = [e for e in bus.snapshot() if e["kind"] == "correct"]
    # after the first period, corrections come from the fake LLM
    later = corrections[-1]
    assert "Claude" in later["rationale"]
    for adj in later["adjustments"].values():
        assert "claude decided" in adj["reason"]
    # and the plan that follows carries those causes
    plans = [e for e in bus.snapshot() if e["kind"] == "plan"]
    assert any(p["cause_hypotheses"] for p in plans)


def test_falls_back_when_llm_unavailable():
    bus, _ = _run(FakeLLM(available=False), periods=3)
    corrections = [e for e in bus.snapshot() if e["kind"] == "correct"]
    # no "Claude" rationale — the rule-based corrector ran
    assert corrections and all("Claude" not in c["rationale"] for c in corrections)


def test_falls_back_when_reply_unusable():
    llm = FakeLLM(broken=True)
    bus, _ = _run(llm, periods=3)
    assert llm.calls >= 1  # it tried Claude
    corrections = [e for e in bus.snapshot() if e["kind"] == "correct"]
    # ...but every correction came from the rules, not Claude
    assert all("Claude" not in c["rationale"] for c in corrections)
