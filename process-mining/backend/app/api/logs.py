"""Event log management: list, detail, delete, audit trail."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import record_audit
from ..db import get_db
from ..models import AuditLog, EventLog, ModelDefinition, User
from ..security import get_current_user, require_role

router = APIRouter(prefix="/api", tags=["logs"])


class LogSummary(BaseModel):
    id: int
    name: str
    description: str
    source_type: str
    source_detail: str
    case_count: int
    event_count: int
    activity_count: int
    start_time: str | None
    end_time: str | None
    status: str
    created_at: str

    model_config = {"from_attributes": True}


def _iso(dt) -> str | None:
    return dt.isoformat() if dt else None


def _to_summary(log: EventLog) -> LogSummary:
    return LogSummary(
        id=log.id,
        name=log.name,
        description=log.description,
        source_type=log.source_type,
        source_detail=log.source_detail,
        case_count=log.case_count,
        event_count=log.event_count,
        activity_count=log.activity_count,
        start_time=_iso(log.start_time),
        end_time=_iso(log.end_time),
        status=log.status,
        created_at=_iso(log.created_at),
    )


def get_log_or_404(db: Session, log_id: int) -> EventLog:
    log = db.get(EventLog, log_id)
    if log is None:
        raise HTTPException(status_code=404, detail="Event log not found")
    return log


@router.get("/logs", response_model=list[LogSummary])
def list_logs(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    logs = db.scalars(select(EventLog).order_by(EventLog.created_at.desc())).all()
    return [_to_summary(log) for log in logs]


@router.get("/logs/{log_id}", response_model=LogSummary)
def get_log(log_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return _to_summary(get_log_or_404(db, log_id))


@router.delete("/logs/{log_id}", status_code=204)
def delete_log(
    log_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("admin")),
):
    log = get_log_or_404(db, log_id)
    from ..models import Event

    db.query(ModelDefinition).filter(ModelDefinition.log_id == log_id).delete()
    db.query(Event).filter(Event.log_id == log_id).delete(synchronize_session=False)
    db.delete(log)
    record_audit(db, action="log_deleted", user=user, resource=f"log:{log_id}", detail={"name": log.name})
    db.commit()


class ModelOut(BaseModel):
    id: int
    name: str
    miner: str
    log_id: int
    log_name: str | None = None
    created_at: str


@router.get("/models", response_model=list[ModelOut])
def list_all_models(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """All models across all logs — reference models can be checked against
    any log, not just the one they were discovered from."""
    from sqlalchemy import select as _select

    rows = db.execute(
        _select(ModelDefinition, EventLog.name).join(EventLog, ModelDefinition.log_id == EventLog.id).order_by(ModelDefinition.id.desc())
    ).all()
    return [
        ModelOut(
            id=m.id,
            name=m.name,
            miner=m.miner,
            log_id=m.log_id,
            log_name=log_name,
            created_at=m.created_at.isoformat(),
        )
        for m, log_name in rows
    ]


class ImportModelBody(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    log_id: int = Field(description="Origin log for provenance")
    miner: str = Field(default="custom", max_length=64)
    spec: dict = Field(description="Model spec: petri_net {places, transitions, arcs, initial_marking, final_marking} + activities/starts/ends")


@router.post("/models/import", status_code=201)
def import_model(
    body: ImportModelBody,
    user: User = Depends(require_role("analyst")),
    db: Session = Depends(get_db),
):
    """Import a hand-built reference model (e.g. the regulatory process)
    as JSON, then run conformance of any log against it."""
    get_log_or_404(db, body.log_id)
    spec = body.spec or {}
    net = spec.get("petri_net")
    if not isinstance(net, dict) or not net.get("places") or not net.get("transitions") or not net.get("arcs"):
        raise HTTPException(
            status_code=422,
            detail="spec.petri_net must contain non-empty places, transitions, and arcs",
        )
    if not net.get("initial_marking") or not net.get("final_marking"):
        raise HTTPException(status_code=422, detail="spec.petri_net needs initial_marking and final_marking")

    existing = db.query(ModelDefinition).filter_by(log_id=body.log_id, name=body.name).first()
    if existing:
        existing.spec = spec
        existing.miner = body.miner
        model = existing
    else:
        model = ModelDefinition(log_id=body.log_id, name=body.name, miner=body.miner, spec=spec)
        db.add(model)
    record_audit(
        db,
        action="model_imported",
        user=user,
        resource=f"log:{body.log_id}",
        detail={"model": body.name, "miner": body.miner},
    )
    db.commit()
    db.refresh(model)
    return {"id": model.id, "name": model.name, "miner": model.miner}


@router.get("/models/{model_id}")
def get_any_model(
    model_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    model = db.get(ModelDefinition, model_id)
    if model is None:
        raise HTTPException(status_code=404, detail="Model not found")
    return {"id": model.id, "name": model.name, "miner": model.miner, "log_id": model.log_id, "spec": model.spec}


@router.get("/logs/{log_id}/cases/{case_id}")
def get_case_trace(
    log_id: int,
    case_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
    limit: int = 500,
):
    """Full event trace for one case — for drill-down during audits."""
    from ..models import Event

    get_log_or_404(db, log_id)
    events = db.scalars(
        select(Event)
        .where(Event.log_id == log_id, Event.case_id == case_id)
        .order_by(Event.timestamp, Event.id)
        .limit(limit)
    ).all()
    if not events:
        raise HTTPException(status_code=404, detail="Case not found")
    return {
        "case_id": case_id,
        "events": [
            {
                "activity": e.activity,
                "timestamp": _iso(e.timestamp),
                "lifecycle": e.lifecycle,
                "attrs": e.attrs,
            }
            for e in events
        ],
    }


@router.get("/audit")
def list_audit(
    limit: int = 100,
    db: Session = Depends(get_db),
    _: User = Depends(require_role("admin")),
):
    rows = db.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(min(limit, 1000))).all()
    return [
        {
            "id": r.id,
            "user_email": r.user_email,
            "action": r.action,
            "resource": r.resource,
            "detail": r.detail,
            "created_at": _iso(r.created_at),
        }
        for r in rows
    ]
