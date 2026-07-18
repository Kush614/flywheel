"""Zero.xyz creative discovery — the §6.2 moment, wired into Loop A.

When Loop A diagnoses a keyword as *relevance-limited* (it wins clicks that
don't convert — a creative problem, not a price problem), the right fix is a
new ad creative, not a higher bid. But the agent has no creative-generation
capability and no API key for one. So it **discovers** a service through Zero
(keyless, x402 wallet) and can call it on the spot.

Runs in a background thread so the loop never blocks on the network. Emits
`creative` events onto the same bus the dashboard watches, so the discovery is
visible live. Any *paid* call passes the Pomerium gate first (§6.2: "every
money-spending call passes the Pomerium gate") — even free ones are audited.

Discovery (search/get) is free and always safe. Calling a capability spends from
the wallet, so by default we only attempt FREE capabilities with a $0 cap; set
FLYWHEEL_ZERO_CALL=0 to discover-only.
"""
from __future__ import annotations

import os
import re
import threading

from integrations.zero import ZeroClient


class ZeroCreativeService:
    def __init__(self, bus, zero: ZeroClient | None = None, gate=None,
                 enable_calls: bool | None = None):
        self.bus = bus
        self.zero = zero or ZeroClient()
        self.gate = gate
        if enable_calls is None:
            enable_calls = os.environ.get("FLYWHEEL_ZERO_CALL", "1") != "0"
        self.enable_calls = enable_calls
        # per-call spend cap (USDC). With a funded wallet this enables LIVE
        # generation; 0 keeps it to free capabilities only.
        self.max_pay = float(os.environ.get("ZERO_MAX_PAY", "0.15"))
        self._requested: set[str] = set()
        self._lock = threading.Lock()

    def request(self, keyword: str, cause: str, period: int) -> None:
        """Fire-and-forget: discover (and maybe generate) a creative for a dud."""
        with self._lock:
            if keyword in self._requested:
                return
            self._requested.add(keyword)
        threading.Thread(target=self._work, args=(keyword, cause, period), daemon=True).start()

    # ----------------------------------------------------------------------
    def _emit(self, period: int, payload: dict) -> None:
        ev = {"kind": "creative", "loop": "marketing", "period": period}
        ev.update(payload)
        self.bus.publish_raw(ev)

    def _work(self, keyword: str, cause: str, period: int) -> None:
        if not self.zero.available:
            self._emit(period, {"stage": "unavailable", "keyword": keyword,
                                "note": "Zero CLI not installed — skipping creative discovery"})
            return

        self._emit(period, {"stage": "discovering", "keyword": keyword,
                            "note": f"'{keyword}' is relevance-limited — discovering an ad-creative "
                                    f"service via Zero (no API key, x402 wallet)"})

        res = self.zero.search(f"generate ad creative image for {keyword}", limit=6)
        if not res.ok or not res.data:
            self._emit(period, {"stage": "unavailable", "keyword": keyword,
                                "note": res.detail or "no capabilities found"})
            return

        caps = [{"token": c.token, "name": c.name, "cost": str(c.cost)} for c in res.data[:4]]
        self._emit(period, {"stage": "discovered", "keyword": keyword, "capabilities": caps,
                            "note": f"discovered {len(caps)} creative services with no pre-wired keys"})

        if not self.enable_calls:
            return

        # prefer capabilities that actually look like image generators
        candidates = [c for c in res.data if _looks_like_image_gen(c)] or res.data

        # money-spend passes the Pomerium gate first (capped at max_pay)
        if self.gate is not None:
            decision = self.gate.authorize(
                {"target": f"zero:creative:{keyword}", "new_bid": self.max_pay,
                 "issued_period": period}, period)
            if not decision.allowed:
                self._emit(period, {"stage": "blocked", "keyword": keyword, "note": decision.reason})
                return

        prompt = (f"On-brand ad creative photo for '{keyword}', premium advertising "
                  f"photography, vibrant, high conversion. No text.")
        last_detail = ""
        for top in candidates[:3]:  # try a few; stop on the first real image
            self._emit(period, {"stage": "generating", "keyword": keyword, "capability": top.name,
                                "note": f"paying via x402 to generate a new ad through '{top.name}' "
                                        f"(cap ${self.max_pay:.2f}, no API key)"})
            fr = self.zero.fetch(top.token, {"prompt": prompt}, max_pay=self.max_pay)
            if fr.ok:
                img, paid = _extract_image_and_cost(fr.data)
                if img:
                    self._emit(period, {"stage": "generated", "keyword": keyword, "capability": top.name,
                                        "image": img, "paid": paid,
                                        "note": f"generated a fresh ad via '{top.name}' — paid ${paid} "
                                                f"from the x402 wallet, no API key"})
                    return
                last_detail = "ok but no image URL"
            else:
                last_detail = fr.detail
        self._emit(period, {"stage": "call_skipped", "keyword": keyword,
                            "note": f"discovery + x402 pay attempted; using prebuilt creative "
                                    f"({last_detail[:60]})"})


def _find_image_url(obj, depth=0):
    if depth > 5:
        return None
    if isinstance(obj, str):
        m = re.search(r'https?://\S+?\.(?:png|jpe?g|webp|gif)', obj, re.I)
        return m.group(0) if m else None
    if isinstance(obj, dict):
        for k in ("url", "image_url", "imageUrl", "image", "output_url", "result_url",
                  "cdn_url", "output", "result"):
            v = obj.get(k)
            if isinstance(v, str) and v.startswith("http"):
                return v
        # arrays of image URLs (e.g. withzero GPT-5 image: {"images": [url,...]})
        for k in ("images", "urls", "data", "outputs"):
            v = obj.get(k)
            if isinstance(v, list):
                for it in v:
                    if isinstance(it, str) and it.startswith("http"):
                        return it
                    if isinstance(it, dict):
                        for kk in ("url", "image_url", "b64", "cdn_url"):
                            u = it.get(kk)
                            if isinstance(u, str) and u.startswith("http"):
                                return u
        for v in obj.values():
            r = _find_image_url(v, depth + 1)
            if r:
                return r
    if isinstance(obj, list):
        for v in obj:
            r = _find_image_url(v, depth + 1)
            if r:
                return r
    return None


def _extract_image_and_cost(data):
    """Pull the generated image URL + amount paid out of a Zero fetch response."""
    paid = "0"
    img = None
    if isinstance(data, dict):
        pay = data.get("payment") or {}
        paid = str(pay.get("amount", paid))
        img = _find_image_url(data.get("body", data))
    else:
        img = _find_image_url(data)
    return img, paid


_IMG_WORDS = ("image", "photo", "creative", "picture", "art", "visual", "render",
              "diffusion", "flux", "stable", "dall", "imagen", "grok", "seedream",
              "text-to-image", "generate")


def _looks_like_image_gen(cap) -> bool:
    t = (getattr(cap, "name", "") + " " + getattr(cap, "description", "")).lower()
    return any(w in t for w in _IMG_WORDS)
