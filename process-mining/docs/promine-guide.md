# ProMine — How It Works (Q&A Guide)

> A plain-language reference for the ProMine process-mining app:
> what the concepts mean, where every number comes from, what runs behind the
> scenes, and a guided demo. Keep this next to the code — it's meant for
> remembering, not reading once.

---

## Q1. What is process mining in the first place?

Every business system you use (core banking, CRM, workflow tools) quietly
writes a diary: *"Loan LN-0042 reached 'KYC Cleared' at 10:42"*. Millions of
little "this happened" notes.

**Process mining** = reconstructing how work *actually flows* from those
notes, instead of trusting the flowchart someone drew three years ago.

It answers the three classic questions, mapped to ProMine's tabs:

| Question | Meaning | ProMine tab |
|---|---|---|
| Discovery — *"What does our process really look like?"* | Reconstruct the real flow | **Map** |
| Enhancement — *"Where does it get stuck?"* | Find queues & variants | **Bottlenecks**, **Variants** |
| Conformance — *"Does reality obey the rules we think we have?"* | Compare cases vs a model | **Conformance** |

Traditional BI tells you *how many* loans were approved. Process mining tells
you **the path each loan took, how long each hop took, and who deviated**.

---

## Q2. Event logs, the tabs, and the flowchart

### Where does the data come from?

You put it there. An **event log** is just rows like:

| case_id | activity | timestamp |
|---|---|---|
| LN-000001 | Application Received | 2025-01-06 09:14 |
| LN-000001 | Credit Score Obtained | 2025-01-06 15:02 |
| LN-000001 | KYC Started | 2025-01-07 08:30 |

- **case_id** = one item of work (one loan)
- **activity** = a step
- **timestamp** = when it happened

In production these rows come from your actual systems — a CSV/XES export or
a direct SQL query (exactly what the **Ingest Data** page does). The demo log
is synthetic data (20,000 loans / ~246k events) generated so there's
something realistic to explore.

### Are the tabs hardcoded?

No — **every tab is computed from those rows**:

| Tab | What it computes from your data |
|---|---|
| Overview | Counts, date range, avg events per case, available attributes |
| Map | Which activity usually follows which (frequency + wait times) |
| Variants | The distinct paths cases took, ranked by how many followed each |
| Bottlenecks | Time between steps, per activity — where queues build; plus *Compare by* group tables |
| Cases | Case search + per-variant case lists → event-timeline drill-down with waits |
| Timeline | Sampled dotted chart: time × cases, dots colored by activity |
| Handover | Who hands work to whom, from an actor attribute (bots & humans) |
| Conformance | Each case checked against a model (incl. imported reference models) |

All analytics tabs respect the **filter bar** (date range + attribute slice).
See **Q5** below for details.

### How was the flowchart created? Is it of the process or the data?

It **is your process, extracted from the data** — not hand-drawn:

1. The algorithm reads every case's sequence: A → B → C …
2. It counts every direct hop: *"KYC Cleared → Documents Requested" happened
   18,402 times*
3. Those counts become the **Map**:
   - each **box** = an activity (colored by bottleneck heat)
   - each **arrow** = a transition (thickness = frequency, label = count +
     average time)

If reality has a shortcut nobody documented — say some loans skip document
collection — **an extra arrow appears on the map**. The diagram can't disagree
with the data, because the data *is* the diagram.

---

## Q3. What algorithm is used? Is an LLM doing the calculations?

**No LLM, no AI predictions — pure deterministic math.** That's deliberate:
auditors must be able to reproduce any number shown, and "the model kind of
felt like 87%" is not evidence.

| Part | How it works |
|---|---|
| Map / Variants / Bottlenecks | One **streaming pass** over all ~246k events: count transitions, sum wait times, bucket percentiles via **reservoir sampling** (estimates percentiles in constant memory) |
| Model discovery (Petri net) | **Inductive Miner** — a classic academic algorithm that recursively splits the data into *sequence*, *parallel*, and *choice* blocks until a complete process model is built. An *alpha miner* is also available (plus a noise threshold to prune rare behavior) |
| Conformance (alignments) | Treated like **diff/merge for processes**: for each case, search for the cheapest set of edits to make the case's path match the model. A move where "this loan did something the model forbids" = deviation. Runs on a fast A*/LP-solver search — 10,000 cases in ~1.5s (measured) |

Rule of thumb: **SQL + counting** for the numbers, **combinatorial search**
for model checking. An LLM could later *narrate* findings ("Credit Review adds
4 days median…") but never be the one *producing* them.

---

## Q4. What are the "Ingest Data" and "Audit Trail" sections?

- **Ingest Data** = the intake pipeline. You give it a file (or SQL query),
  tell it which column is case ID / activity / timestamp (it auto-guesses from
  a preview), and it validates, normalizes to the standard schema, and loads
  it in batches. Failed loads are marked `failed`, not silently dropped
  (you saw "skipped: 0" for clean data).

  While it loads you get a **live progress panel**: current stage (parsing →
  writing → computing statistics), a progress bar, rows written / total,
  elapsed seconds and rows/sec. These are **not animated placeholders** — the
  server streams real counters over NDJSON (`POST /api/ingest/file?stream=1`)
  from the batch writer itself, so the numbers match the file you uploaded.
  A 245k-row file reports 50 progress ticks and finishes in ~9s (it took
  ~70s before the timestamp fast path).

- **Audit Trail** = the compliance black box. Every meaningful action —
  login, ingest, model discovery, conformance run — is written to an
  **append-only** table with *who, what, when*. This is the evidence for
  "who ran this analysis and when" during a regulatory review.
  Admin-only.

---

## Q5. What do the newer features do — filters, compare, drill-down, timeline, handover?

**Filters (top of every log page)**
- **Date range** — analyze only events in a window (e.g. before/after a policy
  change). Cases are evaluated within the window.
- **Slice by attribute** — keep only cases where *any* event carries a value
  (e.g. `branch=NY`). Whole cases are kept — never counted halfway.

**Bottlenecks → “Compare by attribute”** — cycle time + top waits per value:
per analyst, per branch, per automation engine. Instantly answers
*“is it slower in region X / with agent Y?”*

**Cases tab** — search a case id, or click “cases →” next to any variant row;
then click a case to open the **event-timeline drill-down**: every step with
its wait time highlighted (the view auditors ask for).

**Timeline tab (dotted chart)** — x = time, one row per sampled case, dots
colored by activity; bursts and elongated cases jump out.

**Handover tab** — who hands work to whom: actors come from an attribute
(default `user`), so bots (`kyc.engine`, `docs.bot`, `credit.api`) and humans
appear in one network; edges carry handover count and average wait until the
next actor picked the work up.

**Reference models (Conformance tab)**
- *Import reference model* — paste a Petri-net JSON spec (your regulatory
  process) and store it as a model.
- Models from **any log** can be selected — discover one baseline, check every
  other log against it.

---

## 🎯 5-minute guided demo

1. **Login** → `admin@example.com` / `admin12345`
2. **Event Logs** → open **"Loan Origination 2025"** → **Overview**
   (20,000 cases, ~246k events)
3. **Map tab** → wait ~2s the first time (computing), then notice
   **Credit Review** is 🔴 red. Click it → pop-up shows wait p50 ≈ 90h.
   Scroll to zoom, drag to pan. This flowchart was built from the ~246k rows.
4. **Bottlenecks tab** → ranked bars: Credit Review (79) > Documents Received
   (57) > Compliance Hold (37). Stat cards: median case takes ~7.5 days.
5. **Variants tab** → 20 distinct paths exist; **6 cover 80% of all loans**
   (Pareto insight = where to standardize).
6. **Conformance tab** → name a model → **① Discover model** →
   **② Run alignment** → ~100% conformance, since the model was learned
   *from* this same data. (Baseline behavior — deviations appear when you
   check against a *regulatory* reference model.)
7. **Ingest Data** → upload your own CSV, watch the column auto-guess, map,
   ingest → watch the **live progress panel** (stage, bar, rows, rows/s)
   while it loads → a new log appears in the list. To try other processes,
   generate 3 more demo logs first:
   `python3 scripts/generate_demo_logs.py` → **Purchase-to-Pay** (bottleneck
   + conformance deviations), **Insurance Claims** (case drill-down),
   **IT Incidents** (handover network).
8. **Audit Trail** → everything you just did, listed with timestamps.
9. **New tabs**: try **Cases** (search `LN-0042` → click a case → timeline),
   **Timeline** (dotted chart), **Handover** (bot↔human network), and on
   **Bottlenecks** use *Compare by* `user` to rank analysts.
10. *(Optional)* Log in as a **viewer** (create one via the API as admin) —
    they can read but get 403 on ingest. Roles really gate actions.

---

## 📦 ProMine — complete feature list

### Authentication & security
- JWT login/logout, session expiry
- 3 roles: **admin / analyst / viewer** (route-enforced — viewers can't
  ingest; only admins see audit/SQL/delete)
- PBKDF2-SHA256 password hashing (390K iterations), no plaintext anywhere
- Env-driven config (`PM_*`), production secret override ready

### Ingestion
- CSV upload with **column-preview + auto-guess mapping**
  (case / activity / timestamp / lifecycle / extra attrs)
- **Live progress streaming**: `?stream=1` returns NDJSON
  (`stage` → `progress` → `done`/`error`, each with elapsed seconds) while
  the ingest runs; the Ingest page renders it as stage label + progress bar
  + rows/s. Classic JSON mode (no query param) is unchanged
- XES upload (process-mining standard format), auto-mapped
- **SQL pull** (admin): read-only SELECT from an external DB; credentials
  are used for the query and never stored
- Batched inserts (5,000/batch), bad rows counted & skipped,
  status `ready` / `failed`
- Pluggable source interface → a Kafka source drops in for phase 2

### Mining & analytics
- **Process map**: DFG discovery, frequency-weighted edges,
  wait/active-time per node, bottleneck heat coloring, START/END nodes
- **Bottleneck scoring**: 0.7 × relative-wait + 0.3 × load, ranked
- **Variants**: all distinct traces ranked, cumulative share, Pareto-80 count
- **Case cycle-time percentiles** (p50/p90/p95) via bounded reservoirs
- **Model discovery**: inductive miner (default) or alpha miner, with noise
  threshold, persisted as reusable Petri-net models
- **Conformance**: alignment-based; τ/silent moves separated from true
  deviations; worst-cases table; configurable case cap/sampling;
  **cross-log reference models** (import JSON or discover once, check any log)
- **Compare & slice**: date-range filters + attribute slices on every
  analytics endpoint; group-by breakdown (cycle time / top waits per value)
- **Case drill-down**: id search + per-variant case lists + full event
  timeline with per-step waits
- **Visualizations**: dotted timeline chart; organizational handover network
  (actors from any attribute — bots & humans)
- **Single-pass streaming analytics** + per-`(log, event_count, filters)` cache
  (cold ~1.8s → warm 10–35ms)

### Data model & compliance
- Normalized event schema + 3 performance indexes
  (case/time, activity/time, time)
- Tables: `users`, `event_logs`, `events`, `model_definitions`, `audit_log`
  (append-only)
- Case drill-down endpoint (`GET /api/logs/{id}/cases/{case_id}`)
  for audit investigations

### Interface (7 routes)
- Login · Logs list · **Log detail** (Overview / Map / Variants /
  Bottlenecks / Cases / Timeline / Handover / Conformance tabs + filter bar)
  · Ingest (file + SQL forms) · Audit (admin) · Home redirect ·
  API docs at `:8000/docs`

### API surface
- `/api/auth/*` — login, me, user management
- `/api/logs*` — list, detail, delete, case trace
- `/api/ingest/*` — preview-csv, file, sql
- `/api/logs/{id}/*` — process-map, variants, bottlenecks,
  models CRUD, conformance, **attributes, breakdown, handover,
  timeline, cases (search/variant)**
- `/api/models` — global model list, import, get (cross-log reference models)
- `/api/audit` · `/api/health`

### Quality
- **32 backend tests** (full API flow + RBAC + both conformance directions +
  filters, attribute slice, breakdown, handover, timeline, case search,
  variant lists, cross-log model import) — all passing
- TypeScript clean, production build clean, live E2E on all three data
  sources (CSV, XES, SQL)

### Measured performance (this machine, SQLite dev)

| Operation | Scale | Time |
|---|---|---|
| CSV ingest | ~246k events / 18 MB | ~70 s |
| Cold full analytics scan | ~246k events | ~1.8 s |
| Cached map/variants/bottlenecks (incl. filtered) | same | 10–35 ms |
| Model discovery | full log (DFG-based) | ~2.5 s |
| Alignments | 10,000 cases | ~1.5 s |
| Timeline (sampled 400 cases) | ~246k events | ~0.1 s |
| Breakdown / Handover (per-request scans) | ~246k events | ~3 s |

---

## ⚠️ Known caveats

- **pm4py is AGPL-3.0** — closed-source/commercial use likely requires
  their commercial license; confirm with legal before shipping.
- Dev runs on **SQLite**; production should use Postgres
  (`PM_DATABASE_URL`) for ingest throughput.
- Auth token is stored in `localStorage` today — move to httpOnly cookies
  before production.
- Phase 2 (streaming/Kafka) is designed-for but not implemented.
