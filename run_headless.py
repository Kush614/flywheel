"""Headless run of Loop A — sanity check the curve bends down. No UI, no deps.

    py run_headless.py [periods]
"""
import sys

from loopkit import LoopEngine, EventBus
from loopkit.budget import ExploreExploitBudgeter
from plugins.marketing import MarketingPlugin
from sim.market import MarketSimulator


def main():
    periods = int(sys.argv[1]) if len(sys.argv) > 1 else 15
    bus = EventBus()
    sim = MarketSimulator(seed=7)
    plugin = MarketingPlugin(sim, ExploreExploitBudgeter())
    engine = LoopEngine(bus, initial_budget=2000.0)

    state = engine.run(plugin, periods)

    print(f"\n{'period':>6} {'conv/$':>8} {'cost/conv':>10} {'conversions':>12} {'cost':>10}")
    print("-" * 50)
    hist = bus.snapshot()
    observes = [e for e in hist if e["kind"] == "observe"]
    for e in observes:
        raw = None
        # find matching raw via signals aggregate
        obj = e["objective"]
        print(f"{e['period']:>6} {obj:>8.4f}", end="")
        print()

    # summarize using the plugin's stored objective history
    print("\nobjective (conv/$) by period:")
    for i, obj in enumerate(state.objective_history):
        bar = "#" * int(obj * 200)
        print(f"  p{i:>2} {obj:>7.4f} {bar}")

    first = state.objective_history[0] if state.objective_history else 0
    last = state.objective_history[-1] if state.objective_history else 0
    print(f"\nfirst conv/$ = {first:.4f}   last conv/$ = {last:.4f}   "
          f"improvement = {((last-first)/first*100) if first else 0:.0f}%")
    if state.halted:
        print(f"\nHALTED at period {state.period}: {state.halt_reason}")


if __name__ == "__main__":
    main()
