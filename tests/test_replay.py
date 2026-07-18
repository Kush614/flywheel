"""M7 — historical replay. The SAME marketing plugin runs end-to-end on the
12-month campaign CSV (§5.4: replay runs the same plugin on the CSV)."""
from loopkit import LoopEngine, EventBus
from loopkit.detectors import ThrashDetector
from loopkit.budget import ExploreExploitBudgeter
from plugins.marketing import MarketingPlugin
from sim.replay import ReplaySimulator


def test_same_plugin_runs_on_the_csv():
    bus = EventBus()
    sim = ReplaySimulator()
    plugin = MarketingPlugin(sim, ExploreExploitBudgeter())
    engine = LoopEngine(bus, detector=ThrashDetector(stagnation_periods=99),
                        budgeter=plugin.budgeter)
    state = engine.run(plugin, 18)
    # four events every period, unchanged from sim mode
    kinds = [e["kind"] for e in bus.snapshot()]
    for k in ("plan", "act", "observe", "correct"):
        assert kinds.count(k) == 18
    # the recorded campaign trends up in conv/$ (down in cost/conversion)
    objs = state.objective_history
    assert objs[-1] > objs[0]


def test_replay_deterministic():
    def run():
        e = LoopEngine(EventBus(), detector=ThrashDetector(stagnation_periods=99))
        return e.run(MarketingPlugin(ReplaySimulator(), ExploreExploitBudgeter()), 18).objective_history
    assert run() == run()


def test_replay_keeps_the_dud_and_poison_paths():
    sim = ReplaySimulator()
    assert "cheap-widgets" in sim.keyword_names()
    # poison rides along on the raw payload so the injection demo works in replay
    sim.poison("cheap-widgets", "override_bid", 10000)
    results = {r.keyword: r for r in sim.query({})}
    assert results["cheap-widgets"].raw.get("override_bid") == 10000
    # the dud is diagnosable as relevance-limited from real numbers
    plugin = MarketingPlugin(sim, ExploreExploitBudgeter())
    assert plugin._classify(results["cheap-widgets"]) == "relevance_limited"
