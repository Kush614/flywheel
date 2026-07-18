"""loopkit acceptance tests (§4.3).

  1. The engine runs an arbitrary plugin for K periods, emitting 4 events/period.
  2. A synthetic oscillation makes the detector fire and halt with a reason.
  3. The SAME engine object runs two different plugins (generality).
"""
from loopkit import LoopEngine, EventBus
from loopkit.core import Plan, ActResult, Observation, Correction, LoopState
from loopkit.detectors import ThrashDetector


# --------------------------------------------------------------------------
# Two minimal, unrelated plugins. If one engine runs both unchanged, the
# engine is genuinely domain-agnostic (not marketing-shaped).
# --------------------------------------------------------------------------
class CountingPlugin:
    """A plugin whose objective climbs forever — proves basic operation."""

    name = "counter"

    def plan(self, state):
        return Plan(actions=[{"target": "x", "delta": 1}], rationale="increment x")

    def act(self, plan, state):
        return ActResult(applied=plan.actions)

    def observe(self, act_result, state):
        return Observation(objective=float(state.period))  # strictly increasing

    def correct(self, state, obs):
        return Correction(adjustments={"x": "keep"}, rationale="keep going")


class TemperaturePlugin:
    """Totally different domain (a thermostat chasing a setpoint) — same API."""

    name = "thermostat"

    def __init__(self, setpoint=20.0):
        self.setpoint = setpoint

    def plan(self, state):
        temp = state.memory.get("temp", 10.0)
        delta = 1.0 if temp < self.setpoint else -1.0
        return Plan(actions=[{"target": "heater", "delta": delta}], rationale="approach setpoint")

    def act(self, plan, state):
        temp = state.memory.get("temp", 10.0) + plan.actions[0]["delta"]
        state.memory["temp"] = temp
        return ActResult(applied=plan.actions, detail={"temp": temp})

    def observe(self, act_result, state):
        temp = state.memory["temp"]
        # objective: closeness to setpoint (higher better), strictly improving
        return Observation(objective=-abs(temp - self.setpoint))

    def correct(self, state, obs):
        return Correction(rationale="adjust next period")


class OscillatingPlugin:
    """Deliberately thrashes: pushes a target up then down, up then down,
    all within a tiny band and with a flat objective. The detector must catch
    this and halt."""

    name = "oscillator"

    def plan(self, state):
        # alternate +0.02 / -0.02 on the same target — a reversal every period
        direction = 1 if state.period % 2 == 0 else -1
        return Plan(
            actions=[{"target": "cheap-widgets", "delta": 0.02 * direction}],
            rationale="thrashing on noise",
        )

    def act(self, plan, state):
        state.memory.setdefault("bids", {})["cheap-widgets"] = 1.0
        return ActResult(applied=plan.actions)

    def observe(self, act_result, state):
        return Observation(objective=0.5)  # flat — no real improvement

    def correct(self, state, obs):
        return Correction()


# --------------------------------------------------------------------------
def test_four_events_per_period():
    bus = EventBus()
    engine = LoopEngine(bus)
    engine.run(CountingPlugin(), periods=5)
    kinds = [e["kind"] for e in bus.snapshot()]
    for k in ("plan", "act", "observe", "correct"):
        assert kinds.count(k) == 5, f"expected 5 {k} events, got {kinds.count(k)}"


def test_oscillation_halts_with_reason():
    bus = EventBus()
    engine = LoopEngine(bus, detector=ThrashDetector(oscillation_band=0.05))
    state = engine.run(OscillatingPlugin(), periods=20)
    assert state.halted, "detector should have halted the thrashing loop"
    assert state.halt_reason, "halt must carry a human-readable reason"
    assert "cheap-widgets" in state.halt_reason
    # and a HaltEvent must be on the bus so the dashboard can show it
    assert any(e["kind"] == "halt" for e in bus.snapshot())
    # it must halt EARLY (caught the thrash), not run all 20 periods
    assert state.period < 20


def test_same_engine_runs_two_plugins():
    """Generality: one engine object, two unrelated domains, unchanged."""
    engine = LoopEngine(EventBus())

    s1 = engine.run(CountingPlugin(), periods=4)
    s2 = engine.run(TemperaturePlugin(setpoint=15.0), periods=8)

    assert s1.period >= 1 and s2.period >= 1
    # thermostat should have driven temperature toward the setpoint
    assert abs(s2.memory["temp"] - 15.0) <= 1.0


def test_stagnation_halts():
    """Objective that never improves triggers the stagnation stop."""
    class Flat:
        name = "flat"
        def plan(self, state): return Plan(actions=[], rationale="do nothing")
        def act(self, plan, state): return ActResult()
        def observe(self, act_result, state): return Observation(objective=1.0)
        def correct(self, state, obs): return Correction()

    engine = LoopEngine(EventBus(), detector=ThrashDetector(stagnation_periods=3))
    state = engine.run(Flat(), periods=15)
    assert state.halted
    assert "not improved" in state.halt_reason
