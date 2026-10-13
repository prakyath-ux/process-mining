"use client";

/** Log detail: overview, map, variants, bottlenecks (with compare-by),
 * cases drill-down, timeline, handover network, conformance (reference models).
 * A shared filter bar (date range + attribute slice) applies to all analytics. */

import { useParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import CaseDrilldown from "@/components/CaseDrilldown";
import HandoverGraph from "@/components/HandoverGraph";
import ProcessMap from "@/components/ProcessMap";
import Shell from "@/components/Shell";
import TimelineChart from "@/components/TimelineChart";
import {
  api,
  fmtDuration,
  fmtNumber,
  qs,
  type AttrInfo,
  type BottlenecksResponse,
  type BreakdownResponse,
  type CaseSearchResponse,
  type ConformanceResult,
  type GlobalModel,
  type LogFilters,
  type LogSummary,
  type ProcessMap as ProcessMapData,
  type VariantsResponse,
} from "@/lib/api";

type Tab =
  | "overview"
  | "map"
  | "variants"
  | "bottlenecks"
  | "cases"
  | "timeline"
  | "handover"
  | "conformance";

const EMPTY_FILTERS: LogFilters = {};

export default function LogDetailPage() {
  const params = useParams<{ id: string }>();
  const id = params?.id;
  const [log, setLog] = useState<LogSummary | null>(null);
  const [tab, setTab] = useState<Tab>("overview");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState<Record<string, boolean>>({});

  // --- shared filter state ---
  const [filters, setFilters] = useState<LogFilters>(EMPTY_FILTERS);
  const [startD, setStartD] = useState("");
  const [endD, setEndD] = useState("");
  const [attrKey, setAttrKey] = useState("");
  const [attrVal, setAttrVal] = useState("");
  const [attributes, setAttributes] = useState<AttrInfo[]>([]);

  // --- analytics data (invalidated when filters change) ---
  const [mapData, setMapData] = useState<ProcessMapData | null>(null);
  const [variants, setVariants] = useState<VariantsResponse | null>(null);
  const [bottlenecks, setBottlenecks] = useState<BottlenecksResponse | null>(null);
  const [breakdown, setBreakdown] = useState<BreakdownResponse | null>(null);
  const [compareAttr, setCompareAttr] = useState("");

  // --- cases tab ---
  const [caseQuery, setCaseQuery] = useState("");
  const [caseResults, setCaseResults] = useState<CaseSearchResponse | null>(null);
  const [casesVariant, setCasesVariant] = useState("");
  const [drillCase, setDrillCase] = useState<string | null>(null);

  // --- handover ---
  const [actorAttr, setActorAttr] = useState("user");

  // --- conformance ---
  const [models, setModels] = useState<GlobalModel[]>([]);
  const [selectedModel, setSelectedModel] = useState<number | null>(null);
  const [conformance, setConformance] = useState<ConformanceResult | null>(null);
  const [minerName, setMinerName] = useState("Discovered model");
  const [importName, setImportName] = useState("");
  const [importSpec, setImportSpec] = useState("");
  const [importOpen, setImportOpen] = useState(false);

  useEffect(() => {
    if (!id) return;
    api.get<LogSummary>(`/api/logs/${id}`).then(setLog).catch((e) => setError(String(e.message ?? e)));
    api
      .get<{ attributes: AttrInfo[] }>(`/api/logs/${id}/attributes`)
      .then((r) => setAttributes(r.attributes))
      .catch(() => setAttributes([]));
  }, [id]);

  const lazy = useCallback((key: string, loader: () => Promise<void>) => {
    setLoading((s) => ({ ...s, [key]: true }));
    loader()
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading((s) => ({ ...s, [key]: false })));
  }, []);

  const filterActive = Boolean(
    filters.start || filters.end || (filters.attr && filters.attr_value)
  );

  const applyFilters = () => {
    const next: LogFilters = {};
    if (startD) next.start = `${startD}T00:00:00+00:00`;
    if (endD) next.end = `${endD}T23:59:59+00:00`;
    if (attrKey && attrVal) {
      next.attr = attrKey;
      next.attr_value = attrVal;
    }
    setFilters(next);
    // invalidate everything derived from analytics
    setMapData(null);
    setVariants(null);
    setBottlenecks(null);
    setBreakdown(null);
    setConformance(null);
    setCaseResults(null);
    setDrillCase(null);
  };

  const clearFilters = () => {
    setStartD("");
    setEndD("");
    setAttrKey("");
    setAttrVal("");
    applyFiltersTo(EMPTY_FILTERS);
  };

  function applyFiltersTo(next: LogFilters) {
    setFilters(next);
    setMapData(null);
    setVariants(null);
    setBottlenecks(null);
    setBreakdown(null);
    setConformance(null);
    setCaseResults(null);
    setDrillCase(null);
  }

  // --- lazy loaders per tab ---
  useEffect(() => {
    if (!id || !log || log.status !== "ready") return;
    if (tab === "map" && !mapData) {
      lazy("map", async () =>
        setMapData(await api.get<ProcessMapData>(`/api/logs/${id}/process-map${qs(filters)}`))
      );
    }
    if (tab === "variants" && !variants) {
      lazy("variants", async () =>
        setVariants(await api.get<VariantsResponse>(`/api/logs/${id}/variants${qs(filters, { top: 50 })}`))
      );
    }
    if (tab === "bottlenecks" && !bottlenecks) {
      lazy("bottlenecks", async () =>
        setBottlenecks(await api.get<BottlenecksResponse>(`/api/logs/${id}/bottlenecks${qs(filters, { top: 25 })}`))
      );
    }
    if ((tab === "cases" || tab === "variants") && variants === null && attributes.length >= 0) {
      lazy("variants", async () =>
        setVariants(await api.get<VariantsResponse>(`/api/logs/${id}/variants${qs(filters, { top: 50 })}`))
      );
    }
    if (tab === "conformance" && models.length === 0) {
      lazy("models", async () => setModels(await api.get<GlobalModel[]>(`/api/models`)));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab, id, log, filters, models.length]);

  const filterQs = useMemo(() => qs(filters), [filters]);

  function runCompare() {
    if (!id || !compareAttr) return;
    lazy("compare", async () =>
      setBreakdown(
        await api.get<BreakdownResponse>(
          `/api/logs/${id}/breakdown${qs({ start: filters.start, end: filters.end }, { attr: compareAttr })}`
        )
      )
    );
  }

  function searchCases() {
    if (!id || !caseQuery.trim()) return;
    setCasesVariant("");
    setDrillCase(null);
    lazy("cases", async () =>
      setCaseResults(await api.get<CaseSearchResponse>(`/api/logs/${id}/cases${qs(filters, { q: caseQuery.trim() })}`))
    );
  }

  function casesForVariant(activities: string[]) {
    if (!id) return;
    const encoded = JSON.stringify(activities);
    setCasesVariant(encoded);
    setCaseQuery("");
    setDrillCase(null);
    setTab("cases");
    lazy("cases", async () =>
      setCaseResults(await api.get<CaseSearchResponse>(`/api/logs/${id}/cases${qs(filters, { variant: encoded })}`))
    );
  }

  async function discover() {
    if (!id) return;
    lazy("discover", async () => {
      const created = await api.post<{ id: number }>(`/api/logs/${id}/models`, {
        name: minerName || "Discovered model",
        miner: "inductive",
        noise_threshold: 0,
      });
      setModels(await api.get<GlobalModel[]>(`/api/models`));
      setSelectedModel(created.id);
      setConformance(null);
    });
  }

  async function importModel() {
    if (!id || !importName.trim() || !importSpec.trim()) return;
    lazy("import", async () => {
      let spec: unknown;
      try {
        spec = JSON.parse(importSpec);
      } catch {
        throw new Error("Spec is not valid JSON");
      }
      const created = await api.post<{ id: number }>(`/api/models/import`, {
        name: importName.trim(),
        log_id: Number(id),
        miner: "reference",
        spec,
      });
      setModels(await api.get<GlobalModel[]>(`/api/models`));
      setSelectedModel(created.id);
      setImportOpen(false);
      setImportName("");
      setImportSpec("");
      setConformance(null);
    });
  }

  async function runConformance() {
    if (!id || !selectedModel) return;
    lazy("conform", async () => {
      setConformance(
        await api.post<ConformanceResult>(`/api/logs/${id}/conformance`, {
          model_id: selectedModel,
          max_cases: 10000,
        })
      );
    });
  }

  if (!log) {
    return (
      <Shell title="Event Log">
        {error ? <div className="error-banner">{error}</div> : <div className="loading">Loading…</div>}
      </Shell>
    );
  }

  const cd = mapData?.stats.case_durations;

  return (
    <Shell
      title={log.name}
      subtitle={log.description || `Log #${log.id} · ${log.source_type}`}
      actions={filterActive ? <span className="filter-badge">filters active</span> : undefined}
    >
      {error && <div className="error-banner">{error}</div>}

      {/* ---- shared filter bar ---- */}
      <div className="filter-bar">
        <div className="form-row">
          <label>From</label>
          <input type="date" value={startD} onChange={(e) => setStartD(e.target.value)} />
        </div>
        <div className="form-row">
          <label>To</label>
          <input type="date" value={endD} onChange={(e) => setEndD(e.target.value)} />
        </div>
        <div className="form-row">
          <label>Slice by attribute</label>
          <select value={attrKey} onChange={(e) => setAttrKey(e.target.value)}>
            <option value="">— none —</option>
            {attributes.map((a) => (
              <option key={a.key} value={a.key}>
                {a.key}
              </option>
            ))}
          </select>
        </div>
        {attrKey && (
          <div className="form-row">
            <label>Value</label>
            <input
              list="attr-values"
              value={attrVal}
              onChange={(e) => setAttrVal(e.target.value)}
              placeholder="e.g. branch-ny"
            />
            <datalist id="attr-values">
              {(attributes.find((a) => a.key === attrKey)?.samples ?? []).map((s) => (
                <option key={s} value={s} />
              ))}
            </datalist>
          </div>
        )}
        <button className="btn" onClick={applyFilters}>
          Apply
        </button>
        <button className="btn secondary" onClick={clearFilters}>
          Clear
        </button>
        <span className="muted" style={{ fontSize: 11, alignSelf: "center" }}>
          date range = events in window · attribute slice keeps whole cases where any event matches
        </span>
      </div>

      <div className="stat-grid">
        <div className="stat-card">
          <div className="label">Cases</div>
          <div className="value">{fmtNumber(log.case_count)}</div>
          {filterActive && <div className="hint">full log; tabs show filtered</div>}
        </div>
        <div className="stat-card">
          <div className="label">Events</div>
          <div className="value">{fmtNumber(log.event_count)}</div>
        </div>
        <div className="stat-card">
          <div className="label">Activities</div>
          <div className="value">{fmtNumber(log.activity_count)}</div>
        </div>
        <div className="stat-card">
          <div className="label">Variants</div>
          <div className="value">{fmtNumber(mapData?.stats.variant_count ?? variants?.total_variants ?? 0)}</div>
        </div>
        <div className="stat-card">
          <div className="label">Median cycle time</div>
          <div className="value">{cd ? fmtDuration(cd.p50_s) : "—"}</div>
          <div className="hint">p90 {cd ? fmtDuration(cd.p90_s) : "—"}</div>
        </div>
      </div>

      <div className="tabs">
        {(
          [
            "overview",
            "map",
            "variants",
            "bottlenecks",
            "cases",
            "timeline",
            "handover",
            "conformance",
          ] as Tab[]
        ).map((t) => (
          <button key={t} className={tab === t ? "active" : ""} onClick={() => setTab(t)}>
            {t === "conformance"
              ? "Conformance"
              : t === "handover"
                ? "Handover"
                : t[0].toUpperCase() + t.slice(1)}
          </button>
        ))}
      </div>

      {log.status !== "ready" && (
        <div className="notice-banner">Log status: {log.status} — analytics become available once ready.</div>
      )}

      {/* ---------------- Overview ---------------- */}
      {tab === "overview" && (
        <div className="grid-2">
          <div className="panel">
            <h2>Log facts</h2>
            <table className="data">
              <tbody>
                <tr><td className="muted">Source</td><td><span className="badge info">{log.source_type}</span> {log.source_detail}</td></tr>
                <tr><td className="muted">First event</td><td>{log.start_time ? new Date(log.start_time).toLocaleString() : "—"}</td></tr>
                <tr><td className="muted">Last event</td><td>{log.end_time ? new Date(log.end_time).toLocaleString() : "—"}</td></tr>
                <tr><td className="muted">Ingested</td><td>{new Date(log.created_at).toLocaleString()}</td></tr>
                <tr><td className="muted">Avg events / case</td><td>{log.case_count ? (log.event_count / log.case_count).toFixed(1) : "—"}</td></tr>
              </tbody>
            </table>
          </div>
          <div className="panel">
            <h2>Attributes on this log</h2>
            <table className="data">
              <thead><tr><th>Key</th><th>Sample values</th></tr></thead>
              <tbody>
                {attributes.length === 0 && (
                  <tr><td colSpan={2} className="muted">No extra attributes found</td></tr>
                )}
                {attributes.map((a) => (
                  <tr key={a.key}>
                    <td><span className="badge info">{a.key}</span></td>
                    <td className="mono" style={{ fontSize: 11 }}>{a.samples.slice(0, 5).join(", ")}{a.samples.length > 5 ? "…" : ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="muted" style={{ fontSize: 11, marginTop: 8 }}>
              Use these in the filter bar above or in “Compare by” on the Bottlenecks tab.
            </p>
          </div>
        </div>
      )}

      {/* ---------------- Map ---------------- */}
      {tab === "map" && (
        <div className="panel">
          <div className="row" style={{ marginBottom: 12, justifyContent: "space-between" }}>
            <h2 style={{ margin: 0 }}>Process map (directly-follows)</h2>
            <div className="muted" style={{ fontSize: 12 }}>
              🟢 healthy · 🟡 queue building · 🔴 bottleneck — click a node for detail
            </div>
          </div>
          {loading.map && <div className="loading">Mining the graph…</div>}
          {mapData && !loading.map && <ProcessMap map={mapData} />}
        </div>
      )}

      {/* ---------------- Variants ---------------- */}
      {tab === "variants" && (
        <div className="panel">
          <h2>Trace variants</h2>
          {!variants && loading.variants && <div className="loading">Ranking variants…</div>}
          {variants && (
            <>
              <div className="stat-grid">
                <div className="stat-card"><div className="label">Distinct variants</div><div className="value">{fmtNumber(variants.total_variants)}</div></div>
                <div className="stat-card"><div className="label">Cases covered by top {variants.pareto_80_variant_count}</div><div className="value">80%</div><div className="hint">pareto: {variants.pareto_80_variant_count} variants cover 80% of cases</div></div>
              </div>
              <table className="data">
                <thead><tr><th>#</th><th>Sequence</th><th>Cases</th><th>Share</th><th>Cumulative</th><th></th></tr></thead>
                <tbody>
                  {variants.variants.map((v) => (
                    <tr key={v.rank}>
                      <td className="muted">{v.rank}</td>
                      <td>
                        <div className="variant-seq">
                          {v.activities.map((a, i) => (
                            <span key={i}>
                              {i > 0 && <span className="arrow"> → </span>}
                              <span className="step">{a}</span>
                            </span>
                          ))}
                        </div>
                      </td>
                      <td>{fmtNumber(v.cases)}</td>
                      <td>{(v.share * 100).toFixed(1)}%</td>
                      <td>{v.cumulative_share ? `${(v.cumulative_share * 100).toFixed(1)}%` : "—"}</td>
                      <td>
                        <button className="btn sm secondary" onClick={() => casesForVariant(v.activities)}>
                          cases →
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
        </div>
      )}

      {/* ---------------- Bottlenecks ---------------- */}
      {tab === "bottlenecks" && (
        <>
          <div className="panel">
            <div className="row" style={{ justifyContent: "space-between" }}>
              <h2 style={{ margin: 0 }}>Compare by attribute</h2>
              <div className="row">
                <select
                  value={compareAttr}
                  onChange={(e) => setCompareAttr(e.target.value)}
                  style={{ background: "var(--panel-2)", border: "1px solid var(--border)", color: "var(--text)", borderRadius: 8, padding: "8px 12px" }}
                >
                  <option value="">— choose attribute —</option>
                  {attributes.map((a) => (
                    <option key={a.key} value={a.key}>{a.key}</option>
                  ))}
                </select>
                <button className="btn secondary" onClick={runCompare} disabled={!compareAttr || loading.compare}>
                  {loading.compare ? "Comparing…" : "Compare"}
                </button>
              </div>
            </div>
            {breakdown && (
              <div style={{ marginTop: 12 }}>
                <table className="data">
                  <thead>
                    <tr>
                      <th>{breakdown.attribute}</th><th>Cases</th><th>Avg</th><th>p50</th><th>p90</th><th>Top waits</th>
                    </tr>
                  </thead>
                  <tbody>
                    {breakdown.values.map((r) => (
                      <tr key={r.value}>
                        <td><strong>{r.value}</strong></td>
                        <td>{fmtNumber(r.cases)}</td>
                        <td>{fmtDuration(r.avg_duration_s)}</td>
                        <td>{fmtDuration(r.p50_duration_s)}</td>
                        <td>{fmtDuration(r.p90_duration_s)}</td>
                        <td className="muted" style={{ fontSize: 11 }}>
                          {r.top_waits.slice(0, 3).map((w) => `${w.activity} (${fmtDuration(w.avg_wait_s)})`).join(" · ")}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {breakdown.truncated && (
                  <p className="muted" style={{ fontSize: 11 }}>
                    Showing top {breakdown.max_values} values (high-cardinality attribute).
                  </p>
                )}
              </div>
            )}
          </div>

          <div className="panel">
            <h2>Bottleneck analysis</h2>
            {!bottlenecks && loading.bottlenecks && <div className="loading">Scanning queues…</div>}
            {bottlenecks && (
              <>
                <div className="stat-grid">
                  <div className="stat-card"><div className="label">Median case duration</div><div className="value">{fmtDuration(bottlenecks.case_durations.p50_s)}</div></div>
                  <div className="stat-card"><div className="label">p90 case duration</div><div className="value">{fmtDuration(bottlenecks.case_durations.p90_s)}</div></div>
                  <div className="stat-card"><div className="label">p95</div><div className="value">{fmtDuration(bottlenecks.case_durations.p95_s)}</div></div>
                  <div className="stat-card"><div className="label">Avg</div><div className="value">{fmtDuration(bottlenecks.case_durations.avg_s)}</div></div>
                </div>
                <h3>Activities ranked by queueing score (0–100)</h3>
                {bottlenecks.bottlenecks.map((b) => (
                  <div className="bar-row" key={b.activity}>
                    <div className="name" title={b.activity}>{b.activity}</div>
                    <div className="bar-track">
                      <div
                        className={`bar-fill ${b.score >= 0.75 ? "hot" : b.score >= 0.5 ? "warm" : ""}`}
                        style={{ width: `${Math.max(3, b.score * 100)}%` }}
                      />
                    </div>
                    <div className="val">{(b.score * 100).toFixed(0)}</div>
                  </div>
                ))}
                <p className="muted" style={{ fontSize: 12, marginTop: 14 }}>
                  Score = 0.7 × (avg wait ÷ max avg wait) + 0.3 × (activity load ÷ max load).
                  High score ⇒ cases queue here; reducing its wait shrinks overall cycle time.
                </p>
              </>
            )}
          </div>
        </>
      )}

      {/* ---------------- Cases ---------------- */}
      {tab === "cases" && (
        <div className="panel">
          <h2>Case drill-down</h2>
          <div className="row" style={{ marginBottom: 14 }}>
            <input
              value={caseQuery}
              onChange={(e) => setCaseQuery(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && searchCases()}
              placeholder="Search case id, e.g. LN-0042…"
              style={{ background: "var(--panel-2)", border: "1px solid var(--border)", color: "var(--text)", borderRadius: 8, padding: "8px 12px", minWidth: 240 }}
            />
            <button className="btn" onClick={searchCases} disabled={loading.cases || !caseQuery.trim()}>
              {loading.cases ? "Searching…" : "Search"}
            </button>
            <span className="muted">or pick a variant:</span>
            <select
              value={casesVariant}
              onChange={(e) => {
                const v = e.target.value;
                setCasesVariant(v);
                if (!v) return;
                const found = variants?.variants.find((x) => JSON.stringify(x.activities) === v);
                if (found) casesForVariant(found.activities);
              }}
              style={{ background: "var(--panel-2)", border: "1px solid var(--border)", color: "var(--text)", borderRadius: 8, padding: "8px 12px", maxWidth: 380 }}
            >
              <option value="">— choose variant —</option>
              {variants?.variants.map((v) => (
                <option key={v.rank} value={JSON.stringify(v.activities)}>
                  #{v.rank}: {v.activities.join(" → ")}
                </option>
              ))}
            </select>
          </div>

          {drillCase && (
            <div style={{ marginBottom: 18 }}>
              <CaseDrilldown logId={Number(id)} caseId={drillCase} onClose={() => setDrillCase(null)} />
            </div>
          )}

          {!caseResults && !loading.cases && !drillCase && (
            <div className="empty">
              Search by case id, or pick a variant to list its cases — click any row to see the
              full event timeline with wait times.
            </div>
          )}
          {loading.cases && <div className="loading">Finding cases…</div>}
          {caseResults && !loading.cases && (
            <>
              <div className="muted" style={{ fontSize: 12, marginBottom: 8 }}>
                {caseResults.returned} of {fmtNumber(caseResults.total_matching)} matching cases
                {caseResults.variant ? ` · variant: ${caseResults.variant.join(" → ")}` : ""}
              </div>
              {caseResults.cases.length === 0 && <div className="empty">No cases matched.</div>}
              {caseResults.cases.length > 0 && (
                <table className="data">
                  <thead>
                    <tr><th>Case</th><th>Events</th><th>Start</th><th>End</th><th>Last activity</th></tr>
                  </thead>
                  <tbody>
                    {caseResults.cases.map((c) => (
                      <tr key={c.case_id} style={{ cursor: "pointer" }} onClick={() => setDrillCase(c.case_id)}>
                        <td><span className="mono"><strong>{c.case_id}</strong></span></td>
                        <td>{c.events}</td>
                        <td className="muted">{c.start ? new Date(c.start).toLocaleString() : c.first ? new Date(c.first).toLocaleString() : "—"}</td>
                        <td className="muted">{c.end ? new Date(c.end).toLocaleString() : "—"}</td>
                        <td>{c.last_activity ?? "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </>
          )}
        </div>
      )}

      {/* ---------------- Timeline ---------------- */}
      {tab === "timeline" && (
        <div className="panel">
          <h2>Case timeline (dotted chart)</h2>
          <TimelineChart logId={Number(id)} filters={filters} />
        </div>
      )}

      {/* ---------------- Handover ---------------- */}
      {tab === "handover" && (
        <div className="panel">
          <div className="row" style={{ justifyContent: "space-between", marginBottom: 12 }}>
            <h2 style={{ margin: 0 }}>Handover network</h2>
            <div className="row">
              <span className="muted" style={{ fontSize: 12 }}>actor attribute</span>
              <select
                value={actorAttr}
                onChange={(e) => setActorAttr(e.target.value)}
                style={{ background: "var(--panel-2)", border: "1px solid var(--border)", color: "var(--text)", borderRadius: 8, padding: "7px 10px" }}
              >
                {["user", ...attributes.map((a) => a.key).filter((k) => k !== "user")].map((k) => (
                  <option key={k} value={k}>{k}</option>
                ))}
              </select>
            </div>
          </div>
          <HandoverGraph logId={Number(id)} filters={filters} actorAttr={actorAttr} />
        </div>
      )}

      {/* ---------------- Conformance ---------------- */}
      {tab === "conformance" && (
        <div className="panel">
          <h2>Conformance checking (alignments)</h2>
          <p className="muted" style={{ fontSize: 12 }}>
            Models from <strong>any log</strong> can be used here — discover one from this data,
            or import a hand-built reference (regulatory) model and measure deviations against it.
          </p>
          <div className="row" style={{ marginBottom: 14 }}>
            <input
              value={minerName}
              onChange={(e) => setMinerName(e.target.value)}
              style={{ background: "var(--panel-2)", border: "1px solid var(--border)", color: "var(--text)", borderRadius: 8, padding: "8px 12px" }}
              placeholder="Model name"
            />
            <button className="btn" onClick={discover} disabled={loading.discover}>
              {loading.discover ? "Discovering…" : "① Discover from this log"}
            </button>
            <button className="btn secondary" onClick={() => setImportOpen((v) => !v)}>
              ⤓ Import reference model
            </button>
          </div>

          {importOpen && (
            <div className="panel" style={{ background: "var(--panel-2)" }}>
              <h3>Import model spec (JSON)</h3>
              <div className="form-row">
                <label>Name</label>
                <input value={importName} onChange={(e) => setImportName(e.target.value)} placeholder="Regulatory baseline" />
              </div>
              <div className="form-row">
                <label>Spec — must contain petri_net: {"{places, transitions, arcs, initial_marking, final_marking}"}</label>
                <textarea
                  rows={6}
                  className="mono"
                  value={importSpec}
                  onChange={(e) => setImportSpec(e.target.value)}
                  placeholder={'{"petri_net": {"places": [...], "transitions": [...], "arcs": [...], "initial_marking": {"source": 1}, "final_marking": {"sink": 1}}, "activities": [...], "start_activities": [...], "end_activities": [...]}'}
                />
              </div>
              <div className="row end">
                <button className="btn" onClick={importModel} disabled={loading.import || !importName.trim() || !importSpec.trim()}>
                  {loading.import ? "Importing…" : "Import"}
                </button>
              </div>
            </div>
          )}

          <div className="row" style={{ marginBottom: 14, marginTop: 6 }}>
            <select
              value={selectedModel ?? ""}
              onChange={(e) => {
                setSelectedModel(e.target.value ? Number(e.target.value) : null);
                setConformance(null);
              }}
              style={{ background: "var(--panel-2)", border: "1px solid var(--border)", color: "var(--text)", borderRadius: 8, padding: "8px 12px", maxWidth: 420 }}
            >
              <option value="">Select model…</option>
              {models.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.name} ({m.miner}) {m.log_id === Number(id) ? "" : `— from "${m.log_name}"`}
                </option>
              ))}
            </select>
            <button className="btn secondary" onClick={runConformance} disabled={!selectedModel || loading.conform}>
              {loading.conform ? "Checking…" : "② Run alignment vs this log"}
            </button>
          </div>

          {models.length === 0 && !loading.models && (
            <div className="empty">
              No models yet. Discover a model from this log, or import a reference model — then
              run alignments to measure how well cases conform.
            </div>
          )}

          {conformance && (
            <>
              <div className="stat-grid">
                <div className="stat-card"><div className="label">Conformance rate</div><div className="value" style={{ color: conformance.conformance_rate >= 0.9 ? "var(--ok)" : "var(--warn)" }}>{(conformance.conformance_rate * 100).toFixed(1)}%</div></div>
                <div className="stat-card"><div className="label">Avg fitness</div><div className="value">{conformance.avg_fitness.toFixed(3)}</div></div>
                <div className="stat-card"><div className="label">Cases checked</div><div className="value">{fmtNumber(conformance.cases_checked)}</div></div>
                <div className="stat-card"><div className="label">Non-conforming</div><div className="value" style={{ color: conformance.non_conforming ? "var(--danger)" : "var(--ok)" }}>{fmtNumber(conformance.non_conforming)}</div></div>
                <div className="stat-card"><div className="label">Off-model log moves</div><div className="value" style={{ color: conformance.total_log_moves ? "var(--warn)" : "var(--ok)" }}>{fmtNumber(conformance.total_log_moves)}</div></div>
              </div>
              <p className="muted" style={{ fontSize: 12 }}>
                Model <strong>{conformance.model_name}</strong> · against “{log.name}”
              </p>
              {conformance.worst_cases.length > 0 && (
                <>
                  <h3>Worst-fitting cases</h3>
                  <table className="data">
                    <thead><tr><th>Fitness</th><th>Conforming</th><th>Log moves</th><th>Visible model moves</th></tr></thead>
                    <tbody>
                      {conformance.worst_cases.map((w, i) => (
                        <tr key={i}>
                          <td style={{ color: w.fitness < 1 ? "var(--warn)" : "var(--ok)" }}>{w.fitness.toFixed(3)}</td>
                          <td>{w.conforming ? <span className="badge ok">yes</span> : <span className="badge danger">no</span>}</td>
                          <td>{w.log_moves}</td><td>{w.visible_model_moves}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </>
              )}
            </>
          )}
        </div>
      )}
    </Shell>
  );
}
