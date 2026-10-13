# ProMine — Process Mining for Financial Operations

> 📖 **New here?** Read [`docs/promine-guide.md`](docs/promine-guide.md) first —
> plain-language Q&A on how process mining works, where every number comes
> from, a 5-minute demo script, and the full feature list.

Batch process-mining platform (Phase 1) with an ingestion layer designed so
Phase 2's streaming source drops in without schema changes.

**Stack:** FastAPI + pm4py + SQLAlchemy (Python) · Next.js 14 + React Flow (TypeScript)

## Architecture

```
frontend/  Next.js 14 (App Router, client components, React Flow + dagre)
backend/
  app/
    config.py        env-driven settings (PM_* prefix)
    db.py            engine/session (SQLite dev, Postgres via PM_DATABASE_URL)
    models.py        users, event_logs, events, audit_log, model_definitions
    security.py      PBKDF2 hashing, JWT, role guard (viewer/analyst/admin)
    audit.py         append-only audit trail helper
    api/
      auth.py        login, me, user management
      logs.py        log CRUD, case drill-down, audit, global model import/list
      ingest.py      CSV/XES upload (with preview) + SQL pull
      analytics.py   process-map, variants, bottlenecks, models, conformance
      insights.py    attributes, breakdown, handover, timeline, case search
    ingestion/
      sources.py     pluggable sources → normalized events (batched inserts)
    mining/
      analytics.py   single-pass streaming: DFG, variants, waits, percentiles
      discovery.py   process map + Petri net discovery from aggregated DFG
      conformance.py alignment diagnostics + classification
  tests/             32 pytest cases (API flow, RBAC, conformance, filters, insights)
scripts/
  generate_sample_log.py   synthetic 20k-case loan origination log (246k events)
```

### Design decisions (scale & compliance)

- **Normalized event schema** (`log_id, case_id, activity, timestamp, lifecycle, attrs`)
  works across CSV, XES, SQL, and (future) streams — sources are iterables of
  rows so a Kafka source needs no writer changes.
- **Single-pass streaming analytics**: one ordered scan (covered by the
  `(log_id, case_id, timestamp)` index) computes DFG, variants, queue waits,
  and cycle-time percentiles (bounded reservoirs). Memory scales with
  activities/edges/variants, not events. Results cached per `(log, event_count)`.
- **Discovery never materializes pm4py logs**: the inductive/alpha miners run on
  the *aggregated* DFG (pm4py accepts a `DirectlyFollowsGraph` directly).
- **Alignment conformance** caps/sample-runs (default 10k cases, ~1.5s);
  silent τ model moves are classified separately from true deviations.
- **RBAC** viewer/analyst/admin + PBKDF2 passwords + append-only audit log of
  logins, ingests, discoveries, conformance runs.

## Run it

```bash
# Backend (http://localhost:8000, docs at /docs)
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --reload

# Frontend (http://localhost:3000)
cd frontend
npm install
npm run dev
```

Seed login: `admin@example.com` / `admin12345` (override via
`PM_SEED_ADMIN_EMAIL` / `PM_SEED_ADMIN_PASSWORD`, set `PM_JWT_SECRET` in prod).

Load the demo data:

```bash
python3 scripts/generate_sample_log.py 20000 sample_data/loan_origination.csv
# then in the UI: Ingest Data → map case_id/activity/timestamp → Ingest
```

## Tests

```bash
cd backend && .venv/bin/python -m pytest tests/ -q   # 32 passed
cd frontend && npm run typecheck                     # tsc clean
cd frontend && npx next build                        # production build
```

## Measured performance (this machine, SQLite dev)

| Operation                              | Scale             | Time    |
|----------------------------------------|-------------------|---------|
| CSV ingest (~246k events / 20k cases)| 18 MB file        | ~70 s   |
| Cold process-map + full analytics scan | 246k events       | ~1.8 s  |
| Cached process-map / variants / bottlenecks | same         | 10–20 ms|
| Petri net discovery (DFG-based)        | full log          | <1 s    |
| Alignments, 10k cases                  | 10k cases         | ~1.5 s  |
| Alignments, 20k cases                  | 20k cases         | ~2 s    |

Postgres (set `PM_DATABASE_URL`) raises ingest throughput substantially —
SQLite is single-writer.

## Phase 2 (streaming) — planned seam

`ingestion/sources.py` sources yield normalized row dicts; a Kafka consumer can
feed `_write_batches` directly. The UI's Ingest page gains a "stream" tab;
`event_logs.source_type='stream'` already exists.

## ⚠️ Licensing note

pm4py is **AGPL-3.0** (its Community Version). If ProMine stays closed-source
and is offered as a service, you likely need pm4py's commercial license —
or swap `mining/discovery.py` + `mining/conformance.py` for an in-house
implementation of the same functions (the rest of the app has no pm4py import).
Confirm with your legal team before shipping.
