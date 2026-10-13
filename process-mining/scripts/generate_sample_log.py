"""Generate a realistic synthetic event log: small-business loan origination.

Includes rework loops (KYC failures, document requests), a slow manual
bottleneck (Credit Review), and rare shortcut/deviant cases so conformance
checking has something to find.

Usage: python generate_sample_log.py [n_cases] [out.csv]
"""

from __future__ import annotations

import csv
import random
import sys
from datetime import datetime, timedelta

BASE = datetime(2025, 1, 6, 8, 0, 0)

# (activity, mean_hours_from_previous) — previous activity per branch
KYC_ACTIVITIES = ["KYC Started", "KYC Cleared"]


def generate_case(rng: random.Random, case_num: int, start: datetime) -> list[tuple[str, datetime, dict]]:
    events: list[tuple[str, datetime, dict]] = []
    t = start
    analyst = rng.choice(["a.smith", "j.lee", "m.garcia", "k.chen", "r.patel"])
    dept = "SME-Lending"

    def push(activity: str, mean_hours: float, jitter: float = 0.6, user: str | None = None, **attrs) -> None:
        nonlocal t
        hours = max(0.2, rng.lognormvariate(0, jitter) * mean_hours)
        t = t + timedelta(hours=hours)
        events.append((activity, t, {"user": user or analyst, "department": dept, **attrs}))

    amount = rng.choice([25_000, 50_000, 120_000, 250_000, 400_000, 750_000]) + rng.randint(0, 9_999)
    reviewer = rng.choice(["d.novak", "s.rahman", "t.muller"])
    push("Application Received", 1.0, 0.3, amount=amount)
    # automation engines and humans alternate — realistic handover chains
    push("Credit Score Obtained", 6.0, 0.5, user="credit.api", amount=amount)

    # --- KYC: handled by the automation engine, rare manual rework ---
    push("KYC Started", 4.0, 0.5, user="kyc.engine")
    if rng.random() < 0.12:
        push("KYC Failed", 20.0, 0.7, reason="document_mismatch", user="kyc.engine")
        push("KYC Started", 8.0, 0.5, user="kyc.engine")
    push("KYC Cleared", 10.0, 0.6, user="kyc.engine")

    # --- documents: bot requests, human receives (frequent rework loop) ---
    push("Documents Requested", 2.0, 0.4, user="docs.bot")
    push("Documents Received", 30.0, 0.8)
    if rng.random() < 0.35:
        push("Documents Requested", 2.0, 0.4, reason="incomplete_set", user="docs.bot")
        push("Documents Received", 26.0, 0.8)

    # --- credit decision ---
    push("Credit Check Completed", 5.0, 0.5, user="credit.api")
    if rng.random() < 0.3 or amount > 500_000:
        # manual review — THE bottleneck (very slow queue), done by a reviewer
        push("Credit Review", 90.0, 0.5, user=reviewer)
        if rng.random() < 0.22:
            push("Credit Review Rejected", 6.0, 0.5, user=reviewer)
            push("Case Closed", 3.0, 0.4, outcome="rejected")
            return events

    if rng.random() < 0.04:
        # rare shortcut: approval without formal documents (deviant behaviour)
        push("Loan Approved", 10.0, 0.6, shortcut=True)
    else:
        push("Loan Approved", 12.0, 0.6)

    # --- closing / disbursement ---
    push("Loan Setup", 20.0, 0.6)
    if rng.random() < 0.08:
        push("Compliance Hold", 40.0, 0.7, reason="sanctions_rescreen", user="compliance.agent")
        push("Compliance Released", 12.0, 0.5, user="compliance.agent")
    push("Funds Disbursed", 16.0, 0.6, user="payments.bot")
    push("Case Closed", 8.0, 0.5, outcome="disbursed")
    return events


def main() -> None:
    n_cases = int(sys.argv[1]) if len(sys.argv) > 1 else 4000
    out = sys.argv[2] if len(sys.argv) > 2 else "sample_data/loan_origination.csv"
    rng = random.Random(42)

    rows = 0
    with open(out, "w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["case_id", "activity", "timestamp", "user", "department", "amount", "reason", "outcome"])
        for i in range(1, n_cases + 1):
            case_id = f"LN-{i:06d}"
            start = BASE + timedelta(hours=rng.uniform(0, 24 * 150))
            for activity, ts, attrs in generate_case(rng, i, start):
                writer.writerow(
                    [
                        case_id,
                        activity,
                        ts.strftime("%Y-%m-%d %H:%M:%S"),
                        attrs.get("user", ""),
                        attrs.get("department", ""),
                        attrs.get("amount", ""),
                        attrs.get("reason", ""),
                        attrs.get("outcome", ""),
                    ]
                )
                rows += 1
    print(f"Wrote {rows} events across {n_cases} cases to {out}")


if __name__ == "__main__":
    main()
