"""Generate three realistic synthetic demo event logs (CSV).

Each dataset is a different business process so demos can highlight
different features of ProMine:

  purchase_to_pay   — procurement cycle with invoice/3-way-match rework
                      loops, an approval-queue bottleneck and rare "rush"
                      shortcuts that bypass policy (conformance deviations).
  insurance_claims  — claims handling with fast/slow tracks, fraud checks,
                      litigations and reopenings (case drill-down demos).
  it_incidents      — ITSM incident flow with L1/L2 handovers, SLA clocks,
                      escalations and reopens (handover/bottleneck demos).

Common shape (matches the existing sample loader expectations):
  case_id, activity, timestamp, user, department, amount, reason, outcome

`user` alternates between humans and bots (e.g. po.bot, fraud.engine,
monitoring.alert) so the handover analysis has human<->automation chains.

Usage: python generate_demo_logs.py [n_cases_per_log]
"""

from __future__ import annotations

import csv
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path

BASE = datetime(2025, 1, 6, 8, 0, 0)
OUT_DIR = Path(__file__).resolve().parents[1] / "sample_data"

HUMANS = {
    "p2p": ["e.fischer", "n.oyelaran", "p.varga", "l.marchetti", "h.tanaka"],
    "claims": ["c.dubois", "r.iversen", "m.abadi", "g.silva", "y.nakamura"],
    "itsm": ["b.kovacs", "t.adeyemi", "s.lindqvist", "j.morales", "w.park"],
}


class CaseBuilder:
    """Builds one case's event list with lognormal waiting times."""

    def __init__(self, rng: random.Random, start: datetime, team: str, humans: list[str]):
        self.rng = rng
        self.t = start
        self.team = team
        self.humans = humans
        self.events: list[tuple[str, datetime, dict]] = []

    def actor(self) -> str:
        return self.rng.choice(self.humans)

    def push(self, activity: str, mean_hours: float, jitter: float = 0.6,
             user: str | None = None, **attrs) -> None:
        hours = max(0.1, self.rng.lognormvariate(0, jitter) * mean_hours)
        self.t = self.t + timedelta(hours=hours)
        self.events.append(
            (activity, self.t, {"user": user or self.actor(), "department": self.team, **attrs})
        )


def purchase_to_pay(rng: random.Random, i: int, start: datetime) -> list[tuple[str, datetime, dict]]:
    c = CaseBuilder(rng, start, "Procurement", HUMANS["p2p"])
    amount = rng.choice([2_000, 8_000, 15_000, 40_000, 90_000, 250_000]) + rng.randint(0, 999)
    urgent = rng.random() < 0.10  # rush orders are allowed to bypass policy

    c.push("Purchase Requisition Created", 1.0, 0.3, amount=amount)
    if amount > 100_000:
        # multi-level approval queue — THE bottleneck (slow queueing)
        c.push("Requisition Approval Queue", 36.0, 0.6, amount=amount, user="approver.queue")
        c.push("Requisition Approved", 4.0, 0.5, amount=amount)
    else:
        c.push("Requisition Approved", 6.0, 0.5, amount=amount)

    if urgent and rng.random() < 0.5:
        # deviant shortcut: goods ordered/received before the PO exists
        c.push("Purchase Order Created", 1.0, 0.3, amount=amount, reason="rush_order")
        c.push("Goods Received", 20.0, 0.6, user="warehouse.bot", reason="rush_order")
    else:
        c.push("Purchase Order Created", 3.0, 0.4, amount=amount)
        c.push("PO Sent to Supplier", 2.0, 0.4, user="po.bot")
        c.push("Goods Received", 48.0, 0.7, user="warehouse.bot")

    c.push("Invoice Received", 6.0, 0.5, user="ap.bot", amount=amount)
    match_ok = rng.random() > (0.28 if amount > 40_000 else 0.12)
    if match_ok:
        c.push("Three-Way Match Passed", 4.0, 0.5, user="ap.bot")
    else:
        # rework loop: mismatch -> manual review -> resubmission
        c.push("Three-Way Match Failed", 3.0, 0.4, user="ap.bot", reason="price_qty_mismatch")
        c.push("Manual Invoice Review", 40.0, 0.6)
        c.push("Supplier Confirmation Requested", 2.0, 0.4, user="ap.bot")
        c.push("Supplier Confirmation Received", 50.0, 0.7)
        c.push("Three-Way Match Passed", 5.0, 0.5, user="ap.bot")

    if not urgent and rng.random() < 0.06:
        c.push("Payment Blocked", 24.0, 0.6, reason="duplicate_invoice", user="fraud.engine")
        c.push("Payment Released", 20.0, 0.5)

    c.push("Payment Scheduled", 8.0, 0.5, user="payments.bot")
    c.push("Payment Executed", 24.0, 0.5, user="payments.bot", amount=amount, outcome="paid")
    return c.events


def insurance_claims(rng: random.Random, i: int, start: datetime) -> list[tuple[str, datetime, dict]]:
    c = CaseBuilder(rng, start, "Claims", HUMANS["claims"])
    amount = rng.choice([800, 2_500, 6_000, 15_000, 45_000, 120_000]) + rng.randint(0, 499)

    c.push("Claim Registered", 1.0, 0.3, amount=amount, user="claims.portal")
    c.push("Policy Validated", 3.0, 0.5, user="policy.engine")
    c.push("Coverage Check", 4.0, 0.5, user="policy.engine")

    if rng.random() < 0.07:
        # rare fraud investigation branch
        c.push("Fraud Signal Detected", 5.0, 0.5, user="fraud.engine", reason="pattern_match")
        c.push("Fraud Investigation", 120.0, 0.6, user="siu.team")
        if rng.random() < 0.5:
            c.push("Claim Denied", 10.0, 0.5, reason="fraud_confirmed", outcome="denied")
            c.push("Claim Closed", 6.0, 0.4, outcome="denied")
            return c.events
        c.push("Fraud Cleared", 8.0, 0.5, user="siu.team")

    fast = amount < 6_000 and rng.random() < 0.7
    if fast:
        # fast track: straight-through processing
        c.push("Damage Assessment", 8.0, 0.5, user="assess.engine")
        c.push("Claim Approved", 6.0, 0.6, amount=amount)
    else:
        # slow track: manual assessment queue is the bottleneck
        c.push("Assessment Queue", 30.0, 0.6, user="assessor.queue")
        c.push("Damage Assessment", 24.0, 0.6)
        if rng.random() < 0.3:
            c.push("Additional Evidence Requested", 3.0, 0.4, reason="missing_documents")
            c.push("Evidence Received", 60.0, 0.8)
            c.push("Damage Assessment", 12.0, 0.5)
        c.push("Repair Estimate Reviewed", 20.0, 0.6)
        if amount > 45_000 and rng.random() < 0.25:
            c.push("Legal Consultation", 96.0, 0.7, reason="liability_dispute", user="legal.team")
        c.push("Claim Approved", 14.0, 0.6, amount=amount)

    c.push("Payment Issued", 16.0, 0.5, user="payments.bot", amount=amount)
    if rng.random() < 0.08:
        c.push("Claim Reopened", 120.0, 0.7, reason="supplemental_damage")
        c.push("Damage Assessment", 20.0, 0.6)
        c.push("Claim Approved", 10.0, 0.5, amount=amount)
        c.push("Payment Issued", 14.0, 0.5, user="payments.bot", amount=amount)
    c.push("Claim Closed", 8.0, 0.5, outcome="settled")
    return c.events


def it_incidents(rng: random.Random, i: int, start: datetime) -> list[tuple[str, datetime, dict]]:
    c = CaseBuilder(rng, start, "IT-Service", HUMANS["itsm"])
    priority = rng.choices(["P1", "P2", "P3"], weights=[0.1, 0.35, 0.55])[0]
    # SLA clock: P1 must resolve fast, P3 is lenient — drives SLA-breach attr
    sla_hours = {"P1": 4.0, "P2": 24.0, "P3": 72.0}[priority]

    c.push("Incident Logged", 0.5, 0.3, user="monitoring.alert", reason=priority)
    c.push("Incident Categorized", 1.0, 0.5, reason=priority)
    c.push("Assigned to L1", 1.5, 0.5, user="servicedesk.bot")

    if rng.random() < (0.55 if priority in ("P1", "P2") else 0.2):
        # escalation chain: L1 -> L2 handover (handover-network demo)
        c.push("L1 Diagnosis", 3.0, 0.6)
        c.push("Escalated to L2", 2.0, 0.5, reason="needs_specialist")
        c.push("L2 Investigation", 6.0, 0.7)
        if priority == "P1" and rng.random() < 0.5:
            c.push("Escalated to Vendor", 3.0, 0.5, reason="third_party_dependency", user="vendor.portal")
            c.push("Vendor Fix Provided", 20.0, 0.8, user="vendor.portal")
    else:
        c.push("L1 Diagnosis", 4.0, 0.6)

    c.push("Fix Deployed", 4.0, 0.6, user="deploy.bot")
    c.push("Resolved", 2.0, 0.5)

    if rng.random() < 0.18:
        # reopen loop — often the SLA already burned here
        c.push("Incident Reopened", 30.0, 0.8, reason="issue_recurred")
        c.push("L2 Investigation", 8.0, 0.6)
        c.push("Fix Deployed", 5.0, 0.6, user="deploy.bot")
        c.push("Resolved", 3.0, 0.5)

    c.push("User Verification", 6.0, 0.6)
    elapsed = (c.events[-1][1] - c.events[0][1]).total_seconds() / 3600
    c.push("Incident Closed", 4.0, 0.5,
           outcome="sla_breach" if elapsed > sla_hours else "sla_met")
    return c.events


GENERATORS = {
    "purchase_to_pay": (purchase_to_pay, "PO-{i:06d}"),
    "insurance_claims": (insurance_claims, "CL-{i:06d}"),
    "it_incidents": (it_incidents, "IN-{i:06d}"),
}

HEADER = ["case_id", "activity", "timestamp", "user", "department", "amount", "reason", "outcome"]


def write_log(name: str, gen, pattern: str, n_cases: int, rng: random.Random) -> tuple[int, int]:
    out = OUT_DIR / f"{name}.csv"
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rows = 0
    with open(out, "w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(HEADER)
        for i in range(1, n_cases + 1):
            case_id = pattern.format(i=i)
            start = BASE + timedelta(hours=rng.uniform(0, 24 * 180))
            for activity, ts, attrs in gen(rng, i, start):
                writer.writerow([
                    case_id,
                    activity,
                    ts.strftime("%Y-%m-%d %H:%M:%S"),
                    attrs.get("user", ""),
                    attrs.get("department", ""),
                    attrs.get("amount", ""),
                    attrs.get("reason", ""),
                    attrs.get("outcome", ""),
                ])
                rows += 1
    return rows, n_cases


def main() -> None:
    n_cases = int(sys.argv[1]) if len(sys.argv) > 1 else 3000
    seed = int(sys.argv[2]) if len(sys.argv) > 2 else 7
    for idx, (name, (gen, pattern)) in enumerate(GENERATORS.items()):
        rows, cases = write_log(name, gen, pattern, n_cases, random.Random(seed + idx))
        print(f"Wrote {rows} events across {cases} cases to sample_data/{name}.csv")


if __name__ == "__main__":
    main()
