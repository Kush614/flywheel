"""Anthropic API seam — Claude as the planner / corrector (replaces Bedrock).

Per the project decision, Claude is reached through the Anthropic API directly
(no AWS in the middle). It's called over stdlib `urllib` — no SDK dependency —
to honour Flywheel's zero-dependency core: the marketing loop still runs with
nothing installed; Claude is an *optional* upgrade to the reasoning step.

Credentials come from a CLI, matching the rest of the sponsors (Zero, Nexla):
  1. `ANTHROPIC_API_KEY` if set (x-api-key), else
  2. the `ant` CLI profile from `ant auth login` — we fetch a short-lived token
     with `ant auth print-credentials --access-token` and send it as a Bearer
     token (with the `anthropic-beta: oauth-2025-04-20` header, per the docs).
When neither is present, `available` is False and the loop falls back to the
rule-based brain — the demo never breaks for a missing key.

API shape (verified against the current Anthropic docs):
  POST https://api.anthropic.com/v1/messages
  headers: (x-api-key | Authorization: Bearer), anthropic-version: 2023-06-01
  body:    {model, max_tokens, system, messages:[{role:"user",content:"..."}]}
Model defaults to claude-opus-4-8. NOTE: temperature/top_p/top_k are rejected on
Opus 4.8 / Sonnet 5 (400) — we never send them. For a fast high-frequency loop
set ANTHROPIC_MODEL=claude-haiku-4-5 (or claude-sonnet-5).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import urllib.error
import urllib.request

API_URL = "https://api.anthropic.com/v1/messages"
DEFAULT_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-opus-4-8")

_ANT_WIN = r"E:\npm-global\ant.exe"


def _find_ant() -> str | None:
    on_path = shutil.which("ant")
    if on_path:
        return on_path
    for cand in (_ANT_WIN, os.path.expanduser("~/.local/bin/ant")):
        if os.path.exists(cand):
            return cand
    return None


class AnthropicClient:
    def __init__(self, model: str | None = None, timeout: int = 30):
        self.model = model or os.environ.get("ANTHROPIC_MODEL", DEFAULT_MODEL)
        self.timeout = timeout
        self.ant = _find_ant()
        # resolve the credential source once: 'key' | 'ant' | None
        if os.environ.get("ANTHROPIC_API_KEY"):
            self.mode = "key"
        elif self.ant and self._ant_token() is not None:
            self.mode = "ant"
        else:
            self.mode = None

    @property
    def available(self) -> bool:
        return self.mode is not None

    def _ant_token(self) -> str | None:
        """Fetch a fresh short-lived OAuth access token via the ant CLI."""
        if not self.ant:
            return None
        try:
            p = subprocess.run(
                [self.ant, "auth", "print-credentials", "--access-token"],
                capture_output=True, text=True, timeout=20,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        if p.returncode != 0:
            return None
        token = (p.stdout or "").strip()
        return token or None

    def _headers(self) -> dict | None:
        base = {"anthropic-version": "2023-06-01", "content-type": "application/json"}
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if api_key:
            base["x-api-key"] = api_key
            return base
        token = self._ant_token()
        if token:
            base["authorization"] = f"Bearer {token}"
            base["anthropic-beta"] = "oauth-2025-04-20"
            return base
        return None

    def invoke(self, user: str, *, system: str = "", max_tokens: int = 700) -> str | None:
        """Return Claude's text response, or None if unavailable/failed."""
        headers = self._headers()
        if headers is None:
            return None
        body = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": user}],
        }
        if system:
            body["system"] = system
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(API_URL, data=data, method="POST", headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError):
            return None
        # content is a list of blocks; concatenate the text blocks
        parts = payload.get("content") or []
        text = "".join(b.get("text", "") for b in parts if b.get("type") == "text")
        return text or None

    def invoke_json(self, user: str, *, system: str = "", max_tokens: int = 700) -> dict | None:
        """Invoke and parse a JSON object out of the reply (tolerates ```json fences)."""
        text = self.invoke(user, system=system, max_tokens=max_tokens)
        if not text:
            return None
        return _extract_json(text)


def _extract_json(text: str) -> dict | None:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        return None
    try:
        obj = json.loads(text[start:end + 1])
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        return None


if __name__ == "__main__":
    from integrations.env import load_dotenv
    load_dotenv()
    c = AnthropicClient()
    print("model:", c.model, "ant:", c.ant, "cred source:", c.mode, "available:", c.available)
    if c.available:
        print(c.invoke("Reply with exactly: pong", max_tokens=16))
    else:
        print("Not authenticated. Run:  ant auth login   (or set ANTHROPIC_API_KEY)")
