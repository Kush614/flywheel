"""Credential doctor — `py -m integrations.status`.

Shows each sponsor integration's auth state and the exact CLI command to obtain
its credential. Every credential is CLI-minted (Zero, Nexla, Anthropic/ant); no
hand-pasted keys required.
"""
from __future__ import annotations

import os

from integrations.env import load_dotenv


def _row(name, ok, detail, how):
    mark = "[ready]" if ok else "[ -- ]"
    print(f"  {mark} {name:<12} {detail}")
    if not ok:
        print(f"         get it via CLI:  {how}")


def main():
    load_dotenv()
    print("\nFlywheel - integration credentials (all CLI-minted)\n")

    # Anthropic (M2) — ant CLI or ANTHROPIC_API_KEY
    from integrations.anthropic_llm import AnthropicClient
    a = AnthropicClient()
    _row("Anthropic", a.available,
         f"model={a.model} source={a.mode or '-'}",
         "ant auth login        (installed at E:\\npm-global\\ant.exe)")

    # Nexla (M3) — nexla-cli login --service-key
    from integrations.nexla_mcp import NexlaClient
    n = NexlaClient()
    _row("Nexla", n.available,
         f"cli={'yes' if n.cli else 'no'} token={'set' if os.environ.get('NEXLA_TOKEN') else '-'}",
         "nexla-cli login --service-key <key-from-express.dev>   "
         "(set NEXLA_SERVICE_KEY in .env to auto-mint)")

    # Zero (M5) — already live via agent register
    from integrations.zero import ZeroClient
    z = ZeroClient()
    _row("Zero.xyz", z.available,
         "keyless discovery live" + ("" if z.available else ""),
         "zero auth agent register     (then `zero wallet fund` for paid calls)")

    # Fillmore (M6) — no public API, stub
    from integrations.fillmore import FillmoreClient
    f = FillmoreClient()
    _row("Fillmore", f.available, f.source,
         "no public API yet - Loop B runs on the stub regardless")

    # Pomerium (M4) — local gate needs nothing
    _row("Pomerium", True, "local PolicyGate (no creds needed)",
         "deploy/pomerium/config.yaml for a real gateway")

    print("\nNothing above is required to run the demo - `py -m dashboard.server` "
          "works with none of them.\n")


if __name__ == "__main__":
    main()
