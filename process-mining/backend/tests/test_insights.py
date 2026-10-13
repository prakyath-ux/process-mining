"""Tests for the compare/slice + drill-down endpoints:

- date-range and attribute filters on analytics endpoints
- attribute discovery, group-by breakdown
- handover network, timeline sampling
- case search + variant drill-down lists
- reference models: import + cross-log conformance
"""

from .conftest import b64

HANDOVER_CSV = """case_id,activity,timestamp,user
H1,Receive,2025-02-01 09:00,alice
H1,Review,2025-02-01 11:00,alice
H1,Approve,2025-02-01 15:00,bob
H1,Close,2025-02-02 09:00,bob
H2,Receive,2025-02-03 09:00,alice
H2,Review,2025-02-03 12:00,alice
H2,Reject,2025-02-04 09:00,bob
H2,Close,2025-02-04 17:00,bob
H3,Receive,2025-02-05 09:00,carol
H3,Review,2025-02-05 10:00,carol
H3,Close,2025-02-06 09:00,carol
"""


def test_date_range_filter_narrows_analytics(client, auth_headers, uploaded_log):
    # SMALL_CSV events span 2025-01-01..05; cutting off Jan 1 leaves 8 events.
    resp = client.get(
        f"/api/logs/{uploaded_log}/process-map?start=2025-01-02T00:00:00Z",
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    stats = resp.json()["stats"]
    assert stats["event_count"] == 8  # C1:2, C2:2, C3:4
    assert stats["case_count"] == 3
    assert stats["filtered"] is True

    # full log unchanged
    full = client.get(f"/api/logs/{uploaded_log}/process-map", headers=auth_headers).json()
    assert full["stats"]["event_count"] == 12
    assert full["stats"]["filtered"] is False


def test_attribute_filter_keeps_whole_cases(client, auth_headers, uploaded_log):
    # amount 20000 → only C2, and all 4 of its events (whole-case semantics).
    resp = client.get(
        f"/api/logs/{uploaded_log}/process-map?attr=amount&attr_value=20000",
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    stats = resp.json()["stats"]
    assert stats["case_count"] == 1
    assert stats["event_count"] == 4
    node_ids = {n["id"] for n in resp.json()["nodes"]}
    assert "Rejected" in node_ids and "Approved" not in node_ids


def test_attr_without_value_is_rejected(client, auth_headers, uploaded_log):
    resp = client.get(f"/api/logs/{uploaded_log}/process-map?attr=amount", headers=auth_headers)
    assert resp.status_code == 400


def test_attributes_endpoint(client, auth_headers, uploaded_log):
    resp = client.get(f"/api/logs/{uploaded_log}/attributes", headers=auth_headers)
    assert resp.status_code == 200
    attrs = {a["key"]: a for a in resp.json()["attributes"]}
    assert "amount" in attrs
    assert set(attrs["amount"]["samples"]) == {"10000", "20000", "30000"}


def test_breakdown_groups_by_attribute(client, auth_headers, uploaded_log):
    resp = client.get(f"/api/logs/{uploaded_log}/breakdown?attr=amount", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["attribute"] == "amount"
    values = {row["value"]: row for row in body["values"]}
    assert set(values) == {"10000", "20000", "30000"}
    # each amount has exactly one case with a real duration
    assert all(v["cases"] == 1 for v in values.values())
    assert values["30000"]["p50_duration_s"] > 0
    assert body["truncated"] is False


def test_breakdown_unknown_attribute_404(client, auth_headers, uploaded_log):
    resp = client.get(f"/api/logs/{uploaded_log}/breakdown?attr=nope", headers=auth_headers)
    assert resp.status_code == 404


def _uploaded_handover_log(client, auth_headers):
    resp = client.post(
        "/api/ingest/file",
        headers=auth_headers,
        files={"file": ("handover.csv", HANDOVER_CSV.encode(), "text/csv")},
        data={
            "name": "handover-log",
            "case_col": "case_id",
            "activity_col": "activity",
            "timestamp_col": "timestamp",
            "attr_columns": "user",
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["log_id"]


def test_handover_network(client, auth_headers):
    log_id = _uploaded_handover_log(client, auth_headers)
    resp = client.get(f"/api/logs/{log_id}/handover?actor_attr=user", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    nodes = {n["id"]: n for n in body["nodes"]}
    assert set(nodes) == {"alice", "bob", "carol"}
    assert nodes["alice"]["events"] == 4
    assert nodes["carol"]["events"] == 3
    edges = {(e["source"], e["target"]): e for e in body["edges"]}
    assert ("alice", "bob") in edges
    assert edges[("alice", "bob")]["count"] == 2  # H1 and H2 both hand over
    assert ("carol", "bob") not in edges  # carol never hands off
    # handover wait exists for alice→bob (Review→Approve H1: 4h, H2 next day)
    assert edges[("alice", "bob")]["avg_wait_s"] > 0


def test_timeline_samples_cases(client, auth_headers, uploaded_log):
    resp = client.get(f"/api/logs/{uploaded_log}/timeline?limit=100", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total_cases"] == 3
    assert body["sampled_cases"] == 3
    assert "Application Received" in body["activities"]
    first = body["cases"][0]
    assert first["case_id"].startswith("C")
    assert all("ts" in e for e in first["events"])


def test_case_search_by_substring(client, auth_headers, uploaded_log):
    resp = client.get(f"/api/logs/{uploaded_log}/cases?q=C1", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total_matching"] == 1
    case = body["cases"][0]
    assert case["case_id"] == "C1"
    assert case["events"] == 4
    assert case["start_activity"] == "Application Received"
    assert case["last_activity"] == "Closed"


def test_case_search_requires_query(client, auth_headers, uploaded_log):
    resp = client.get(f"/api/logs/{uploaded_log}/cases", headers=auth_headers)
    assert resp.status_code == 400


def test_variant_case_list(client, auth_headers, uploaded_log):
    import json as _json

    variant = _json.dumps(["Application Received", "Credit Check", "Approved", "Closed"])
    resp = client.get(f"/api/logs/{uploaded_log}/cases", params={"variant": variant}, headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total_matching"] == 2  # C1 and C3 share this variant
    assert {c["case_id"] for c in body["cases"]} == {"C1", "C3"}
    assert all(c["events"] == 4 for c in body["cases"])


def test_variants_expose_case_samples(client, auth_headers, uploaded_log):
    resp = client.get(f"/api/logs/{uploaded_log}/variants?top=5", headers=auth_headers)
    assert resp.status_code == 200
    top = resp.json()["variants"][0]
    assert "case_samples" in top
    assert len(top["case_samples"]) == top["cases"] <= 100


def test_cross_log_reference_conformance(client, auth_headers, uploaded_log):
    """Import a strict reference model, then check the log against it —
    the regulatory-model use case."""
    log_id = uploaded_log
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
    }
    imported = client.post(
        "/api/models/import",
        headers=auth_headers,
        json={"name": "Regulatory baseline", "log_id": log_id, "miner": "reference", "spec": spec},
    )
    assert imported.status_code == 201, imported.text
    model_id = imported.json()["id"]

    listed = client.get("/api/models", headers=auth_headers)
    assert listed.status_code == 200
    assert any(m["id"] == model_id and m["name"] == "Regulatory baseline" for m in listed.json())

    conf = client.post(
        f"/api/logs/{log_id}/conformance",
        headers=auth_headers,
        json={"model_id": model_id, "max_cases": 100},
    )
    assert conf.status_code == 200, conf.text
    body = conf.json()
    assert body["cases_checked"] == 3
    assert body["non_conforming"] == 1  # C2 goes through 'Rejected' — off-model
    assert body["conformance_rate"] == 0.6667

    audited = [r["action"] for r in client.get("/api/audit", headers=auth_headers).json()]
    assert "model_imported" in audited


def test_import_rejects_malformed_spec(client, auth_headers, uploaded_log):
    resp = client.post(
        "/api/models/import",
        headers=auth_headers,
        json={"name": "Broken", "log_id": uploaded_log, "spec": {"petri_net": {"places": []}}},
    )
    assert resp.status_code == 422


def test_filters_apply_to_variants_and_bottlenecks(client, auth_headers, uploaded_log):
    base = f"/api/logs/{uploaded_log}"
    # amount filter: only C2's variant remains
    v = client.get(f"{base}/variants?attr=amount&attr_value=10000", headers=auth_headers).json()
    assert v["case_count"] == 1
    assert v["variants"][0]["activities"] == [
        "Application Received",
        "Credit Check",
        "Approved",
        "Closed",
    ]
    # date filter: bottlenecks recomputed for the window (only C3 reaches
    # 2025-01-04+, via Approved→Closed — a single 24h wait on Closed)
    b = client.get(
        f"{base}/bottlenecks?start=2025-01-04T00:00:00Z&top=5", headers=auth_headers
    )
    assert b.status_code == 200
    assert b.json()["case_durations"]["count"] == 1
    assert [row["activity"] for row in b.json()["bottlenecks"]] == ["Closed"]
