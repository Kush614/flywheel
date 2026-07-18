"""Pomerium seam — zero-trust policy gate in front of money-spending writes.

The thesis (§7): an autonomous agent that *spends money* is exactly where
zero-trust belongs. Reads are free; **writes are policy-gated at the infra
layer**, so even a prompt-injected agent cannot overspend — it can't argue with
a gate that sits below it.

In production this is a real Pomerium deployment in front of the Nexla
`bid.actions` MCP server (see deploy/pomerium/config.yaml — `mcp:` route +
`mcp_tool` PPL allowlist + service-account JWT identity + audit log). Pomerium
owns identity, tool-scoping, TLS, and the audit trail. The three *stateful*
policies the demo needs — a per-session budget cap, time-bound per-period
authority, and human-approval-above-threshold — are enforced here in the gate
wrapper (Pomerium's PPL is stateless per-request), so this class is a faithful
local stand-in that runs with no cloud dependency.

Every decision produces an AuditRecord. The dashboard renders the allow / deny /
pending stream live — security you can watch.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional


@dataclass
class AuditRecord:
    seq: int
    period: int
    identity: str
    target: str
    amount: float
    decision: str      # "allow" | "deny" | "pending" | "approved"
    category: str      # "ok" | "budget" | "stale" | "injection" | "approval"
    reason: str

    def to_dict(self) -> dict:
        return {
            "kind": "audit", "seq": self.seq, "period": self.period,
            "identity": self.identity, "target": self.target,
            "amount": round(self.amount, 2), "decision": self.decision,
            "category": self.category, "reason": self.reason,
        }


@dataclass
class GateDecision:
    action: dict
    decision: str
    category: str
    reason: str
    record: AuditRecord

    @property
    def allowed(self) -> bool:
        # an out-of-band human approval also authorizes the write
        return self.decision in ("allow", "approved")


class PolicyGate:
    """Faithful local stand-in for a Pomerium gate over `bid.actions`."""

    def __init__(
        self,
        *,
        session_budget_cap: float = 200.0,
        approval_threshold: float = 4.0,
        sane_bid_ceiling: float = 25.0,
        identity: str = "agent:flywheel-loopA",
        on_audit: Optional[Callable[[AuditRecord], None]] = None,
    ):
        self.session_budget_cap = session_budget_cap      # max $ authorizable per session
        self.approval_threshold = approval_threshold      # single action above this needs a human
        self.sane_bid_ceiling = sane_bid_ceiling          # anything above this is an attack, not a bid
        self.identity = identity
        self.on_audit = on_audit

        self.authorized_spend = 0.0
        self.approved: set[str] = set()                   # targets granted standing approval
        self.pending: dict[str, dict] = {}                # target -> held action
        self.audit: list[AuditRecord] = []
        self._seq = 0

    # --- the gate ----------------------------------------------------------
    def authorize(self, action: dict, period: int) -> GateDecision:
        """Run one write action through the policy checks, in priority order."""
        target = action.get("target", "?")
        amount = float(action.get("new_bid", action.get("amount", 0.0)) or 0.0)

        # 1) INJECTION GUARD — the headline beat. A poisoned data field tried to
        #    make the agent bid absurdly high, or carried an instruction to
        #    "ignore prior limits". The gate refuses below the agent's reasoning.
        if action.get("injected") or action.get("instruction") or amount > self.sane_bid_ceiling:
            reason = (
                f"BLOCKED: bid ${amount:,.0f} exceeds the sane ceiling "
                f"(${self.sane_bid_ceiling:.0f}) / action carries an injected "
                f"instruction. Prompt-injection refused at the gate — the agent "
                f"never gets to spend it."
            )
            return self._decide(action, period, "deny", "injection", reason, amount, target)

        # 2) TIME-BOUND AUTHORITY — a bid-action token is scoped to the period
        #    it was issued in. A stale plan (replayed from an earlier period)
        #    cannot execute.
        issued = action.get("issued_period", period)
        if issued != period:
            reason = (f"DENIED (stale): action was issued for period {issued} but the "
                      f"current period is {period} — time-bound authority has expired.")
            return self._decide(action, period, "deny", "stale", reason, amount, target)

        # 3) HUMAN-APPROVAL-ABOVE-THRESHOLD — hold big spends for a person.
        #    Approval is a standing per-target grant (a human vouched for it).
        if amount > self.approval_threshold and target not in self.approved:
            self.pending[target] = action
            reason = (
                f"HELD: bid ${amount:.2f} is over the ${self.approval_threshold:.2f} "
                f"approval threshold — awaiting out-of-band human approval."
            )
            return self._decide(action, period, "pending", "approval", reason, amount, target)

        # 3) PER-SESSION BUDGET CAP — a hard ceiling the agent physically can't cross.
        if self.authorized_spend + amount > self.session_budget_cap:
            reason = (
                f"DENIED: session budget cap ${self.session_budget_cap:.0f} would be "
                f"exceeded (already authorized ${self.authorized_spend:.2f}). "
                f"The loop cannot spend more this session, whatever it decides."
            )
            return self._decide(action, period, "deny", "budget", reason, amount, target)

        # 4) ALLOW — scoped to the agent identity, added to the running total.
        self.authorized_spend += amount
        was_approved = target in self.approved
        reason = (
            f"{'APPROVED' if was_approved else 'ALLOWED'}: authorized ${amount:.2f} "
            f"(session ${self.authorized_spend:.2f}/${self.session_budget_cap:.0f})."
        )
        return self._decide(action, period, "approved" if was_approved else "allow",
                            "ok", reason, amount, target)

    # --- out-of-band human approval ---------------------------------------
    def approve(self, target: str, period: int = -1) -> bool:
        """A human clicks Approve — grants standing authority for this target."""
        self.approved.add(target)
        self.pending.pop(target, None)
        self._seq += 1
        rec = AuditRecord(self._seq, period, "human:demo-operator", target,
                          0.0, "approved", "approval",
                          f"human granted standing approval for bids on '{target}'.")
        self.audit.append(rec)
        if self.on_audit:
            self.on_audit(rec)
        return True

    def deny(self, target: str, period: int = -1) -> bool:
        self.pending.pop(target, None)
        self._seq += 1
        rec = AuditRecord(self._seq, period, "human:demo-operator", target,
                          0.0, "deny", "approval",
                          f"human rejected the held bid on '{target}'.")
        self.audit.append(rec)
        if self.on_audit:
            self.on_audit(rec)
        return True

    def pending_list(self) -> list[dict]:
        return [{"target": t, "new_bid": a.get("new_bid")} for t, a in self.pending.items()]

    # --- helpers -----------------------------------------------------------
    def _decide(self, action, period, decision, category, reason, amount, target) -> GateDecision:
        self._seq += 1
        rec = AuditRecord(self._seq, period, self.identity, target, amount,
                          decision, category, reason)
        self.audit.append(rec)
        if self.on_audit:
            self.on_audit(rec)
        return GateDecision(action, decision, category, reason, rec)
