"""Conformance classification + a strict reference model that rejects
deviant traces — proves the non-conforming path detects real deviations."""

from sqlalchemy import select

from app.db import SessionLocal
from app.mining.conformance import classify_alignment
from app.models import ModelDefinition


def test_sync_only_alignment_is_conforming():
    state = classify_alignment([("A", "A"), ("B", "B")])
    assert state["conforming"] is True
    assert state["log_moves"] == 0
    assert state["visible_model_moves"] == 0


def test_silent_model_moves_still_conforming():
    # pm4py charges cost for τ moves, but they are not deviations.
    state = classify_alignment([("A", "A"), (">>", None), (">>", None), ("B", "B")])
    assert state["conforming"] is True
    assert state["silent_moves"] == 2
    assert state["log_moves"] == 0


def test_log_move_is_non_conforming():
    # Log did something the model does not allow.
    state = classify_alignment([("A", "A"), ("SNEAK", ">>"), ("B", "B")])
    assert state["conforming"] is False
    assert state["log_moves"] == 1


def test_visible_model_move_is_non_conforming():
    # Model requires a step the log skipped.
    state = classify_alignment([("A", "A"), (">>", "REQUIRED_CHECK"), ("B", "B")])
    assert state["conforming"] is False
    assert state["visible_model_moves"] == 1


def _strict_model_for(log_id: int) -> int:
    """A hand-built linear net A→B→C→D. The test log contains traces with
    'Rejected'/'Closed' branches, so several cases must fail conformance."""
    spec = {
        "petri_net": {
            "places": ["source", "p1", "p2", "p3", "sink"],
            "transitions": [
                {"name": "tA", "label": "Application Received", "is_visible": True},
                {"name": "tB", "label": "Credit Check", "is_visible": True},
                {"name": "tC", "label": "Approved", "is_visible": True},
                {"name": "tD", "label": "Closed", "is_visible": True},
            ],
            "arcs": [
                {"source": "source", "target": "tA", "type": "Arc"},
                {"source": "tA", "target": "p1", "type": "Arc"},
                {"source": "p1", "target": "tB", "type": "Arc"},
                {"source": "tB", "target": "p2", "type": "Arc"},
                {"source": "p2", "target": "tC", "type": "Arc"},
                {"source": "tC", "target": "p3", "type": "Arc"},
                {"source": "p3", "target": "tD", "type": "Arc"},
                {"source": "tD", "target": "sink", "type": "Arc"},
            ],
            "initial_marking": {"source": 1},
            "final_marking": {"sink": 1},
        },
        "activities": ["Application Received", "Credit Check", "Approved", "Closed"],
        "start_activities": ["Application Received"],
        "end_activities": ["Closed"],
        "miner": "handcrafted",
        "noise_threshold": 0.0,
    }
    with SessionLocal() as db:
        model = ModelDefinition(log_id=log_id, name="Strict reference", miner="handcrafted", spec=spec)
        db.add(model)
        db.commit()
        db.refresh(model)
        return model.id


def test_strict_model_flags_deviant_cases(client, auth_headers, uploaded_log):
    """C2's trace contains 'Rejected' which the strict model forbids."""
    model_id = _strict_model_for(uploaded_log)
    resp = client.post(
        f"/api/logs/{uploaded_log}/conformance",
        headers=auth_headers,
        json={"model_id": model_id, "max_cases": 1000},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["cases_checked"] == 3
    # C1 and C3: Approved path → conform; C2: Rejected path → deviant.
    assert body["non_conforming"] == 1
    assert body["conformance_rate"] == 0.6667
    assert body["total_log_moves"] >= 1
    # Worst case must be the rejected trace.
    worst = body["worst_cases"][0]
    assert worst["conforming"] is False
    assert worst["log_moves"] >= 1
