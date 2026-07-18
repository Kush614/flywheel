"""Event bus + the four (plus one) event types.

Every cycle emits PlanEvent, ActEvent, ObserveEvent, CorrectEvent. A HaltEvent
fires when the stop detector trips. The dashboard subscribes to the bus over
SSE — if a correction is not on the bus, it is not on screen, and per the spec
that means it did not happen.

The bus is thread-safe and fan-out: the engine runs in one thread, N SSE
clients each drain their own queue. A ring buffer of recent events lets a
client that connects late replay what it missed.
"""
from __future__ import annotations

import itertools
import queue
import threading
from dataclasses import dataclass, field, asdict
from typing import Any, Optional

_seq = itertools.count(1)


@dataclass
class Event:
    kind: str = "event"
    loop: str = ""
    period: int = 0
    seq: int = field(default_factory=lambda: next(_seq))

    def to_dict(self) -> dict:
        d = asdict(self)
        d["kind"] = self.kind
        return d


@dataclass
class PlanEvent(Event):
    kind: str = "plan"
    rationale: str = ""
    actions: list = field(default_factory=list)
    cause_hypotheses: dict = field(default_factory=dict)
    explore: list = field(default_factory=list)
    exploit: list = field(default_factory=list)
    budget_remaining: float = 0.0


@dataclass
class ActEvent(Event):
    kind: str = "act"
    applied: list = field(default_factory=list)
    blocked: list = field(default_factory=list)
    detail: dict = field(default_factory=dict)


@dataclass
class ObserveEvent(Event):
    kind: str = "observe"
    objective: float = 0.0
    signals: dict = field(default_factory=dict)
    classifications: dict = field(default_factory=dict)


@dataclass
class CorrectEvent(Event):
    kind: str = "correct"
    adjustments: dict = field(default_factory=dict)
    rationale: str = ""
    strategy_shift: Optional[str] = None


@dataclass
class HaltEvent(Event):
    kind: str = "halt"
    reason: str = ""
    detail: dict = field(default_factory=dict)


class EventBus:
    """Thread-safe fan-out bus with a replay ring buffer."""

    def __init__(self, history: int = 500):
        self._subscribers: list[queue.Queue] = []
        self._lock = threading.Lock()
        self._history: list[dict] = []
        self._history_max = history

    def publish(self, event: Event) -> None:
        self.publish_raw(event.to_dict())

    def publish_raw(self, payload: dict) -> None:
        """Publish an already-built payload dict (used for audit / curveball
        events that aren't Event dataclasses)."""
        with self._lock:
            self._history.append(payload)
            if len(self._history) > self._history_max:
                self._history.pop(0)
            subs = list(self._subscribers)
        for q in subs:
            try:
                q.put_nowait(payload)
            except queue.Full:
                pass  # slow client; drop rather than block the engine

    def subscribe(self, replay: bool = True) -> "queue.Queue[dict]":
        q: queue.Queue = queue.Queue(maxsize=1000)
        with self._lock:
            if replay:
                for payload in self._history:
                    try:
                        q.put_nowait(payload)
                    except queue.Full:
                        break
            self._subscribers.append(q)
        return q

    def unsubscribe(self, q: "queue.Queue[dict]") -> None:
        with self._lock:
            if q in self._subscribers:
                self._subscribers.remove(q)

    def snapshot(self) -> list[dict]:
        with self._lock:
            return list(self._history)
