"""M6 — Loop B (talent) acceptance. Reply-rate self-corrects upward, and the
SAME engine object runs both the marketing and talent plugins (generality)."""
from loopkit import LoopEngine, EventBus
from loopkit.detectors import ThrashDetector
from loopkit.budget import ExploreExploitBudgeter
from plugins.marketing import MarketingPlugin
from plugins.talent import TalentPlugin
from integrations.fillmore import FillmoreClient
from sim.market import MarketSimulator
from sim.talent import TalentSimulator


def test_reply_rate_bends_up():
    bus = EventBus()
    engine = LoopEngine(bus, detector=ThrashDetector(stagnation_periods=30))
    plugin = TalentPlugin(FillmoreClient(TalentSimulator(seed=11)), role="Growth Engineer")
    state = engine.run(plugin, 14)
    objs = state.objective_history
    assert len(objs) >= 12
    # best reply-rate reached should clear a meaningful bar above the start
    assert max(objs[3:]) > objs[0] + 0.05, "reply-rate should climb toward the optimum"


def test_same_engine_runs_marketing_and_talent():
    """Generality: one engine object drives both domains, unchanged."""
    engine = LoopEngine(EventBus(), detector=ThrashDetector(stagnation_periods=30))

    mkt = MarketingPlugin(MarketSimulator(seed=7), ExploreExploitBudgeter())
    s_mkt = engine.run(mkt, 6)

    tal = TalentPlugin(FillmoreClient(TalentSimulator(seed=11)))
    s_tal = engine.run(tal, 6)

    assert s_mkt.period >= 1 and s_tal.period >= 1
    # each produced its own ground-truth objective series
    assert s_mkt.objective_history and s_tal.objective_history
    # the two domains keep different state shapes on the same engine
    assert "bids" in s_mkt.memory and "talent" in s_tal.memory
    assert {"tone", "seniority"} <= set(tal._state(s_tal))


def test_fillmore_stub_reports_source():
    fc = FillmoreClient(TalentSimulator())
    assert "stub" in fc.source.lower()  # no FILLMORE_API_KEY -> simulated
    r = fc.run_outreach.__self__.sim.send(0.65, 0.55, 0)
    assert 0.0 <= r.reply_rate <= 1.0


def test_talent_deterministic():
    def run():
        e = LoopEngine(EventBus(), detector=ThrashDetector(stagnation_periods=30))
        return e.run(TalentPlugin(FillmoreClient(TalentSimulator(seed=11))), 10).objective_history
    assert run() == run()
