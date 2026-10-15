"""End-to-end API flow tests: auth → ingest → mine → discover → conformance."""

import json

from .conftest import SMALL_CSV, b64


def test_health(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_login_and_me(client, auth_headers):
    resp = client.get("/api/auth/me", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["role"] == "admin"


def test_bad_login_rejected(client):
    resp = client.post("/api/auth/login", data={"username": "admin@test.local", "password": "wrong"})
    assert resp.status_code == 401


def test_unauthenticated_rejected(client):
    assert client.get("/api/logs").status_code == 401


def test_csv_preview(client, auth_headers):
    resp = client.post(
        "/api/ingest/preview-csv",
        headers=auth_headers,
        json={"data_base64": b64(SMALL_CSV.encode())},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["columns"] == ["case_id", "activity", "timestamp", "amount"]
    assert len(body["rows"]) > 0


def test_ingest_and_stats(client, auth_headers, uploaded_log):
    resp = client.get(f"/api/logs/{uploaded_log}", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ready"
    assert body["case_count"] == 3
    assert body["event_count"] == 12
    assert body["activity_count"] == 5  # Received, Check, Approved, Rejected, Closed


def test_process_map(client, auth_headers, uploaded_log):
    resp = client.get(f"/api/logs/{uploaded_log}/process-map", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    node_ids = {n["id"] for n in body["nodes"]}
    assert "Application Received" in node_ids
    assert "__START__" in node_ids and "__END__" in node_ids
    edges = {(e["source"], e["target"]) for e in body["edges"]}
    assert ("Application Received", "Credit Check") in edges
    assert ("Credit Check", "Approved") in edges
    # bottleneck scores present for activities with waits
    assert body["bottleneck_scores"]


def test_variants(client, auth_headers, uploaded_log):
    resp = client.get(f"/api/logs/{uploaded_log}/variants", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_variants"] == 2  # C1/C3 share a trace; C2 differs
    assert body["case_count"] == 3
    top = body["variants"][0]
    assert top["cases"] >= 1
    assert "cumulative_share" in top


def test_bottlenecks(client, auth_headers, uploaded_log):
    resp = client.get(f"/api/logs/{uploaded_log}/bottlenecks", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["bottlenecks"]
    assert body["case_durations"]["count"] == 3
    # rankings sorted by score desc
    scores = [b["score"] for b in body["bottlenecks"]]
    assert scores == sorted(scores, reverse=True)


def test_model_discovery_and_conformance(client, auth_headers, uploaded_log):
    resp = client.post(
        f"/api/logs/{uploaded_log}/models",
        headers=auth_headers,
        json={"name": "Baseline", "miner": "inductive"},
    )
    assert resp.status_code == 201, resp.text
    model_id = resp.json()["id"]

    got = client.get(f"/api/logs/{uploaded_log}/models/{model_id}", headers=auth_headers)
    assert got.status_code == 200
    spec = got.json()["spec"]
    assert spec["petri_net"]["places"]
    assert spec["start_activities"] == ["Application Received"]

    # perfect log against its own discovered model
    conf = client.post(
        f"/api/logs/{uploaded_log}/conformance",
        headers=auth_headers,
        json={"model_id": model_id, "max_cases": 1000},
    )
    assert conf.status_code == 200, conf.text
    body = conf.json()
    assert body["cases_checked"] == 3
    assert body["conformance_rate"] == 1.0


def test_audit_trail(client, auth_headers, uploaded_log):
    resp = client.get("/api/audit", headers=auth_headers)
    assert resp.status_code == 200
    actions = [r["action"] for r in resp.json()]
    assert "login" in actions
    assert "ingest_completed" in actions
    assert "model_discovered" in actions
    assert "conformance_run" in actions


def test_ingest_streaming_progress(client, auth_headers):
    """`?stream=1` emits NDJSON stage/progress/done events while ingesting."""
    resp = client.post(
        "/api/ingest/file?stream=true",
        headers=auth_headers,
        files={"file": ("stream.csv", SMALL_CSV.encode(), "text/csv")},
        data={
            "name": "stream-log",
            "case_col": "case_id",
            "activity_col": "activity",
            "timestamp_col": "timestamp",
            "attr_columns": "amount",
        },
    )
    assert resp.status_code == 200, resp.text
    assert "application/x-ndjson" in resp.headers["content-type"]

    events = [json.loads(line) for line in resp.text.splitlines() if line.strip()]
    assert events, "stream contained no events"
    assert events[0]["type"] == "stage" and events[0]["stage"] == "parsing"
    assert events[0]["total"] == 12  # header excluded: 12 data rows
    done = [e for e in events if e["type"] == "done"]
    assert len(done) == 1
    assert done[0]["inserted"] == 12 and done[0]["skipped"] == 0
    assert "elapsed_s" in done[0]
    # every line carries elapsed time, and progress events exist before done
    assert all("elapsed_s" in e for e in events)
    assert any(e["type"] == "progress" for e in events)

    # the log must be usable right after the stream finishes
    got = client.get(f"/api/logs/{done[0]['log_id']}", headers=auth_headers)
    assert got.status_code == 200
    assert got.json()["status"] == "ready"
    assert got.json()["event_count"] == 12


def test_rbac_viewer_cannot_ingest(client, auth_headers):
    created = client.post(
        "/api/auth/users",
        headers=auth_headers,
        json={"email": "viewer@example.com", "password": "viewer12345", "role": "viewer"},
    )
    assert created.status_code == 201
    login = client.post(
        "/api/auth/login", data={"username": "viewer@example.com", "password": "viewer12345"}
    )
    token = {"Authorization": f"Bearer {login.json()['access_token']}"}
    # viewer can read
    assert client.get("/api/logs", headers=token).status_code == 200
    # viewer cannot ingest
    resp = client.post(
        "/api/ingest/file",
        headers=token,
        files={"file": ("t.csv", b"a,b,c", "text/csv")},
        data={"name": "x", "case_col": "a", "activity_col": "b", "timestamp_col": "c"},
    )
    assert resp.status_code == 403
