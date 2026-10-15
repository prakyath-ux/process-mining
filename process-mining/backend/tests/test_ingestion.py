"""Unit tests for the ingestion layer: timestamp fast path + progress events."""

from datetime import datetime, timezone

from app.ingestion.sources import _parse_timestamp


def test_parse_timestamp_iso_fast_path():
    """ISO-style strings parse via datetime.fromisoformat (the fast path)."""
    ts = _parse_timestamp("2025-03-14 09:21:00")
    assert ts == datetime(2025, 3, 14, 9, 21, tzinfo=timezone.utc)
    ts_t = _parse_timestamp("2025-03-14T09:21:00")
    assert ts_t == datetime(2025, 3, 14, 9, 21, tzinfo=timezone.utc)


def test_parse_timestamp_preserves_offsets():
    """Offsets survive the fast path (no silent UTC rewrite of aware times)."""
    ts = _parse_timestamp("2025-03-14T09:21:00+02:00")
    assert ts is not None
    assert ts.utcoffset().total_seconds() == 2 * 3600
    # same instant expressed in UTC
    utc = _parse_timestamp("2025-03-14T07:21:00+00:00")
    assert utc is not None
    assert ts.astimezone(timezone.utc) == utc


def test_parse_timestamp_falls_back_to_pandas():
    """Non-ISO formats still parse (pandas fallback), naive values go UTC."""
    ts = _parse_timestamp("March 14, 2025 09:21")
    assert ts is not None
    assert (ts.year, ts.month, ts.day) == (2025, 3, 14)
    assert ts.utcoffset().total_seconds() == 0  # naive -> UTC


def test_parse_timestamp_invalid_values():
    assert _parse_timestamp(None) is None
    assert _parse_timestamp("") is None
    assert _parse_timestamp(float("nan")) is None
    assert _parse_timestamp("not a date at all") is None
    # integer epoch-nanos is pandas' domain; must not raise either way
    assert _parse_timestamp(20250314) is None or isinstance(
        _parse_timestamp(20250314), datetime
    )


def test_parse_timestamp_datetime_passthrough():
    aware = datetime(2025, 3, 14, 9, 21, tzinfo=timezone.utc)
    assert _parse_timestamp(aware) is aware


def test_progress_events_during_csv_ingest(tmp_path):
    """CSV ingest reports stage -> progress -> stats with an exact row total."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.db import Base
    from app.ingestion.sources import ColumnMapping, ingest_csv
    from app.models import EventLog

    engine = create_engine(f"sqlite:///{tmp_path}/p.db")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True)
    db = Session()

    log = EventLog(name="t", source_type="csv", case_column="c", activity_column="a",
                  timestamp_column="t")
    db.add(log)
    db.commit()

    csv_data = (
        b"c,a,t\n"
        b"1,Start,2025-01-01 09:00:00\n"
        b"1,End,2025-01-01 10:00:00\n"
        b"2,Start,2025-01-02 09:00:00\n"
        b"2,End,2025-01-02 10:00:00\n"
    )
    events: list[dict] = []
    result = ingest_csv(
        db,
        log,
        csv_data,
        ColumnMapping(case_id="c", activity="a", timestamp="t"),
        progress=events.append,
    )

    assert result == {"inserted": 4, "skipped": 0}
    stages = [e for e in events if e["type"] == "stage"]
    progress = [e for e in events if e["type"] == "progress"]
    assert stages[0]["stage"] == "parsing"
    assert stages[0]["total"] == 4  # newline count minus header
    assert stages[0]["source"] == "csv"
    assert stages[-1]["stage"] == "stats"
    assert progress and progress[-1]["inserted"] == 4
    assert progress[-1]["total"] == 4

    assert log.case_count == 2
    assert log.event_count == 4
    assert log.start_time is not None and log.end_time is not None
    db.close()
