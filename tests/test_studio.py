"""Adbox-on-Zero+Nexla: the decide→render studio and the Nexla publish pipeline.
Tested on the offline fallback path (deterministic, no wallet/network)."""
import os
import time

from loopkit.events import EventBus
from integrations.studio import AdboxStudio
from integrations.nexla_publish import NexlaPublisher


class FakeZero:
    available = False   # forces the local-concept + prebuilt-render fallback


def _drain(bus):
    q = bus.subscribe(replay=True)
    out = []
    while not q.empty():
        out.append(q.get_nowait())
    return out


def test_decide_render_fallback():
    bus = EventBus()
    studio = AdboxStudio(bus, zero=FakeZero())
    studio.request("running-shoes", "clicks don't convert", period=2)
    studio.request("running-shoes", "dup", period=3)  # dedupe
    time.sleep(0.3)

    stages = [e["stage"] for e in _drain(bus) if e["kind"] == "creative"]
    assert "deciding" in stages          # DECIDE ran (Adbox two-tier idea)
    assert "concepts" in stages          # concepts drafted + one chosen
    assert "call_skipped" in stages      # render offline -> prebuilt
    # the chosen concept carries a real headline
    ev = [e for e in _drain(bus) if e.get("stage") == "concepts"]


def test_concepts_have_headlines():
    bus = EventBus()
    studio = AdboxStudio(bus, zero=FakeZero())
    studio.request("premium-watches", "dud", 1)
    time.sleep(0.3)
    concepts = [e for e in _drain(bus) if e.get("stage") == "concepts"]
    assert concepts
    c = concepts[0]
    assert len(c["concepts"]) == 3 and c["chosen"]["headline"]


def test_nexla_publish_builds_platform_feeds(tmp_path):
    pub = NexlaPublisher(nexla=None)   # not authed -> local feeds, push pending
    r = pub.publish_campaign("running-shoes", {"conversions": 12, "ctr": "0.21"})
    assert r["live"] is False
    platforms = {f["platform"] for f in r["feeds"]}
    assert {"Shopify", "Google Merchant", "Meta Catalog"} <= platforms
    # the feed files were actually written under /media/campaigns/
    base = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                        "dashboard", "static", "media", "campaigns", "running-shoes")
    assert os.path.exists(os.path.join(base, "shopify.csv"))
    with open(os.path.join(base, "shopify.csv"), encoding="utf-8") as f:
        assert "Running Shoes" in f.read()


def test_studio_publish_emits_event():
    bus = EventBus()
    studio = AdboxStudio(bus, zero=FakeZero(), nexla_publish=NexlaPublisher(nexla=None))
    studio.publish("blue-sneakers", {"conversions": 9, "ctr": "0.2"}, period=5)
    time.sleep(0.3)
    pub = [e for e in _drain(bus) if e.get("stage") == "published"]
    assert pub and pub[0]["feeds"] and "Nexla" in pub[0]["note"]
