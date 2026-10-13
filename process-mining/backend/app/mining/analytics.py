"""Single-pass streaming analytics over the event store.

Design for scale: one ordered scan (served by the case/timestamp index) builds
DFG frequencies, variants, waiting times, and case durations with memory
proportional to the number of *activities/edges/variants* — not events.
Duration percentiles use bounded reservoirs per edge/activity.

Every case is buffered completely, then folded into the aggregates only if it
passes the filters — a filtered-out case never contributes partial rows, and
an attribute-filtered case is always counted in full.

Filters ("compare & slice"):
- `start`/`end`: cut events by timestamp (event-level, evaluated in SQL so the
  index serves the range; cases are analyzed within the window).
- `attr`/`attr_value`: keep a case when *any* of its events carries that
  attribute value (e.g. branch="NY").
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Event

RESERVOIR_CAP = 2_000
SAMPLE_CASES_PER_VARIANT = 100  # drill-down list cap per variant
BREAKDOWN_MAX_VALUES = 60


def _ensure_utc(ts: datetime) -> datetime:
    return ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts


def _attr_match(attrs: dict | None, key: str, value: str) -> bool:
    if not attrs:
        return False
    v = attrs.get(key)
    return v is not None and str(v) == str(value)


class DurationStat:
    """Running count/sum/min/max plus a reservoir sample for percentiles."""

    __slots__ = ("count", "total_s", "min_s", "max_s", "_reservoir", "_seen")

    def __init__(self) -> None:
        self.count = 0
        self.total_s = 0.0
        self.min_s = float("inf")
        self.max_s = 0.0
        self._reservoir: list[float] = []
        self._seen = 0

    def add(self, seconds: float) -> None:
        self.count += 1
        self.total_s += seconds
        self.min_s = min(self.min_s, seconds)
        self.max_s = max(self.max_s, seconds)
        self._seen += 1
        if len(self._reservoir) < RESERVOIR_CAP:
            self._reservoir.append(seconds)
        else:
            j = random.randint(0, self._seen - 1)
            if j < RESERVOIR_CAP:
                self._reservoir[j] = seconds

    @property
    def avg_s(self) -> float:
        return self.total_s / self.count if self.count else 0.0

    def percentile(self, p: float) -> float:
        if not self._reservoir:
            return 0.0
        data = sorted(self._reservoir)
        idx = min(len(data) - 1, max(0, int(round(p / 100 * (len(data) - 1)))))
        return data[idx]

    def to_dict(self) -> dict:
        return {
            "count": self.count,
            "avg_s": round(self.avg_s, 3),
            "min_s": round(self.min_s if self.count else 0.0, 3),
            "max_s": round(self.max_s, 3),
            "p50_s": round(self.percentile(50), 3),
            "p90_s": round(self.percentile(90), 3),
        }


@dataclass
class LogAnalytics:
    log_id: int
    filtered: bool = False
    case_count: int = 0
    event_count: int = 0
    start_time: datetime | None = None
    end_time: datetime | None = None
    activity_counts: dict[str, int] = field(default_factory=dict)
    start_activities: dict[str, int] = field(default_factory=dict)
    end_activities: dict[str, int] = field(default_factory=dict)
    # edge -> frequency
    dfg: dict[tuple[str, str], int] = field(default_factory=dict)
    # edge -> duration between the two events (edge sojourn / wait time)
    edge_durations: dict[tuple[str, str], DurationStat] = field(default_factory=dict)
    # activity -> time spent waiting before it started (per case)
    activity_waits: dict[str, DurationStat] = field(default_factory=dict)
    # variant (activity tuple) -> case count
    variants: dict[tuple[str, ...], int] = field(default_factory=dict)
    # per-case total duration, for cycle-time distribution
    case_durations: list[float] = field(default_factory=list)
    # activity active time (time between this event and the next in its case)
    activity_active: dict[str, DurationStat] = field(default_factory=dict)
    # variant -> sample case summaries for drill-down (capped)
    variant_cases: dict[tuple[str, ...], list[dict]] = field(default_factory=dict)

    def case_duration_percentiles(self) -> dict:
        if not self.case_durations:
            return {"count": 0}
        data = sorted(self.case_durations)

        def pct(p: float) -> float:
            idx = min(len(data) - 1, max(0, int(round(p / 100 * (len(data) - 1)))))
            return round(data[idx], 3)

        return {
            "count": len(data),
            "min_s": round(data[0], 3),
            "p50_s": pct(50),
            "p90_s": pct(90),
            "p95_s": pct(95),
            "max_s": round(data[-1], 3),
            "avg_s": round(sum(data) / len(data), 3),
        }

    def top_variants(self, n: int = 20) -> list[dict]:
        total = max(1, self.case_count)
        ranked = sorted(self.variants.items(), key=lambda kv: kv[1], reverse=True)[:n]
        return [
            {
                "rank": i + 1,
                "activities": list(variant),
                "length": len(variant),
                "cases": count,
                "share": round(count / total, 4),
                "case_samples": self.variant_cases.get(variant, []),
            }
            for i, (variant, count) in enumerate(ranked)
        ]

    def bottleneck_scores(self) -> dict[str, float]:
        """0..1 per activity combining relative wait time and throughput share.
        High = cases pile up here (queue) — the bottleneck signal."""
        waits = {a: st.avg_s for a, st in self.activity_waits.items() if st.count}
        if not waits:
            return {}
        max_wait = max(waits.values()) or 1.0
        max_count = max(self.activity_counts.values()) or 1
        scores = {}
        for activity, wait in waits.items():
            wait_component = wait / max_wait
            load_component = self.activity_counts.get(activity, 0) / max_count
            scores[activity] = round(0.7 * wait_component + 0.3 * load_component, 4)
        return scores

    def summary(self) -> dict:
        return {
            "log_id": self.log_id,
            "case_count": self.case_count,
            "event_count": self.event_count,
            "activity_count": len(self.activity_counts),
            "variant_count": len(self.variants),
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "case_durations": self.case_duration_percentiles(),
            "filtered": self.filtered,
        }


@dataclass
class _CaseAccum:
    """One case fully buffered in memory (a case is tiny: tens of events)."""

    case_id: str
    events: list[tuple[str, datetime]] = field(default_factory=list)
    matched: bool = True  # only meaningful when an attribute filter is active

    @property
    def first_ts(self) -> datetime | None:
        return self.events[0][1] if self.events else None

    @property
    def last_ts(self) -> datetime | None:
        return self.events[-1][1] if self.events else None


def analyze_log(
    db: Session,
    log_id: int,
    start: datetime | None = None,
    end: datetime | None = None,
    attr: str | None = None,
    attr_value: str | None = None,
) -> LogAnalytics:
    """Stream the matching events once (ordered by the case index), buffer each
    case fully, then fold cases that pass the filters into the aggregates."""
    use_attr = attr is not None and attr_value is not None
    analytics = LogAnalytics(log_id=log_id, filtered=any([start, end, use_attr]))

    cols = [Event.case_id, Event.activity, Event.timestamp]
    if use_attr:
        cols.append(Event.attrs)
    stmt = select(*cols).where(Event.log_id == log_id)
    if start is not None:
        stmt = stmt.where(Event.timestamp >= start)
    if end is not None:
        stmt = stmt.where(Event.timestamp <= end)
    stmt = stmt.order_by(Event.case_id, Event.timestamp, Event.id)

    def fold(acc: _CaseAccum) -> None:
        if use_attr and not acc.matched:
            return
        if not acc.events:
            return

        activities = [a for a, _ in acc.events]
        variant = tuple(activities)
        first_ts, last_ts = acc.first_ts, acc.last_ts
        duration = max(0.0, (last_ts - first_ts).total_seconds()) if first_ts and last_ts else 0.0

        analytics.case_count += 1
        analytics.case_durations.append(duration)
        analytics.event_count += len(acc.events)
        analytics.variants[variant] = analytics.variants.get(variant, 0) + 1

        samples = analytics.variant_cases.setdefault(variant, [])
        if len(samples) < SAMPLE_CASES_PER_VARIANT:
            samples.append(
                {
                    "case_id": acc.case_id,
                    "events": len(acc.events),
                    "start": first_ts.isoformat() if first_ts else None,
                    "end": last_ts.isoformat() if last_ts else None,
                }
            )

        analytics.start_activities[activities[0]] = analytics.start_activities.get(activities[0], 0) + 1
        analytics.end_activities[activities[-1]] = analytics.end_activities.get(activities[-1], 0) + 1

        if first_ts and (analytics.start_time is None or first_ts < analytics.start_time):
            analytics.start_time = first_ts
        if last_ts and (analytics.end_time is None or last_ts > analytics.end_time):
            analytics.end_time = last_ts

        for i, (activity, ts) in enumerate(acc.events):
            analytics.activity_counts[activity] = analytics.activity_counts.get(activity, 0) + 1
            if i == 0:
                continue
            prev_activity, prev_ts = acc.events[i - 1]
            gap = (ts - prev_ts).total_seconds()
            if gap < 0:
                gap = 0.0  # tolerate small out-of-order timestamps
            edge = (prev_activity, activity)
            analytics.dfg[edge] = analytics.dfg.get(edge, 0) + 1
            analytics.edge_durations.setdefault(edge, DurationStat()).add(gap)
            analytics.activity_waits.setdefault(activity, DurationStat()).add(gap)
            analytics.activity_active.setdefault(prev_activity, DurationStat()).add(gap)

    acc: _CaseAccum | None = None
    current_case: str | None = None
    for row in db.execute(stmt).yield_per(10_000):
        case_id, activity, ts_raw = row[0], row[1], row[2]
        attrs = row[3] if use_attr else None
        ts = _ensure_utc(ts_raw)

        if case_id != current_case:
            if acc is not None:
                fold(acc)
            current_case = case_id
            acc = _CaseAccum(case_id=case_id, matched=not use_attr)

        if acc is None:
            continue
        if use_attr and not acc.matched and _attr_match(attrs, attr, str(attr_value)):
            acc.matched = True
        acc.events.append((activity, ts))

    if acc is not None:
        fold(acc)
    return analytics


@dataclass
class _DimBucket:
    case_count: int = 0
    durations: list[float] = field(default_factory=list)
    waits: dict[str, DurationStat] = field(default_factory=dict)


def analyze_breakdown(
    db: Session,
    log_id: int,
    attr: str,
    start: datetime | None = None,
    end: datetime | None = None,
) -> dict:
    """Group cycle-time performance by an attribute value (branch, user,
    amount band…): one pass, one bucket per value.

    The dimension value of a case = the earliest event carrying the key;
    cases without the key are ignored. At most BREAKDOWN_MAX_VALUES buckets.
    """
    stmt = (
        select(Event.case_id, Event.activity, Event.timestamp, Event.attrs)
        .where(Event.log_id == log_id)
    )
    if start is not None:
        stmt = stmt.where(Event.timestamp >= start)
    if end is not None:
        stmt = stmt.where(Event.timestamp <= end)
    stmt = stmt.order_by(Event.case_id, Event.timestamp, Event.id)

    buckets: dict[str, _DimBucket] = {}
    truncated = False

    def fold(acc: _CaseAccum, dim_value: str | None, waits: list[tuple[str, float]]) -> None:
        nonlocal truncated
        if dim_value is None or not acc.events:
            return
        if dim_value not in buckets:
            if len(buckets) >= BREAKDOWN_MAX_VALUES:
                truncated = True
                return
            buckets[dim_value] = _DimBucket()
        b = buckets[dim_value]
        b.case_count += 1
        first_ts, last_ts = acc.first_ts, acc.last_ts
        if first_ts and last_ts:
            b.durations.append(max(0.0, (last_ts - first_ts).total_seconds()))
        for activity, gap in waits:
            b.waits.setdefault(activity, DurationStat()).add(gap)

    acc: _CaseAccum | None = None
    dim_value: str | None = None
    waits: list[tuple[str, float]] = []
    current_case: str | None = None

    for case_id, activity, ts_raw, attrs in db.execute(stmt).yield_per(10_000):
        ts = _ensure_utc(ts_raw)
        if case_id != current_case:
            fold(acc, dim_value, waits)
            current_case = case_id
            acc = _CaseAccum(case_id=case_id)
            dim_value = None
            waits = []
        if acc is None:
            continue
        if dim_value is None and attrs and attrs.get(attr) is not None:
            dim_value = str(attrs[attr])
        if acc.events and dim_value is not None:
            prev_activity, prev_ts = acc.events[-1]
            gap = (ts - prev_ts).total_seconds()
            waits.append((activity, max(0.0, gap)))
        acc.events.append((activity, ts))
    fold(acc, dim_value, waits)

    def pct(data: list[float], p: float) -> float:
        if not data:
            return 0.0
        s = sorted(data)
        idx = min(len(s) - 1, max(0, int(round(p / 100 * (len(s) - 1)))))
        return round(s[idx], 3)

    rows = []
    for value, b in buckets.items():
        top_waits = sorted(
            (
                {
                    "activity": a,
                    "avg_wait_s": round(st.avg_s, 3),
                    "p90_wait_s": round(st.percentile(90), 3),
                    "events": st.count,
                }
                for a, st in b.waits.items()
            ),
            key=lambda r: r["avg_wait_s"],
            reverse=True,
        )
        avg = round(sum(b.durations) / len(b.durations), 3) if b.durations else 0.0
        rows.append(
            {
                "value": value,
                "cases": b.case_count,
                "avg_duration_s": avg,
                "p50_duration_s": pct(b.durations, 50),
                "p90_duration_s": pct(b.durations, 90),
                "top_waits": top_waits[:5],
            }
        )
    rows.sort(key=lambda r: r["avg_duration_s"], reverse=True)
    return {
        "attribute": attr,
        "values": rows,
        "truncated": truncated,
        "max_values": BREAKDOWN_MAX_VALUES,
    }
