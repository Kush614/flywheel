"""Loop A acceptance (§5.4): the cost-per-conversion curve bends down over
>=12 periods in sim mode, and the dud is cut via a cause hypothesis (not a
bid raise)."""
from loopkit import LoopEngine, EventBus
from loopkit.detectors import ThrashDetector
from loopkit.budget import ExploreExploitBudgeter
from plugins.marketing import MarketingPlugin
from sim.market import MarketSimulator


def _run(periods=15):
    bus = EventBus()
    sim = MarketSimulator(seed=7)
    plugin = MarketingPlugin(sim, ExploreExploitBudgeter())
    engine = LoopEngine(bus, detector=ThrashDetector(stagnation_periods=6),
                        budgeter=plugin.budgeter, initial_budget=3000.0)
    state = engine.run(plugin, periods)
    return bus, state, plugin


def test_curve_bends_down_over_12_periods():
    bus, state, _ = _run(15)
    objs = state.objective_history
    assert len(objs) >= 12, "need at least 12 periods of signal"
    # conversions-per-dollar should end meaningfully higher than it started
    assert objs[-1] > objs[0], "conv/$ should improve (cost/conv should fall)"
    improvement = (objs[-1] - objs[0]) / objs[0]
    assert improvement > 0.05, f"expected >5% improvement, got {improvement:.1%}"


def test_deterministic():
    _, s1, _ = _run(12)
    _, s2, _ = _run(12)
    assert s1.objective_history == s2.objective_history, "sim must be reproducible"


def test_dud_is_cut_not_raised():
    """cheap-widgets is a value-0.10 dud. The agent must diagnose it as
    relevance-limited and cut its bid, NOT raise it."""
    bus, state, _ = _run(12)
    corrections = [e for e in bus.snapshot() if e["kind"] == "correct"]
    # look at the final few corrections for cheap-widgets
    last = corrections[-1]["adjustments"]["cheap-widgets"]
    assert last["move"] in ("cut", "cut_hard"), f"dud should be cut, got {last['move']}"
    assert "relevance" in last["reason"].lower() or "creative" in last["reason"].lower()
    # and its final bid should be near the floor, well below where it started
    assert state.memory["bids"]["cheap-widgets"] < 1.0


def test_plan_carries_cause_hypotheses():
    """Not a thermostat: every plan states a cause per adjustment."""
    bus, _, _ = _run(6)
    plans = [e for e in bus.snapshot() if e["kind"] == "plan"]
    assert plans
    for p in plans:
        assert p["cause_hypotheses"], "each plan must carry cause hypotheses"
