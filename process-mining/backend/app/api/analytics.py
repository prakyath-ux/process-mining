"""Mining/analysis API: process map, variants, bottlenecks, models, conformance."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import record_audit
from ..db import get_db
from ..mining import analyze_log, build_process_map, discover_model, run_alignments
from ..mining.analytics import LogAnalytics
from ..models import EventLog, ModelDefinition, User
from ..security import get_current_user, require_role
from .logs import get_log_or_404

router = APIRouter(prefix="/api/logs", tags=["mining"])

# Analytics cache: keyed by (log_id, event_count, filters) so ingests AND
# filter changes invalidate correctly. Bounded to avoid memory growth.
_MAX_CACHE = 8
_analytics_cache: dict[tuple, LogAnalytics] = {}

FilterKw = dict  # {"start": datetime|None, "end": datetime|None, "attr": str|None, "attr_value": str|None}


def _filter_kwargs(
    start: datetime | None = None,
    end: datetime | None = None,
    attr: str | None = None,
    attr_value: str | None = None,
) -> FilterKw:
    if (attr is None) != (attr_value is None):
        raise HTTPException(status_code=400, detail="attr and attr_value must be provided together")
    return {
        "start": start,
        "end": end,
        "attr": attr if attr_value is not None else None,
        "attr_value": attr_value,
    }


def get_analytics(db: Session, log: EventLog, **filters) -> LogAnalytics:
    key = (log.id, log.event_count, filters.get("start"), filters.get("end"), filters.get("attr"), filters.get("attr_value"))
    if key in _analytics_cache:
        cached = _analytics_cache.pop(key)  # LRU-ish: refresh recency
        _analytics_cache[key] = cached
        return cached
    analytics = analyze_log(db, log.id, **filters)
    _analytics_cache[key] = analytics
    while len(_analytics_cache) > _MAX_CACHE:
        _analytics_cache.pop(next(iter(_analytics_cache)))
    return analytics


@router.get("/{log_id}/process-map")
def process_map(
    log_id: int,
    top_edges: int | None = Query(default=None, ge=1, le=2000),
    start: datetime | None = None,
    end: datetime | None = None,
    attr: str | None = None,
    attr_value: str | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    log = get_log_or_404(db, log_id)
    if log.event_count == 0:
        raise HTTPException(status_code=400, detail="Log has no events")
    analytics = get_analytics(db, log, **_filter_kwargs(start, end, attr, attr_value))
    payload = build_process_map(analytics, top_edges=top_edges)
    payload["log"] = {"id": log.id, "name": log.name}
    return payload


@router.get("/{log_id}/variants")
def variants(
    log_id: int,
    top: int = Query(default=20, ge=1, le=200),
    start: datetime | None = None,
    end: datetime | None = None,
    attr: str | None = None,
    attr_value: str | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    log = get_log_or_404(db, log_id)
    analytics = get_analytics(db, log, **_filter_kwargs(start, end, attr, attr_value))
    total = len(analytics.variants)
    all_ranked = analytics.top_variants(10_000)
    cumulative = 0.0
    for row in all_ranked:
        cumulative += row["share"]
        row["cumulative_share"] = round(cumulative, 4)
    ranked = all_ranked[:top]
    return {
        "total_variants": total,
        "case_count": analytics.case_count,
        "pareto_80_variant_count": _pareto_count(all_ranked, 0.8),
        "variants": ranked,
    }


def _pareto_count(ranked: list[dict], target: float) -> int:
    cumulative = 0.0
    for i, row in enumerate(ranked):
        cumulative += row["share"]
        if cumulative >= target:
            return i + 1
    return len(ranked)


@router.get("/{log_id}/bottlenecks")
def bottlenecks(
    log_id: int,
    top: int = Query(default=15, ge=1, le=100),
    start: datetime | None = None,
    end: datetime | None = None,
    attr: str | None = None,
    attr_value: str | None = None,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Activities ranked by queueing (wait) time — the bottleneck report."""
    log = get_log_or_404(db, log_id)
    analytics = get_analytics(db, log, **_filter_kwargs(start, end, attr, attr_value))
    scores = analytics.bottleneck_scores()
    rows = []
    for activity, score in scores.items():
        wait = analytics.activity_waits.get(activity)
        rows.append(
            {
                "activity": activity,
                "score": score,
                "count": analytics.activity_counts.get(activity, 0),
                "wait": wait.to_dict() if wait else None,
            }
        )
    rows.sort(key=lambda r: r["score"], reverse=True)
    return {
        "bottlenecks": rows[:top],
        "case_durations": analytics.case_duration_percentiles(),
        "total_activities": len(rows),
    }


@router.get("/{log_id}/models", status_code=200)
def list_models(
    log_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    get_log_or_404(db, log_id)
    models = db.scalars(select(ModelDefinition).where(ModelDefinition.log_id == log_id)).all()
    return [
        {"id": m.id, "name": m.name, "miner": m.miner, "created_at": m.created_at.isoformat()}
        for m in models
    ]


class DiscoverBody(BaseModel):
    name: str = Field(default="Discovered model", min_length=1, max_length=255)
    miner: str = Field(default="inductive", pattern="^(inductive|alpha)$")
    noise_threshold: float = Field(default=0.0, ge=0.0, le=1.0)


@router.post("/{log_id}/models", status_code=201)
def create_model(
    log_id: int,
    body: DiscoverBody,
    start: datetime | None = None,
    end: datetime | None = None,
    attr: str | None = None,
    attr_value: str | None = None,
    user: User = Depends(require_role("analyst")),
    db: Session = Depends(get_db),
):
    log = get_log_or_404(db, log_id)
    if log.event_count == 0:
        raise HTTPException(status_code=400, detail="Log has no events")
    analytics = get_analytics(db, log, **_filter_kwargs(start, end, attr, attr_value))
    try:
        model = discover_model(
            db, log, analytics, name=body.name, miner=body.miner, noise_threshold=body.noise_threshold
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    record_audit(
        db,
        action="model_discovered",
        user=user,
        resource=f"log:{log.id}",
        detail={"model": model.name, "miner": body.miner},
    )
    db.commit()
    return {"id": model.id, "name": model.name, "miner": model.miner}


@router.get("/{log_id}/models/{model_id}")
def get_model(
    log_id: int,
    model_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    model = db.get(ModelDefinition, model_id)
    if model is None or model.log_id != log_id:
        raise HTTPException(status_code=404, detail="Model not found")
    return {"id": model.id, "name": model.name, "miner": model.miner, "spec": model.spec}


class ConformanceBody(BaseModel):
    model_id: int
    max_cases: int | None = Field(default=10_000, ge=1, le=1_000_000)


@router.post("/{log_id}/conformance")
def conformance(
    log_id: int,
    body: ConformanceBody,
    user: User = Depends(require_role("analyst")),
    db: Session = Depends(get_db),
):
    log = get_log_or_404(db, log_id)
    try:
        result = run_alignments(db, log, model_id=body.model_id, max_cases=body.max_cases)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    record_audit(
        db,
        action="conformance_run",
        user=user,
        resource=f"log:{log.id}",
        detail={"model_id": body.model_id, "cases": result["cases_checked"]},
    )
    db.commit()
    return result
