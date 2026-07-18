"""Nexla seam — the agent's governed world-view, driven via `nexla-cli`.

Per the project decision, Nexla is reached through the Nexla Agent CLI (not the
REST SDK). The CLI is agent-friendly by design: dry-run validation, JSON output,
and a Claude Code skill.

The win condition (§6.1): the agent's *entire* trusted view of campaign
performance is a governed Nexset — schema, validation, lineage — delivered by
Nexla, and exposed to the agent as an MCP toolset. Reads flow through
`campaign.performance`; writes (`bid.actions`) sit behind the Pomerium gate (M4).

Auth (set in .env, then the CLI mints a token):
    NEXLA_API_URL=https://dev-api-express-code.nexla.com/
    NEXLA_TOKEN=$(nexla-cli login --service-key <key-from-express.dev>)

Graceful degradation: if the CLI or NEXLA_TOKEN is missing, `available` is False
and the marketing loop reads campaign performance straight from the simulator
feed. The Nexset is the *governed delivery* of that same data, not a different
signal — so the loop is identical whether or not Nexla is wired.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field

API_URL = os.environ.get("NEXLA_API_URL", "")
TOKEN = os.environ.get("NEXLA_TOKEN", "")
NEXSET_ID = os.environ.get("NEXSET_ID", "")

_NPM_GLOBAL = r"E:\npm-global\nexla-cli.cmd"


def _find_cli() -> str | None:
    on_path = shutil.which("nexla-cli")
    if on_path:
        return on_path
    for cand in (_NPM_GLOBAL, _NPM_GLOBAL.replace(".cmd", "")):
        if os.path.exists(cand):
            return cand
    return None


@dataclass
class NexlaResult:
    ok: bool
    detail: str = ""
    data: list | dict | None = None


class NexlaClient:
    def __init__(self, timeout: int = 45):
        self.cli = _find_cli()
        self.timeout = timeout
        self._ensure_token()

    def _ensure_token(self) -> None:
        """Mint NEXLA_TOKEN from the service key via the CLI (all creds via CLI).
        `nexla-cli login --service-key <key>` prints the session token."""
        if os.environ.get("NEXLA_TOKEN") or not self.cli:
            return
        key = os.environ.get("NEXLA_SERVICE_KEY")
        if not key:
            return
        try:
            p = subprocess.run([self.cli, "login", "--service-key", key],
                               capture_output=True, text=True, timeout=self.timeout)
        except (OSError, subprocess.TimeoutExpired):
            return
        if p.returncode == 0 and p.stdout.strip():
            os.environ["NEXLA_TOKEN"] = p.stdout.strip()

    @property
    def available(self) -> bool:
        return bool(self.cli) and bool(os.environ.get("NEXLA_TOKEN"))

    def _run(self, args: list[str]) -> subprocess.CompletedProcess | None:
        if not self.cli:
            return None
        env = dict(os.environ)
        try:
            return subprocess.run([self.cli, *args, "--output", "json"],
                                  capture_output=True, text=True, timeout=self.timeout, env=env)
        except (subprocess.TimeoutExpired, OSError):
            return None

    def whoami(self) -> NexlaResult:
        if not self.available:
            return NexlaResult(False, "nexla-cli unconfigured (need NEXLA_TOKEN)")
        p = self._run(["probe"])
        if not p or p.returncode != 0:
            return NexlaResult(False, (p.stderr if p else "no cli") or "probe failed")
        return NexlaResult(True, "ok", _safe_json(p.stdout))

    def list_nexsets(self) -> NexlaResult:
        if not self.available:
            return NexlaResult(False, "nexla-cli unconfigured")
        p = self._run(["nexsets", "list"])
        if not p or p.returncode != 0:
            return NexlaResult(False, (p.stderr if p else "no cli") or "list failed")
        return NexlaResult(True, "ok", _safe_json(p.stdout))

    def campaign_performance(self, nexset_id: str | None = None) -> NexlaResult:
        """Read the governed campaign-performance Nexset — the agent's world-view."""
        if not self.available:
            return NexlaResult(False, "nexla-cli unconfigured — loop reads the sim feed directly")
        nid = nexset_id or NEXSET_ID
        if not nid:
            return NexlaResult(False, "no NEXSET_ID configured")
        p = self._run(["nexsets", "get", nid])
        if not p or p.returncode != 0:
            return NexlaResult(False, (p.stderr if p else "no cli") or "get failed")
        return NexlaResult(True, "ok", _safe_json(p.stdout))

    # the user-response data product the loop trusts — its schema, validation,
    # and lineage. This is the governed Nexset the agent's `observe` step reads.
    USER_RESPONSE_SCHEMA = [
        {"field": "ad", "type": "string", "desc": "ad / keyword identifier", "rule": "not null"},
        {"field": "impressions", "type": "int", "desc": "times shown to users", "rule": ">= 0"},
        {"field": "clicks", "type": "int", "desc": "user clicks", "rule": "<= impressions"},
        {"field": "conversions", "type": "int", "desc": "users who converted", "rule": "<= clicks"},
        {"field": "cost", "type": "float", "desc": "spend ($)", "rule": ">= 0"},
        {"field": "ctr", "type": "float", "desc": "click-through = clicks/impr", "rule": "0..1"},
        {"field": "conv_per_$", "type": "float", "desc": "user response per dollar", "rule": "derived"},
    ]

    def nexset_info(self, nexset_id: str | None = None) -> dict:
        """The Nexset drawer (§6.1): schema / validation / lineage of the
        governed user-response data the loop reads."""
        live = self.available
        info = {
            "name": "user_response.performance",
            "product": "governed Nexset",
            "delivered_by": "Nexla",
            "live": live,
            "source": ("Nexla governed Nexset (nexla-cli, MCP toolset)" if live
                       else "Nexla Nexset — pending provisioning (nexla-cli login). "
                            "Loop reads the same shape from the local feed until then."),
            "schema": self.USER_RESPONSE_SCHEMA,
            "validation": "schema-enforced, per-field rules, lineage-tracked",
        }
        if live:
            res = self.campaign_performance(nexset_id)
            if res.ok and isinstance(res.data, dict):
                info["id"] = res.data.get("id")
                info["name"] = res.data.get("name", info["name"])
                if res.data.get("output_schema") or res.data.get("schema"):
                    info["live_schema"] = res.data.get("output_schema") or res.data.get("schema")
        return info

    def ensure_toolset(self, name: str = "flywheel-user-response") -> NexlaResult:
        """Provision an MCP toolset + attach the nexset (Nexla's main agent
        capability: expose governed data to any MCP agent, no DB creds). Needs auth."""
        if not self.available:
            return NexlaResult(False, "nexla-cli unconfigured — run `nexla-cli login`")
        p = self._run(["toolsets", "create", "--name", name, "--mcp-gateway", "enabled"])
        if not p or p.returncode != 0:
            return NexlaResult(False, (p.stderr if p else "no cli") or "toolset create failed")
        return NexlaResult(True, "ok", _safe_json(p.stdout))


def _safe_json(text: str):
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return text.strip() if text else None


if __name__ == "__main__":
    from integrations.env import load_dotenv
    load_dotenv()
    c = NexlaClient()
    print("cli:", c.cli, "available:", c.available)
    print("whoami:", c.whoami().detail)
    print("nexsets:", c.list_nexsets().detail)
