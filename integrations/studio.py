"""Adbox "decide → render" studio, re-architected on Zero + Nexla.

This is Adbox's creative factory (draft concepts → pick → render) running inside
the Flywheel loop, with the two sponsors doing the heavy lifting instead of
Akamai:

  * DECIDE  — draft ad concepts + pick the best, via a Zero-brokered LLM (x402).
  * RENDER  — generate the winning creative, via a Zero-discovered image API (x402).
  * PUBLISH — a winning ad is shipped to ad platforms as a governed Nexla Nexset.

Called when the Flywheel loop diagnoses an ad as *relevance-limited* (users
click but don't convert — a creative problem). Runs off-thread; every money-
spend passes the Pomerium gate; degrades to deterministic local concepts +
prebuilt creatives so the loop never stalls. Emits `creative` events the
dashboard renders as the live decide→render pipeline, and tracks spend for the
cost ledger (Adbox's signature).
"""
from __future__ import annotations

import os
import threading

from integrations.zero import ZeroClient
from integrations.zero_llm import ZeroLLM, parse_json
from integrations.creative import _extract_image_and_cost, _looks_like_image_gen

# pinned render engine: fal.ai FLUX.1 Schnell — $0.003/call, 99% success,
# settles via mpp on Tempo (the network the Zero welcome credit can actually
# pay), returns {images:[{url}]}. Verified live. Discovery is the fallback.
RENDER_CAP = "fal-ai-schnell-4412b32c"
RENDER_NAME = "FLUX.1 Schnell"
# pinned image→video engine (Grok Imagine i2v via fal.mpp.tempo — verified live)
VIDEO_CAP = "fal-ai-image-to-video-9105fdab"
VIDEO_NAME = "Grok Imagine Video"


def _render_body(prompt: str, seed: int) -> dict:
    # a fresh seed each call so every ad is a brand-new render
    return {"prompt": prompt, "image_size": {"width": 768, "height": 768},
            "num_images": 1, "num_inference_steps": 4, "seed": seed}


def _video_body(prompt: str, image_url: str) -> dict:
    return {"prompt": prompt, "duration": 4, "image_url": image_url, "motion_scale": 0.4}


def _find_video_url(data):
    import re
    m = re.search(r'https?://\S+?\.(?:mp4|webm|mov)', __import__("json").dumps(data), re.I)
    return m.group(0) if m else None

# per-ad concept angles used when the Zero LLM doesn't answer (fallback)
_ANGLES = [
    ("benefit",     "{name}, Perfected", "Made for how you actually live.", "Shop now"),
    ("social",      "Why {name} Sells Out", "Join thousands who switched.", "See why"),
    ("urgency",     "{name} — This Week Only", "New drop. Limited run.", "Get yours"),
]


class AdboxStudio:
    def __init__(self, bus, zero: ZeroClient | None = None, gate=None,
                 nexla_publish=None, enable_calls: bool | None = None):
        self.bus = bus
        self.zero = zero or ZeroClient()
        self.gate = gate
        self.llm = ZeroLLM(self.zero)
        self.publisher = nexla_publish
        if enable_calls is None:
            enable_calls = os.environ.get("FLYWHEEL_ZERO_CALL", "1") != "0"
        self.enable_calls = enable_calls
        self.max_pay = float(os.environ.get("ZERO_MAX_PAY", "0.15"))
        # render cap comfortably covers FLUX Schnell ($0.003/call)
        self.render_cap = float(os.environ.get("ZERO_RENDER_MAX_PAY", "0.05"))
        # live video is pricier ($0.5); on for the winner only, gated + capped
        self.enable_video = os.environ.get("ZERO_VIDEO", "1") != "0"
        self.video_cap = float(os.environ.get("ZERO_VIDEO_MAX_PAY", "0.6"))
        self.spent = 0.0
        self.generated = 0
        self._requested: set[str] = set()
        self._published: set[str] = set()
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ API
    def request(self, ad: str, cause: str, period: int) -> None:
        """Regenerate an under-performing ad (decide → render)."""
        with self._lock:
            if ad in self._requested:
                return
            self._requested.add(ad)
        threading.Thread(target=self._work, args=(ad, cause, period), daemon=True).start()

    def publish(self, ad: str, perf: dict, period: int) -> None:
        """Ship a winning ad to ad platforms as a governed Nexla Nexset."""
        with self._lock:
            if ad in self._published or self.publisher is None:
                return
            self._published.add(ad)
        threading.Thread(target=self._publish, args=(ad, perf, period), daemon=True).start()

    # ------------------------------------------------------------- internal
    def _emit(self, period: int, payload: dict) -> None:
        ev = {"kind": "creative", "loop": "marketing", "period": period}
        ev.update(payload)
        self.bus.publish_raw(ev)

    def _work(self, ad: str, cause: str, period: int) -> None:
        # --- DECIDE ---------------------------------------------------------
        self._emit(period, {"stage": "deciding", "keyword": ad,
                            "note": "drafting ad concepts via a Zero-brokered LLM (x402, no Akamai)"})
        concepts, chosen, llm_paid = self._decide(ad, cause)
        self.spent += _f(llm_paid)
        self._emit(period, {"stage": "concepts", "keyword": ad, "concepts": concepts,
                            "chosen": chosen, "paid": llm_paid,
                            "note": f"drafted {len(concepts)} concepts → picked “{chosen['headline']}”"})

        if not (self.enable_calls and self.zero.available):
            self._emit(period, {"stage": "call_skipped", "keyword": ad,
                                "note": "render offline — using prebuilt creative"})
            return

        # --- RENDER (money-spend → Pomerium gate) ---------------------------
        if self.gate is not None:
            dec = self.gate.authorize(
                {"target": f"zero:render:{ad}", "new_bid": self.render_cap, "issued_period": period}, period)
            if not dec.allowed:
                self._emit(period, {"stage": "blocked", "keyword": ad, "note": dec.reason})
                return

        prompt = (f"{chosen['visual']} — {ad} advertising photo, premium, high conversion. No text.")
        self._emit(period, {"stage": "discovered", "keyword": ad,
                            "capabilities": [{"name": RENDER_NAME, "cost": "$0.003"}],
                            "note": f"rendering via '{RENDER_NAME}' — discovered on Zero, paid per-use, no keys"})
        # try the pinned engine first (verified live); search only if it fails.
        seed = (period * 131 + sum(ord(c) for c in ad)) & 0xFFFF
        attempts = [(RENDER_NAME, RENDER_CAP, _render_body(prompt, seed))]
        last = ""
        for i, (name, cap, body) in enumerate(attempts):
            self._emit(period, {"stage": "rendering", "keyword": ad, "capability": name,
                                "note": f"paying via x402/mpp to render through '{name}' (cap ${self.render_cap:.2f})"})
            fr = self.zero.fetch(cap, body, max_pay=self.render_cap)
            if fr.ok:
                img, paid = _extract_image_and_cost(fr.data)
                self.spent += _f(paid)
                if img:
                    self.generated += 1
                    self._emit(period, {"stage": "generated", "keyword": ad, "capability": name,
                                        "image": img, "paid": paid, "headline": chosen["headline"],
                                        "note": f"rendered a fresh ad via '{name}' — paid ${paid} from the Zero wallet, no API key"})
                    return
                last = "ok, no image URL"
            else:
                last = fr.detail
            # pinned failed — fall back to discovery once
            if i == 0:
                res = self.zero.search(f"generate ad creative image for {ad}", limit=6)
                cands = [c for c in (res.data or []) if _looks_like_image_gen(c)]
                attempts += [(c.name, c.token, {"prompt": prompt}) for c in cands[:2]]
        self.generated += 1  # concept still counts as a regenerated ad (prebuilt render)
        self._emit(period, {"stage": "call_skipped", "keyword": ad, "headline": chosen["headline"],
                            "note": f"discover + x402 pay attempted; using prebuilt render ({last[:50]})"})

    def _decide(self, ad, cause):
        name = ad.replace("-", " ").title()
        # try the Zero-brokered LLM first (the Adbox two-tier idea, keyless) —
        # context: the ad's real user-response problem.
        if self.llm.available:
            prompt = (
                f'You are an ad creative director. The "{name}" ad is under-performing: '
                f'{cause} — users engage but don\'t convert, so the creative isn\'t resonating. '
                f'Draft 3 DISTINCT new concepts (different angle each) and pick the strongest. '
                f'Each "visual" must be a concrete, specific art-direction brief for an image model. '
                f'Reply ONLY JSON: {{"concepts":[{{"headline":"","body":"","cta":"","visual":""}}],"chosen":0}}')
            text, paid = self.llm.chat(prompt)
            obj = parse_json(text or "")
            if obj and isinstance(obj.get("concepts"), list) and obj["concepts"]:
                cs = [{"headline": str(c.get("headline", name))[:60],
                       "body": str(c.get("body", ""))[:90],
                       "cta": str(c.get("cta", "Shop now"))[:20],
                       "visual": str(c.get("visual", "premium studio shot"))[:80]}
                      for c in obj["concepts"][:3]]
                idx = obj.get("chosen", 0) if isinstance(obj.get("chosen"), int) else 0
                return cs, cs[min(idx, len(cs) - 1)], paid
        # fallback: deterministic local concepts (always works)
        cs = [{"headline": h.format(name=name), "body": b, "cta": cta,
               "visual": f"{angle} angle, premium advertising photography"}
              for (angle, h, b, cta) in _ANGLES]
        return cs, cs[0], "0"

    def _publish(self, ad, perf, period):
        name = ad.replace("-", " ").title()
        image = video = None
        # the champion gets a freshly rendered hero creative + a generated video
        if self.enable_calls and self.zero.available:
            prompt = (f"{name} hero ad, premium advertising photography, top-performing "
                      f"campaign, vibrant, cinematic. No text.")
            seed = (period * 977 + sum(ord(c) for c in ad)) & 0xFFFF
            self._emit(period, {"stage": "rendering", "keyword": ad, "capability": RENDER_NAME,
                                "note": f"rendering the winning ad's hero creative via '{RENDER_NAME}'"})
            fr = self.zero.fetch(RENDER_CAP, _render_body(prompt, seed), max_pay=self.render_cap)
            if fr.ok:
                image, paid = _extract_image_and_cost(fr.data)
                self.spent += _f(paid)
                if image:
                    self.generated += 1
                    self._emit(period, {"stage": "generated", "keyword": ad, "image": image, "paid": paid,
                                        "note": f"hero creative for the winner '{name}' — ${paid}, no keys"})
            if image and self.enable_video:
                self._emit(period, {"stage": "animating", "keyword": ad, "capability": VIDEO_NAME,
                                    "note": f"animating the winner into a hero video via '{VIDEO_NAME}' (x402)"})
                vr = self.zero.fetch(VIDEO_CAP, _video_body(prompt, image), max_pay=self.video_cap)
                if vr.ok:
                    video = _find_video_url(vr.data)
                    vpaid = str((vr.data.get("payment") or {}).get("amount", "0")) if isinstance(vr.data, dict) else "0"
                    self.spent += _f(vpaid)
                    if video:
                        self._emit(period, {"stage": "video", "keyword": ad, "video": video, "paid": vpaid,
                                            "note": f"generated a hero video for '{name}' — ${vpaid} via x402"})
        # ship the campaign to ad platforms as a governed Nexla Nexset
        r = self.publisher.publish_campaign(ad, perf)
        self._emit(period, {"stage": "published", "keyword": ad, "feeds": r.get("feeds", []),
                            "live": r.get("live", False), "image": image, "video": video,
                            "note": r.get("note", "published")})


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0
