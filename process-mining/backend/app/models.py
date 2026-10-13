from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    BigInteger,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# SQLite only autoincrements INTEGER primary keys; Postgres is happy with BIGINT.
BigIntPk = BigInteger().with_variant(Integer, "sqlite")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), default="")
    hashed_password: Mapped[str] = mapped_column(String(512), nullable=False)
    role: Mapped[str] = mapped_column(String(32), default="analyst")  # admin | analyst | viewer
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class EventLog(Base):
    """A normalized event log ingested from CSV/XES/SQL (or a stream snapshot)."""

    __tablename__ = "event_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    source_type: Mapped[str] = mapped_column(String(32))  # csv | xes | sql | stream
    source_detail: Mapped[str] = mapped_column(Text, default="")
    case_column: Mapped[str] = mapped_column(String(255))
    activity_column: Mapped[str] = mapped_column(String(255))
    timestamp_column: Mapped[str] = mapped_column(String(255))
    lifecycle_column: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Denormalized stats kept fresh on ingest so the dashboard doesn't scan events.
    case_count: Mapped[int] = mapped_column(BigInteger, default=0)
    event_count: Mapped[int] = mapped_column(BigInteger, default=0)
    activity_count: Mapped[int] = mapped_column(Integer, default=0)
    start_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    end_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="ready")  # ingesting | ready | failed
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    # Never lazy-load events through the log: a log can hold millions of rows.
    # Event rows are always fetched with explicit, indexed queries instead;
    # "raise" makes an accidental access fail loudly rather than load 100k+ rows.
    events: Mapped[list["Event"]] = relationship(back_populates="event_log", lazy="raise")


class Event(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(BigIntPk, primary_key=True, autoincrement=True)
    log_id: Mapped[int] = mapped_column(ForeignKey("event_logs.id", ondelete="CASCADE"), nullable=False)
    case_id: Mapped[str] = mapped_column(String(255), nullable=False)
    activity: Mapped[str] = mapped_column(String(255), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    lifecycle: Mapped[str | None] = mapped_column(String(64), nullable=True)
    attrs: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    event_log: Mapped[EventLog] = relationship(back_populates="events")

    __table_args__ = (
        Index("ix_events_log_case_ts", "log_id", "case_id", "timestamp"),
        Index("ix_events_log_activity_ts", "log_id", "activity", "timestamp"),
        Index("ix_events_log_ts", "log_id", "timestamp"),
    )


class AuditLog(Base):
    """Immutable trail of who did what — required for financial compliance."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(BigIntPk, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    user_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    resource: Mapped[str] = mapped_column(String(255), default="")
    detail: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class ModelDefinition(Base):
    """A discovered or imported reference process model (Petri net / BPMN-ish graph)."""

    __tablename__ = "model_definitions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    log_id: Mapped[int] = mapped_column(ForeignKey("event_logs.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    miner: Mapped[str] = mapped_column(String(64), default="inductive")  # heuristic | inductive | alpha
    spec: Mapped[dict] = mapped_column(JSON, nullable=False)  # nodes/edges graph + petri net
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (UniqueConstraint("log_id", "name", name="uq_model_log_name"),)
