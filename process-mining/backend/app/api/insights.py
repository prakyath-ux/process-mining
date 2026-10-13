"""Deeper insights: attribute discovery, group-by comparisons, organizational
handover network, timeline sampling, and case search for drill-down."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..mining.analytics import analyze_breakdown
from ..models import Event, EventLog, User
from ..security import get_current_user
from .analytics import get_analytics
from .logs import get_log_or_404

router = APIRouter(prefix="/api/logs", tags=["insights"])


def _parse_bounds(start: datetime | None, end: datetime | None) -> tuple[datetime | None, datetime | None]:
    return start, end


@router.get("/{log_id}/attributes")
def list_attributes(
    log_id: int,
    sample: int = Query(default=3000, ge=100, le=50_000),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Discover which extra attributes exist on this log (keys + sample values),
    by scanning a bounded window of events. Powers filter/compare dropdowns."""
    get_log_or_404(db, log_id)
    rows = db.execute(
        select(Event.attrs).where(Event.log_id == log_id, Event.attrs.is_not(None)).limit(sample)
    )
    keys: dict[str, dict] = {}
    for (attrs,) in rows:
        if not isinstance(attrs, dict):
            continue
        for k, v in attrs.items():
            if v is None:
                continue
            entry = keys.setdefault(k, {"key": k, "samples": [], "_seen": set(), "numeric": True, "count": 0})
            entry["count"] += 1
            if not isinstance(v, (int, float)):
                entry["numeric"] = False
            sv = str(v)
            if len(entry["_seen"]) < 15 and sv not in entry["_seen"]:
                entry["_seen"].add(sv)
                entry["samples"].append(sv)
    result = [
        {"key": e["key"], "samples": e["samples"], "numeric": e["numeric"], "events_with_key": e["count"]}
        for e in sorted(keys.values(), key=lambda e: e["count"], reverse=True)
    ]
    return {"attributes": result, "sampled_events": sample}


@router.get("/{log_id}/breakdown")
def breakdown(
    log_id: int,
    attr: str = Query(min_length=1, max_length=64),
    start: datetime | None = None,
    end: datetime | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Compare performance across values of an attribute: e.g. cycle time and
    top waits per branch, per agent, or per automation engine."""
    get_log_or_404(db, log_id)
    start, end = _parse_bounds(start, end)
    result = analyze_breakdown(db, log_id, attr, start=start, end=end)
    if not result["values"]:
        raise HTTPException(
            status_code=404,
            detail=f"No cases carry attribute '{attr}' on this log (check the sampled attributes first)",
        )
    return result


@router.get("/{log_id}/handover")
def handover(
    log_id: int,
    actor_attr: str = Query(default="user", min_length=1, max_length=64),
    start: datetime | None = None,
    end: datetime | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Organizational mining: who hands work to whom (or which bot/agent hands
    off to which human/CRM). One pass; edges carry count + handover wait time."""
    get_log_or_404(db, log_id)
    stmt = (
        select(Event.case_id, Event.activity, Event.timestamp, Event.attrs)
        .where(Event.log_id == log_id)
    )
    if start is not None:
        stmt = stmt.where(Event.timestamp >= start)
    if end is not None:
        stmt = stmt.where(Event.timestamp <= end)
    stmt = stmt.order_by(Event.case_id, Event.timestamp, Event.id)

    nodes: dict[str, dict] = {}
    edges: dict[tuple[str, str], dict] = {}
    current_case = None
    prev_actor: str | None = None
    prev_ts: datetime | None = None

    def node(actor: str, activity: str) -> dict:
        n = nodes.get(actor)
        if n is None:
            n = nodes[actor] = {"id": actor, "events": 0, "activities": {}}
        n["events"] += 1
        n["activities"][activity] = n["activities"].get(activity, 0) + 1
        return n

    for case_id, activity, ts_raw, attrs in db.execute(stmt).yield_per(10_000):
        if case_id != current_case:
            current_case = case_id
            prev_actor = None
            prev_ts = None
        actor = None
        if isinstance(attrs, dict) and attrs.get(actor_attr) is not None:
            actor = str(attrs[actor_attr])
        if actor is not None:
            node(actor, activity)
        if actor is not None and prev_actor is not None and prev_actor != actor and prev_ts is not None:
            gap = max(0.0, (ts_raw - prev_ts).total_seconds())
            e = edges.setdefault(
                (prev_actor, actor),
                {"count": 0, "wait_s": 0.0, "_gaps": []},
            )
            e["count"] += 1
            e["wait_s"] += gap
            if len(e["_gaps"]) < 2000:
                e["_gaps"].append(gap)
        if actor is not None:
            prev_actor = actor
            prev_ts = ts_raw

    for n in nodes.values():
        top = sorted(n["activities"].items(), key=lambda kv: kv[1], reverse=True)[:4]
        n["top_activities"] = [{"activity": a, "count": c} for a, c in top]
        del n["activities"]

    edge_rows = []
    for (src, tgt), e in edges.items():
        gaps = sorted(e["_gaps"])
        p50 = gaps[len(gaps) // 2] if gaps else 0.0
        edge_rows.append(
            {
                "source": src,
                "target": tgt,
                "count": e["count"],
                "avg_wait_s": round(e["wait_s"] / e["count"], 3),
                "p50_wait_s": round(p50, 3),
            }
        )
    edge_rows.sort(key=lambda r: r["count"], reverse=True)

    return {
        "actor_attr": actor_attr,
        "nodes": sorted(nodes.values(), key=lambda n: n["events"], reverse=True),
        "edges": edge_rows,
        "actors": len(nodes),
        "handovers": len(edge_rows),
    }


@router.get("/{log_id}/timeline")
def timeline(
    log_id: int,
    limit: int = Query(default=400, ge=10, le=2000),
    start: datetime | None = None,
    end: datetime | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Sampled case strips over time (dotted chart): x = event time,
    one row per case. Cases are stride-sampled so big logs stay responsive."""
    get_log_or_404(db, log_id)
    id_stmt = select(Event.case_id).where(Event.log_id == log_id).distinct()
    if start is not None:
        id_stmt = id_stmt.where(Event.timestamp >= start)
    if end is not None:
        id_stmt = id_stmt.where(Event.timestamp <= end)
    case_ids = [r[0] for r in db.execute(id_stmt.order_by(Event.case_id))]
    if not case_ids:
        raise HTTPException(status_code=404, detail="No cases in range")

    total = len(case_ids)
    if total > limit:
        step = total / limit
        case_ids = [case_ids[int(i * step)] for i in range(limit)]

    rows = db.execute(
        select(Event.case_id, Event.activity, Event.timestamp)
        .where(Event.log_id == log_id, Event.case_id.in_(case_ids))
        .order_by(Event.case_id, Event.timestamp, Event.id)
    )
    by_case: dict[str, list[dict]] = {}
    for case_id, activity, ts in rows:
        by_case.setdefault(case_id, []).append(
            {"activity": activity, "ts": _iso(ts)}
        )
    cases = sorted(
        ({"case_id": cid, "events": evs} for cid, evs in by_case.items() if evs),
        key=lambda c: c["events"][0]["ts"],
    )
    activities = sorted({e["activity"] for c in cases for e in c["events"]})
    return {
        "cases": cases,
        "total_cases": total,
        "sampled_cases": len(cases),
        "activities": activities,
    }


@router.get("/{log_id}/cases")
def search_cases(
    log_id: int,
    q: str | None = Query(default=None, max_length=255),
    variant: str | None = Query(
        default=None, description='JSON array of activities, e.g. ["A","B","C"]'
    ),
    start: datetime | None = None,
    end: datetime | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Find cases for drill-down: by id substring (q) or by variant sequence
    (uses the analytics cache's per-variant samples)."""
    log = get_log_or_404(db, log_id)
    import json as _json

    if variant:
        try:
            seq = tuple(str(a) for a in _json.loads(variant))
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail="variant must be a JSON array of activity names")
        analytics = get_analytics(db, log, start=start, end=end)
        if seq not in analytics.variants:
            raise HTTPException(status_code=404, detail="Variant not present in this log")
        samples = analytics.variant_cases.get(seq, [])
        return {
            "cases": samples,
            "variant": list(seq),
            "total_matching": analytics.variants[seq],
            "returned": len(samples),
        }

    if q:
        stmt = (
            select(Event.case_id)
            .where(Event.log_id == log_id, Event.case_id.contains(q))
            .distinct()
            .order_by(Event.case_id)
            .limit(50)
        )
        if start is not None:
            stmt = stmt.where(Event.timestamp >= start)
        if end is not None:
            stmt = stmt.where(Event.timestamp <= end)
        ids = [r[0] for r in db.execute(stmt)]
        if not ids:
            return {"cases": [], "total_matching": 0, "returned": 0}
        rows = db.execute(
            select(Event.case_id, Event.activity, Event.timestamp)
            .where(Event.log_id == log_id, Event.case_id.in_(ids))
            .order_by(Event.case_id, Event.timestamp, Event.id)
        )
        summary: dict[str, dict] = {}
        for case_id, activity, ts in rows:
            s = summary.setdefault(
                case_id, {"case_id": case_id, "events": 0, "first": _iso(ts), "start_activity": activity}
            )
            s["events"] += 1
            s["end"] = _iso(ts)
            s["last_activity"] = activity
        return {
            "cases": list(summary.values()),
            "total_matching": len(summary),
            "returned": len(summary),
        }

    raise HTTPException(status_code=400, detail="Provide q (case id substring) or variant (JSON array)")


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None
