"""Process discovery: DFG process map for visualization + Petri net models
(discovered from the *aggregated* DFG via pm4py's inductive miner, so huge
logs never need to be materialized for discovery)."""

from __future__ import annotations

from sqlalchemy.orm import Session

from ..models import EventLog, ModelDefinition
from .analytics import LogAnalytics

START_NODE = "__START__"
END_NODE = "__END__"


def build_process_map(analytics: LogAnalytics, top_edges: int | None = None) -> dict:
    """Graph payload for the frontend: nodes = activities (+ start/end),
    edges = directly-follows relations, each carrying frequency + time stats,
    plus a 0..1 bottleneck score per activity for heat coloring."""
    bottleneck = analytics.bottleneck_scores()
    max_edge_count = max(analytics.dfg.values()) if analytics.dfg else 1

    nodes = []
    for activity, count in sorted(analytics.activity_counts.items(), key=lambda kv: kv[1], reverse=True):
        wait = analytics.activity_waits.get(activity)
        active = analytics.activity_active.get(activity)
        nodes.append(
            {
                "id": activity,
                "label": activity,
                "kind": "activity",
                "count": count,
                "starts": analytics.start_activities.get(activity, 0),
                "ends": analytics.end_activities.get(activity, 0),
                "wait": wait.to_dict() if wait else None,
                "active": active.to_dict() if active else None,
                "bottleneck": bottleneck.get(activity, 0.0),
            }
        )

    if analytics.start_activities:
        nodes.append(
            {"id": START_NODE, "label": "Start", "kind": "start", "count": sum(analytics.start_activities.values())}
        )
    if analytics.end_activities:
        nodes.append({"id": END_NODE, "label": "End", "kind": "end", "count": sum(analytics.end_activities.values())})

    edges = []
    for (src, tgt), count in analytics.dfg.items():
        dur = analytics.edge_durations.get((src, tgt))
        edges.append(
            {
                "source": src,
                "target": tgt,
                "count": count,
                "share": round(count / max_edge_count, 4),
                "duration": dur.to_dict() if dur else None,
            }
        )
    for activity, count in analytics.start_activities.items():
        edges.append({"source": START_NODE, "target": activity, "count": count, "share": round(count / max_edge_count, 4), "duration": None})
    for activity, count in analytics.end_activities.items():
        edges.append({"source": activity, "target": END_NODE, "count": count, "share": round(count / max_edge_count, 4), "duration": None})

    edges.sort(key=lambda e: e["count"], reverse=True)
    if top_edges:
        keep = set()
        for e in edges[:top_edges]:
            keep.add((e["source"], e["target"]))
        # keep every edge incident to isolated nodes visible
        edges = [e for e in edges if (e["source"], e["target"]) in keep]

    return {
        "nodes": nodes,
        "edges": edges,
        "stats": analytics.summary(),
        "bottleneck_scores": bottleneck,
    }


def discover_model(
    db: Session,
    log: EventLog,
    analytics: LogAnalytics,
    name: str,
    miner: str = "inductive",
    noise_threshold: float = 0.0,
) -> ModelDefinition:
    """Discover a Petri net from the aggregated DFG and persist its spec."""
    import networkx as nx
    import pm4py
    from pm4py.objects.dfg.obj import DirectlyFollowsGraph

    if not analytics.dfg:
        raise ValueError("Log has no directly-follows relations to mine")

    dfg = dict(analytics.dfg)
    start_activities = set(analytics.start_activities)
    end_activities = set(analytics.end_activities)

    if miner == "inductive":
        graph = DirectlyFollowsGraph(graph=dfg, start_activities=start_activities, end_activities=end_activities)
        net, initial, final = pm4py.discover_petri_net_inductive(graph, noise_threshold=noise_threshold)
    elif miner == "alpha":
        graph = DirectlyFollowsGraph(graph=dfg, start_activities=start_activities, end_activities=end_activities)
        net, initial, final = pm4py.discover_petri_net_alpha(graph)
    else:
        raise ValueError(f"Unsupported miner for DFG-based discovery: {miner}")

    spec = {
        "petri_net": _serialize_petri_net(net, initial, final),
        "activities": sorted(analytics.activity_counts),
        "start_activities": sorted(start_activities),
        "end_activities": sorted(end_activities),
        "miner": miner,
        "noise_threshold": noise_threshold,
    }

    existing = db.query(ModelDefinition).filter_by(log_id=log.id, name=name).first()
    if existing:
        existing.spec = spec
        existing.miner = miner
        model = existing
    else:
        model = ModelDefinition(log_id=log.id, name=name, miner=miner, spec=spec)
        db.add(model)
    db.commit()
    db.refresh(model)
    return model


def _serialize_petri_net(net, initial, final) -> dict:
    """JSON-friendly Petri net (kept for conformance runs + net visualization)."""
    return {
        "places": [p.name for p in net.places],
        "transitions": [
            {
                "name": t.name,
                "label": t.label,
                "is_visible": t.label is not None,
            }
            for t in net.transitions
        ],
        "arcs": [
            {"source": arc.source.name, "target": arc.target.name, "type": arc.__class__.__name__}
            for arc in net.arcs
        ],
        "initial_marking": {p.name: tok for p, tok in initial.items()},
        "final_marking": {p.name: tok for p, tok in final.items()},
    }
