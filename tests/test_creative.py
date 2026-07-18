"""Zero creative-discovery service: fires once per relevance-limited keyword,
emits discovery events, and gates any spend through Pomerium. A fake Zero client
keeps it offline and deterministic."""
import time

from loopkit.events import EventBus
from integrations.creative import ZeroCreativeService
from integrations.pomerium import PolicyGate
from integrations.zero import Capability, ZeroResult


class FakeZero:
    available = True
    def __init__(self):
        self.searches = 0
        self.fetches = 0
    def search(self, q, free_only=False, limit=8):
        self.searches += 1
        return ZeroResult(True, "ok", [
            Capability(token="z_x.1", name="AdPrompt Creative", cost="Free", description="d"),
        ])
    def fetch(self, cap, body, max_pay):
        self.fetches += 1
        return ZeroResult(True, "ok", {"creative_url": "https://example/creative.png"})
    def review(self, *a, **k):
        return ZeroResult(True, "ok")


def _drain(bus):
    q = bus.subscribe(replay=True)
    out = []
    while not q.empty():
        out.append(q.get_nowait())
    return out


def test_discovers_and_generates_once():
    bus = EventBus()
    z = FakeZero()
    svc = ZeroCreativeService(bus, zero=z, gate=PolicyGate(), enable_calls=True)
    svc.request("cheap-widgets", "dud", period=3)
    svc.request("cheap-widgets", "dud", period=4)  # dedupe — same keyword
    time.sleep(0.3)  # let the background thread finish

    assert z.searches == 1, "should discover once per keyword (deduped)"
    events = [e for e in _drain(bus) if e["kind"] == "creative"]
    stages = {e["stage"] for e in events}
    assert "discovering" in stages and "discovered" in stages
    assert "generated" in stages  # free capability called through the gate


def test_discovery_only_when_calls_disabled():
    bus = EventBus()
    z = FakeZero()
    svc = ZeroCreativeService(bus, zero=z, gate=None, enable_calls=False)
    svc.request("cheap-widgets", "dud", period=1)
    time.sleep(0.3)
    assert z.fetches == 0  # no spend attempted
    stages = {e["stage"] for e in _drain(bus) if e["kind"] == "creative"}
    assert "discovered" in stages and "generated" not in stages
