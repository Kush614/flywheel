"""Zero.xyz seam — keyless API discovery + x402 micropayments.

The agent hits a capability it lacks ("generate a new ad creative") and, instead
of a hand-wired API key, *discovers* a service through Zero and calls it, paying
pennies from an x402 wallet. This wraps the real `zero` CLI (proven live in this
repo: `zero auth agent register` → wallet, `zero search`, `zero get`, `zero
fetch`, `zero review`).

Design rules:
  * Never blocks the core loop. If the CLI is missing or unauthenticated, every
    method returns a structured "unavailable" result and the marketing loop
    carries on — Zero is a *flourish*, not the data feed (§6.2 / risk register).
  * search / get are free. `fetch` spends money, so it always passes a hard
    `--max-pay` cap and, in the full system, routes through the Pomerium gate
    (M4). Nothing here spends without an explicit max_pay.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field


def _find_runner() -> list[str] | None:
    """Resolve the zero runner per Zero's documented precedence."""
    if os.environ.get("ZERO_RUNNER"):
        return [os.environ["ZERO_RUNNER"]]
    on_path = shutil.which("zero")
    if on_path:
        return [on_path]
    # well-known install locations (this repo installed to E:\npm-global)
    for cand in (r"E:\npm-global\zero.cmd", r"E:\npm-global\zero",
                 os.path.expanduser("~/.zero/runtime/bin/zero")):
        if os.path.exists(cand):
            return [cand]
    if shutil.which("npx"):
        return ["npx", "-y", "@zeroxyz/cli@latest"]
    return None


@dataclass
class Capability:
    token: str
    name: str
    cost: str
    description: str
    slug: str = ""
    raw: dict = field(default_factory=dict)


@dataclass
class ZeroResult:
    ok: bool
    detail: str = ""
    data: dict | list | None = None


class ZeroClient:
    def __init__(self, timeout: int = 90):
        self.runner = _find_runner()
        self.timeout = timeout

    @property
    def available(self) -> bool:
        return self.runner is not None

    def _run(self, args: list[str]) -> subprocess.CompletedProcess | None:
        if not self.runner:
            return None
        try:
            return subprocess.run(
                self.runner + args,
                capture_output=True, text=True, timeout=self.timeout,
                shell=False,
            )
        except (subprocess.TimeoutExpired, OSError):
            return None

    # --- discovery (free) --------------------------------------------------
    def search(self, query: str, *, free_only: bool = False, limit: int = 8) -> ZeroResult:
        if not self.available:
            return ZeroResult(False, "zero CLI not installed — skipping discovery")
        args = ["search", query, "--json", "--limit", str(limit)]
        if free_only:
            args.append("--free")
        proc = self._run(args)
        if not proc or proc.returncode != 0:
            return ZeroResult(False, (proc.stderr if proc else "no runner") or "search failed")
        try:
            data = json.loads(proc.stdout)
        except json.JSONDecodeError:
            return ZeroResult(False, "could not parse search output")
        caps = self._parse_caps(data)
        return ZeroResult(True, f"{len(caps)} capabilities found", caps)

    def get(self, identifier: str) -> ZeroResult:
        if not self.available:
            return ZeroResult(False, "zero CLI not installed")
        proc = self._run(["get", identifier, "--json"])
        if not proc or proc.returncode != 0:
            return ZeroResult(False, (proc.stderr if proc else "no runner") or "get failed")
        try:
            return ZeroResult(True, "ok", json.loads(proc.stdout))
        except json.JSONDecodeError:
            return ZeroResult(True, proc.stdout.strip())

    # --- invocation (spends money — always capped) -------------------------
    def fetch(self, capability: str, body: dict | None, *, max_pay: float) -> ZeroResult:
        """Call a capability. `max_pay` (USDC) is a HARD per-call cap; in the
        full system this call also passes the Pomerium budget gate."""
        if not self.available:
            return ZeroResult(False, "zero CLI not installed")
        if max_pay is None:
            return ZeroResult(False, "refusing to fetch without a max_pay cap")
        args = ["fetch", "--capability", capability, "--max-pay", str(max_pay), "--json"]
        if body is not None:
            args += ["-d", json.dumps(body)]
        proc = self._run(args)
        if not proc:
            return ZeroResult(False, "no runner")
        if proc.returncode != 0:
            return ZeroResult(False, proc.stderr.strip() or "fetch failed (funds? cap?)")
        try:
            return ZeroResult(True, "ok", json.loads(proc.stdout))
        except json.JSONDecodeError:
            return ZeroResult(True, proc.stdout.strip())

    def review(self, run_id: str, *, success: bool, accuracy: int = 4,
               value: int = 4, reliability: int = 4) -> ZeroResult:
        if not self.available:
            return ZeroResult(False, "zero CLI not installed")
        args = ["review", run_id, "--accuracy", str(accuracy),
                "--value", str(value), "--reliability", str(reliability)]
        args.append("--success" if success else "--failure")
        proc = self._run(args)
        ok = bool(proc and proc.returncode == 0)
        return ZeroResult(ok, (proc.stdout.strip() if proc else "no runner"))

    # --- helpers -----------------------------------------------------------
    @staticmethod
    def _parse_caps(data) -> list[Capability]:
        items = data if isinstance(data, list) else data.get("results") or data.get("capabilities") or []
        caps = []
        for it in items:
            if not isinstance(it, dict):
                continue
            caps.append(Capability(
                token=it.get("token") or it.get("attribution") or "",
                name=it.get("name") or it.get("title") or "",
                cost=str(it.get("cost") or it.get("price") or "?"),
                description=it.get("description") or it.get("summary") or "",
                slug=it.get("slug") or "",
                raw=it,
            ))
        return caps


if __name__ == "__main__":
    # smoke test against the live account
    c = ZeroClient()
    print("runner:", c.runner, "available:", c.available)
    r = c.search("generate ad creative image", limit=5)
    print(r.ok, r.detail)
    for cap in (r.data or [])[:5]:
        print(f"  {cap.token}  {cap.name}  [{cap.cost}]")
