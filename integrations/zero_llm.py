"""Zero-brokered LLM — replaces Adbox's Akamai inference (LIVE).

The agent pays (x402/mpp) for LLM inference through Zero — no Akamai, no keys.
Pinned to a capability verified to settle on the Tempo mpp rail the Zero credit
can actually pay: **Groq Chat (Llama 3.3 70B)**, ~$0.008/call. Used by the studio
to draft ad concepts from the ad's user-response context. Degrades to a local
drafter if the call fails, so the loop never stalls.
"""
from __future__ import annotations

import json
import os

from integrations.zero import ZeroClient

# pinned, verified live: Groq Chat via mpp on Tempo (~$0.008/call)
LLM_CAP = "groq-chat-0362cf4f"
LLM_MODEL = os.environ.get("ZERO_LLM_MODEL", "llama-3.3-70b-versatile")


class ZeroLLM:
    def __init__(self, zero: ZeroClient | None = None):
        self.zero = zero or ZeroClient()
        self.max_pay = float(os.environ.get("ZERO_LLM_MAX_PAY", "0.05"))

    @property
    def available(self) -> bool:
        return self.zero.available

    def chat(self, prompt: str) -> tuple[str | None, str]:
        """Return (assistant_text, paid). None text → caller falls back locally."""
        if not self.zero.available:
            return None, "0"
        body = {"model": LLM_MODEL,
                "messages": [{"role": "user", "content": prompt}]}
        fr = self.zero.fetch(LLM_CAP, body, max_pay=self.max_pay)
        if not fr.ok:
            return None, "0"
        paid = str((fr.data.get("payment") or {}).get("amount", "0")) if isinstance(fr.data, dict) else "0"
        return _extract_text(fr.data), paid


def _extract_text(data) -> str | None:
    """Pull assistant text from an OpenAI/Groq-shaped x402 response."""
    if not isinstance(data, dict):
        return data if isinstance(data, str) else None
    body = data.get("body", data)
    if isinstance(body, str):
        return body or None
    if not isinstance(body, dict):
        return None
    # Groq wraps as {"success":true,"data":{"choices":[...]}}
    inner = body.get("data") if isinstance(body.get("data"), dict) else body
    ch = inner.get("choices")
    if isinstance(ch, list) and ch:
        msg = ch[0].get("message") or {}
        if msg.get("content"):
            return msg["content"]
        if ch[0].get("text"):
            return ch[0]["text"]
    for k in ("text", "content", "output", "response", "completion", "result"):
        v = inner.get(k) or body.get(k)
        if isinstance(v, str) and v.strip():
            return v
    return None


def parse_json(text: str) -> dict | None:
    if not text:
        return None
    t = text.strip()
    if t.startswith("```"):
        t = t.split("```", 2)[1]
        t = t[4:] if t.startswith("json") else t
    s, e = t.find("{"), t.rfind("}")
    if s == -1 or e == -1:
        return None
    try:
        obj = json.loads(t[s:e + 1])
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        return None
