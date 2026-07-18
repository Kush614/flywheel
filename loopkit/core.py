"""Core interfaces and the engine loop.

The engine is deliberately small. It orchestrates four steps per period, emits
an event for each, tracks rolling memory + budget, and consults a stop detector
after every cycle. It never inspects the *meaning* of a plan — that is the
plugin's job. This is what lets the same engine object drive marketing and
recruiting unchanged (see tests/test_generality.py).
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Optional, Protocol, runtime_checkable

from .events import (
    EventBus,
    PlanEvent,
    ActEvent,
    ObserveEvent,
    CorrectEvent,
    HaltEvent,
)
from .detectors import ThrashDetector
from .budget import ExploreExploitBudgeter


@dataclass
class LoopState:
    """Everything the plugin reasons over. The engine owns and mutates this."""

    period: int = 0
    memory: dict = field(default_factory=dict)        # rolling history
    budget_remaining: float = 0.0                     # for explore/exploit
    last_actions: list = field(default_factory=list)  # for thrash detection
    objective_history: list = field(default_factory=list)  # metric per period
    halted: bool = False
    halt_reason: Optional[str] = None


@dataclass
class Plan:
    """What to change and WHY. The 'why' is not optional — a plan without a
    cause hypothesis reads as a thermostat, and judges probe that."""

    actions: list                       # list of dicts, plugin-defined
    rationale: str                      # human-readable reasoning
    cause_hypotheses: dict = field(default_factory=dict)  # target -> cause
    explore: list = field(default_factory=list)  # targets probed to learn
    exploit: list = field(default_factory=list)  # targets bet on to earn
    meta: dict = field(default_factory=dict)


@dataclass
class ActResult:
    """Outcome of executing a plan — including anything a policy gate blocked."""

    applied: list = field(default_factory=list)   # actions that went through
    blocked: list = field(default_factory=list)   # actions denied by policy
    detail: dict = field(default_factory=dict)


@dataclass
class Observation:
    """Ground-truth signal pulled after acting. Never LLM-graded."""

    objective: float                    # the number we optimize (higher=better)
    signals: dict = field(default_factory=dict)   # per-target detail
    classifications: dict = field(default_factory=dict)  # cause tags
    raw: dict = field(default_factory=dict)


@dataclass
class Correction:
    """Reasoned adjustment for next period — revert / hold / re-strategize."""

    adjustments: dict = field(default_factory=dict)  # target -> new intent
    rationale: str = ""
    strategy_shift: Optional[str] = None             # set when strategy changes


@runtime_checkable
class LoopPlugin(Protocol):
    """A domain plugs into the engine by implementing these four steps."""

    name: str

    def plan(self, state: LoopState) -> Plan: ...
    def act(self, plan: Plan, state: LoopState) -> ActResult: ...
    def observe(self, act_result: ActResult, state: LoopState) -> Observation: ...
    def correct(self, state: LoopState, obs: Observation) -> Correction: ...


class LoopEngine:
    """Runs an arbitrary LoopPlugin for K periods.

    Guarantees per the spec (§4.2):
      1. Four events emitted every cycle onto the bus.
      2. A thrash/stop detector that can halt with a logged reason.
      3. Budget surfaced so plugins can trade explore vs exploit.
    """

    def __init__(
        self,
        bus: Optional[EventBus] = None,
        *,
        detector: Optional[ThrashDetector] = None,
        budgeter: Optional[ExploreExploitBudgeter] = None,
        period_delay: float = 0.0,
        initial_budget: float = 1000.0,
    ):
        self.bus = bus or EventBus()
        self.detector = detector or ThrashDetector()
        self.budgeter = budgeter or ExploreExploitBudgeter()
        self.period_delay = period_delay
        self.initial_budget = initial_budget

    def run(self, plugin: LoopPlugin, periods: int, state: Optional[LoopState] = None) -> LoopState:
        """Drive one plugin for `periods` cycles (or until it halts)."""
        state = state or LoopState(budget_remaining=self.initial_budget)

        for _ in range(periods):
            if state.halted:
                break
            self.step(plugin, state)
            if self.period_delay:
                time.sleep(self.period_delay)

        return state

    def step(self, plugin: LoopPlugin, state: LoopState) -> None:
        """Execute exactly one plan/act/observe/correct cycle."""
        loop_name = getattr(plugin, "name", plugin.__class__.__name__)

        # --- PLAN ------------------------------------------------------------
        plan = plugin.plan(state)
        self.bus.publish(
            PlanEvent(
                loop=loop_name,
                period=state.period,
                rationale=plan.rationale,
                actions=plan.actions,
                cause_hypotheses=plan.cause_hypotheses,
                explore=plan.explore,
                exploit=plan.exploit,
                budget_remaining=state.budget_remaining,
            )
        )

        # --- ACT -------------------------------------------------------------
        act_result = plugin.act(plan, state)
        self.bus.publish(
            ActEvent(
                loop=loop_name,
                period=state.period,
                applied=act_result.applied,
                blocked=act_result.blocked,
                detail=act_result.detail,
            )
        )
        # record actions for thrash detection (target + direction)
        for a in act_result.applied:
            state.last_actions.append(a)

        # --- OBSERVE ---------------------------------------------------------
        obs = plugin.observe(act_result, state)
        state.objective_history.append(obs.objective)
        self.bus.publish(
            ObserveEvent(
                loop=loop_name,
                period=state.period,
                objective=obs.objective,
                signals=obs.signals,
                classifications=obs.classifications,
            )
        )

        # --- CORRECT ---------------------------------------------------------
        correction = plugin.correct(state, obs)
        self.bus.publish(
            CorrectEvent(
                loop=loop_name,
                period=state.period,
                adjustments=correction.adjustments,
                rationale=correction.rationale,
                strategy_shift=correction.strategy_shift,
            )
        )
        # fold the correction into memory so next plan sees it
        state.memory.setdefault("corrections", []).append(correction.adjustments)

        # --- STOP DETECTOR ---------------------------------------------------
        decision = self.detector.evaluate(state)
        if decision.halt:
            state.halted = True
            state.halt_reason = decision.reason
            self.bus.publish(
                HaltEvent(
                    loop=loop_name,
                    period=state.period,
                    reason=decision.reason,
                    detail=decision.detail,
                )
            )

        state.period += 1
