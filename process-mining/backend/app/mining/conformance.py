"""Conformance checking via pm4py alignment diagnostics.

Models are persisted as JSON specs and reconstructed on demand, so alignment
runs don't require rediscovery. Runs are capped/sampled to protect latency on
very large logs (full-log runs possible via sample=None).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Event, EventLog, ModelDefinition
from .analytics import _ensure_utc


def deserialize_petri_net(spec: dict[str, Any]):
    from pm4py.objects.petri_net.obj import Marking, PetriNet
    from pm4py.objects.petri_net.utils.petri_utils import add_arc_from_to

    net = PetriNet()
    places = {}
    for place_name in spec["places"]:
        places[place_name] = PetriNet.Place(place_name)
        net.places.add(places[place_name])
    transitions = {}
    for t in spec["transitions"]:
        trans = PetriNet.Transition(t["name"], t["label"])
        transitions[t["name"]] = trans
        net.transitions.add(trans)
    for arc in spec["arcs"]:
        src = places.get(arc["source"]) or transitions.get(arc["source"])
        tgt = places.get(arc["target"]) or transitions.get(arc["target"])
        if src is None or tgt is None:
            continue
        # add_arc_from_to wires node-level in/out arcs; arcs.add() alone does not.
        add_arc_from_to(src, tgt, net)
    initial = Marking()
    for place_name, tokens in spec.get("initial_marking", {}).items():
        if place_name in places:
            initial[places[place_name]] = tokens
    final = Marking()
    for place_name, tokens in spec.get("final_marking", {}).items():
        if place_name in places:
            final[places[place_name]] = tokens
    return net, initial, final


def build_dataframe_from_log(db: Session, log_id: int, max_cases: int | None) -> "Any":
    """Load events into a pm4py-compatible DataFrame, ordered for case assembly.
    max_cases limits the run (sampled by ascending case_id for determinism)."""
    import pandas as pd

    case_stmt = select(Event.case_id).where(Event.log_id == log_id).distinct().order_by(Event.case_id)
    if max_cases:
        case_stmt = case_stmt.limit(max_cases)
    case_ids = [row[0] for row in db.execute(case_stmt)]
    if not case_ids:
        return pd.DataFrame(columns=["case:concept:name", "concept:name", "time:timestamp"])

    stmt = (
        select(Event.case_id, Event.activity, Event.timestamp)
        .where(Event.log_id == log_id, Event.case_id.in_(case_ids))
        .order_by(Event.case_id, Event.timestamp, Event.id)
    )
    rows = [
        {"case:concept:name": c, "concept:name": a, "time:timestamp": _ensure_utc(t)}
        for c, a, t in db.execute(stmt)
    ]
    return pd.DataFrame(rows)


def classify_alignment(alignment: list) -> dict:
    """Classify one pm4py alignment.

    Entries are (log_move, model_move):
    - sync:          ("a", "a")
    - move on log:   ("a", ">>")  → behaviour not allowed by the model
    - visible model: (">>", "A")  → model expects a labelled step the log skipped
    - silent model:  (">>", None) → invisible τ execution, expected in any run
    Only log moves and *visible* model moves mean non-conformance.
    """
    log_moves = 0
    visible_model_moves = 0
    silent_moves = 0
    for m in alignment or []:
        src, tgt = m[0], m[1]
        if tgt == ">>":
            log_moves += 1
        elif src == ">>":
            if tgt is None:
                silent_moves += 1
            else:
                visible_model_moves += 1
    return {
        "conforming": log_moves == 0 and visible_model_moves == 0,
        "log_moves": log_moves,
        "visible_model_moves": visible_model_moves,
        "silent_moves": silent_moves,
    }


def run_alignments(
    db: Session,
    log: EventLog,
    model_id: int,
    max_cases: int | None = 10_000,
) -> dict:
    """Run alignment-based conformance between a stored model and the log.

    The model may originate from a *different* log — that's the reference-
    model use case: discover or import one regulatory model, then check every
    log against it.
    """
    import pm4py

    model = db.get(ModelDefinition, model_id)
    if model is None:
        raise ValueError("Model not found")

    net, initial, final = deserialize_petri_net(model.spec["petri_net"])
    df = build_dataframe_from_log(db, log.id, max_cases)
    if df.empty:
        raise ValueError("Log has no events to check")

    diagnostics = pm4py.conformance_diagnostics_alignments(df, net, initial, final)
    total = len(diagnostics)

    states = []
    for d in diagnostics:
        state = classify_alignment(d.get("alignment"))
        state["fitness"] = d.get("fitness", 0.0)
        state["cost"] = d.get("cost")
        states.append(state)
    conforming = sum(1 for s in states if s["conforming"])
    fitnesses = [s["fitness"] for s in states]

    worst = sorted(states, key=lambda s: (s["conforming"], s["fitness"], -s["log_moves"]))[:10]
    return {
        "model_id": model.id,
        "model_name": model.name,
        "cases_checked": total,
        "max_cases": max_cases,
        "perfect_fits": conforming,
        "non_conforming": total - conforming,
        "conformance_rate": round(conforming / total, 4) if total else 0.0,
        "avg_fitness": round(sum(fitnesses) / total, 4) if total else 0.0,
        "total_log_moves": sum(s["log_moves"] for s in states),
        "total_visible_model_moves": sum(s["visible_model_moves"] for s in states),
        "worst_cases": worst,
    }
