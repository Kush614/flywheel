"""loopkit — a domain-agnostic plan -> act -> observe -> correct loop engine.

Everything else in Flywheel is a plugin. The engine knows nothing about
marketing, recruiting, bids or keywords. It runs any object that satisfies the
LoopPlugin protocol, emits four events per cycle, and refuses to thrash forever.
"""
from .core import (
    LoopState,
    Plan,
    ActResult,
    Observation,
    Correction,
    LoopPlugin,
    LoopEngine,
)
from .events import (
    Event,
    PlanEvent,
    ActEvent,
    ObserveEvent,
    CorrectEvent,
    HaltEvent,
    EventBus,
)
from .detectors import ThrashDetector, HaltDecision
from .budget import ExploreExploitBudgeter

__all__ = [
    "LoopState",
    "Plan",
    "ActResult",
    "Observation",
    "Correction",
    "LoopPlugin",
    "LoopEngine",
    "Event",
    "PlanEvent",
    "ActEvent",
    "ObserveEvent",
    "CorrectEvent",
    "HaltEvent",
    "EventBus",
    "ThrashDetector",
    "HaltDecision",
    "ExploreExploitBudgeter",
]
