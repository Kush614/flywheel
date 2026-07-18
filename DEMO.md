# DEMO.md — Flywheel, the 2-minute run

> One loop engine (`loopkit`) that plans → acts → observes → self-corrects, shown
> driving two different domains unchanged. Every beat below is on screen in the
> live dashboard. Ground-truth feedback, visible self-correction, hard limits.

**Setup:** `py -m dashboard.server` → open http://localhost:8000. Click **🔊 Narrate**
if you want it to speak the beats. For a fast run: `FLYWHEEL_PERIOD_DELAY=0.6 py -m dashboard.server`.

---

## The script (target ~2:00)

**0:00 — What this is (15s).**
"This is a loop *engine*. Watch four lanes — plan, act, observe, correct — and
the flywheel up top: it spins faster as the loop earns efficiency." Click
**▶ Start Loop A**. The four lanes start filling.

**0:15 — The curve bends (25s).**
The cost-per-conversion curve bends **down**. Read one Plan aloud: it states a
*cause hypothesis* per keyword ("`cheap-widgets` wins clicks that don't convert —
relevance, not price") and an explore probe. "This isn't a thermostat — every
correction names a cause and picks a different fix per cause."

**0:40 — Real feedback, real correction (20s).**
Click **⚔ Competitor bid war** (or ☀ seasonal spike). The next Plan references the
change and corrects. "The feedback is ground truth the agent can't fake —
conversions per dollar — so the correction is real."

**1:00 — Security where the agent can't argue (20s).**
Click **☠ Inject poison ($10k)**. A poisoned data field tells the agent to bid
$10,000. It *tries* — and **Pomerium blocks it at the gate** and audits the
attempt (watch the Pomerium panel: `BLOCKED` on the scoped identity
`agent:flywheel-loopA`; the bid never changes). "Even a prompt-injected agent
physically cannot overspend — the limit is below the agent, at the infra layer."
*(Bonus: click 🔐 Request $5 bid → it's held → Approve it in the panel.)*

**1:20 — It knows when to stop, and it makes its own tools (20s).**
The dud triggers **Zero.xyz discovery** (Zero panel): with no API keys, the agent
finds real ad-creative services and shows a fresh AI creative vs the stale one.
Meanwhile the thrash/stop detector halts a noisy keyword with a stated reason.
"It catches *itself* — stops rather than thrash — and when it lacks a capability
it discovers and pays for one through Zero, no config."

**1:40 — Same engine, new domain (20s).**
Conversions-per-dollar holds above threshold → **`growth.sustained`** fires and the
**Loop B — Talent (Fillmore)** card appears. The *same* engine now runs an outbound
recruiting loop: reply-rate is the ground-truth signal and it self-corrects upward.
"Marketing growth *causing* a hiring loop — same loopkit, unchanged." *(Force it
anytime with 🌱 Trigger growth.)*

**2:00 — Close (10s).**
"One loop engine. Two domains. Ground-truth signals, visible self-correction,
hard budget limits — built on Nexla, Zero, Pomerium, Fillmore, and Claude."
Optional: flip **🎞 Mode: Replay** to show the identical loop running on a real
12-month campaign CSV.

---

## Prize-to-feature map (all demonstrable live)

| Prize | Feature | Where on screen |
|---|---|---|
| Most Innovative Pomerium | Policy-gated money-spend; $10k injection blocked at the gate; full audit | ☠ Inject poison → Pomerium panel |
| Best use of Zero.xyz | Agent discovers + pays for ad-creative APIs with no keys (x402 wallet); also **hosts a live site via Zero** | Zero panel; `sites.withzero.ai` |
| Best use of Fillmore | Growth-triggered outbound recruiting as a real observe/correct loop | Loop B card, reply-rate chart |
| Best Nexla ADK | Agent's world-view is a governed Nexset via `nexla-cli` (`ant`/CLI creds) | on `nexla-cli login` |
| 1st / General | `loopkit` generality + self-correction + self-stop, live | whole run; Loop A + Loop B |

## Fallback plan (if any API dies mid-demo)
Everything above runs on the **zero-dependency fallback path** — no credentials
needed. The simulator, Pomerium gate, thrash detector, Loop B, and the four-step
dashboard are all local. Zero discovery is the only live-network beat; if it's
down, the loop keeps running and the rest of the demo is unaffected.

## Talking points if a judge probes
- **"Is the feedback real?"** Conversions/cost from a simulator the agent never
  sees the internals of (or a real CSV in Replay mode). It must *discover* the
  response surface by bidding and observing.
- **"Is the correction real reasoning?"** Each Plan states a cause hypothesis and
  picks a *different* fix per cause (bid-limited → raise; relevance-limited → cut
  + new creative). With `ant auth login`, Claude writes those hypotheses.
- **"What stops it overspending?"** Pomerium: per-session budget cap, time-bound
  authority, human-approval-above-threshold, and the injection block — all at the
  infra layer, audited.
- **"Is it really one engine?"** `tests/test_talent.py::test_same_engine_runs_marketing_and_talent`
  runs one engine object over both domains. 26 tests green.
