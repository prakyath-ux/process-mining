"""Ingestion API: upload CSV/XES files or pull from an external SQL source."""

import base64

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..audit import record_audit
from ..config import get_settings
from ..db import get_db
from ..ingestion import ColumnMapping, ingest_csv, ingest_sql, ingest_xes, peek_csv_columns
from ..models import EventLog, User
from ..security import require_role

router = APIRouter(prefix="/api/ingest", tags=["ingest"])


class MappingBody(BaseModel):
    case_id: str
    activity: str
    timestamp: str
    lifecycle: str | None = None
    attr_columns: list[str] = Field(default_factory=list)


class SqlIngestBody(BaseModel):
    name: str
    description: str = ""
    source_url: str
    query: str = Field(min_length=8, description="SELECT statement producing event rows")
    mapping: MappingBody


class PreviewRequest(BaseModel):
    data_base64: str
    delimiter: str = ","


@router.post("/preview-csv")
def preview_csv(
    body: PreviewRequest,
    _: User = Depends(require_role("analyst")),
):
    """Return header + first rows so the UI can build a column mapping."""
    try:
        data = base64.b64decode(body.data_base64)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid base64 payload")
    try:
        return {
            "columns": peek_csv_columns(data),
            **_preview_rows(data, body.delimiter),
        }
    except Exception as exc:  # noqa: BLE001 - surface parse errors to the UI
        raise HTTPException(status_code=400, detail=f"Could not parse CSV: {exc}")


def _preview_rows(data: bytes, delimiter: str) -> dict:
    import csv as csv_mod
    import io

    reader = csv_mod.DictReader(io.StringIO(data.decode("utf-8-sig", errors="replace")), delimiter=delimiter)
    rows = []
    for i, row in enumerate(reader):
        if i >= 20:
            break
        rows.append(row)
    return {"rows": rows}


def _mapping_from_form(
    case_col: str, activity_col: str, ts_col: str, lifecycle_col: str | None, attrs_csv: str
) -> ColumnMapping:
    attrs = [a.strip() for a in attrs_csv.split(",") if a.strip()] if attrs_csv else []
    return ColumnMapping(
        case_id=case_col,
        activity=activity_col,
        timestamp=ts_col,
        lifecycle=lifecycle_col or None,
        attr_columns=attrs,
    )


@router.post("/file", status_code=201)
async def ingest_file(
    file: UploadFile = File(...),
    name: str = Form(...),
    description: str = Form(""),
    case_col: str = Form(...),
    activity_col: str = Form(...),
    timestamp_col: str = Form(...),
    lifecycle_col: str = Form(""),
    attr_columns: str = Form(""),
    delimiter: str = Form(","),
    user: User = Depends(require_role("analyst")),
    db: Session = Depends(get_db),
):
    settings = get_settings()
    data = await file.read()
    if len(data) > settings.upload_max_bytes:
        raise HTTPException(status_code=413, detail="File exceeds upload limit")
    if not data:
        raise HTTPException(status_code=400, detail="Empty file")

    filename = (file.filename or "").lower()
    source_type = "xes" if filename.endswith(".xes") else "csv"
    mapping = _mapping_from_form(case_col, activity_col, timestamp_col, lifecycle_col, attr_columns)

    log = EventLog(
        name=name,
        description=description,
        source_type=source_type,
        source_detail=file.filename or "",
        case_column=mapping.case_id,
        activity_column=mapping.activity,
        timestamp_column=mapping.timestamp,
        lifecycle_column=mapping.lifecycle,
        created_by=user.id,
        status="ingesting",
    )
    db.add(log)
    db.commit()
    db.refresh(log)

    try:
        if source_type == "xes":
            result = ingest_xes(db, log, data, mapping)
        else:
            result = ingest_csv(db, log, data, mapping, delimiter=delimiter)
        log.status = "ready"
        db.commit()
    except Exception as exc:  # noqa: BLE001 - failed ingest must not kill the API
        log.status = "failed"
        db.commit()
        record_audit(
            db, action="ingest_failed", user=user, resource=f"log:{log.id}", detail={"error": str(exc)[:500]}
        )
        db.commit()
        raise HTTPException(status_code=400, detail=f"Ingestion failed: {exc}")

    record_audit(
        db,
        action="ingest_completed",
        user=user,
        resource=f"log:{log.id}",
        detail={"source": source_type, **result},
    )
    db.commit()
    return {"log_id": log.id, "source_type": source_type, **result}


@router.post("/sql", status_code=201)
def ingest_from_sql(
    body: SqlIngestBody,
    user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    """Pull events from an external database. Admin-only: the query runs with
    credentials supplied by the caller (never stored)."""
    if not body.query.strip().lower().startswith("select"):
        raise HTTPException(status_code=400, detail="Only SELECT statements are allowed")

    log = EventLog(
        name=body.name,
        description=body.description,
        source_type="sql",
        source_detail=f"{body.source_url.split('@')[-1]} :: {body.query[:200]}",
        case_column=body.mapping.case_id,
        activity_column=body.mapping.activity,
        timestamp_column=body.mapping.timestamp,
        lifecycle_column=body.mapping.lifecycle,
        created_by=user.id,
        status="ingesting",
    )
    db.add(log)
    db.commit()
    db.refresh(log)

    try:
        result = ingest_sql(db, log, body.source_url, body.query, body.mapping)
        log.status = "ready"
        db.commit()
    except Exception as exc:  # noqa: BLE001
        log.status = "failed"
        db.commit()
        raise HTTPException(status_code=400, detail=f"SQL ingestion failed: {exc}")

    record_audit(
        db, action="ingest_completed", user=user, resource=f"log:{log.id}", detail={"source": "sql", **result}
    )
    db.commit()
    return {"log_id": log.id, "source_type": "sql", **result}
