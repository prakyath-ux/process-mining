"use client";

/** CSV/XES upload with column-mapping preview, plus SQL pull (admin). */

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState, type FormEvent } from "react";
import Shell from "@/components/Shell";
import { API_URL, api, getUser, type Role } from "@/lib/api";

interface Preview {
  columns: string[];
  rows: Record<string, string>[];
}

export default function IngestPage() {
  const router = useRouter();
  const [role, setRole] = useState<Role | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [caseCol, setCaseCol] = useState("");
  const [activityCol, setActivityCol] = useState("");
  const [tsCol, setTsCol] = useState("");
  const [lifecycleCol, setLifecycleCol] = useState("");
  const [attrCols, setAttrCols] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [success, setSuccess] = useState<string | null>(null);

  // SQL form
  const [sqlUrl, setSqlUrl] = useState("");
  const [sqlQuery, setSqlQuery] = useState("");
  const [sqlName, setSqlName] = useState("");
  const [sqlCase, setSqlCase] = useState("");
  const [sqlActivity, setSqlActivity] = useState("");
  const [sqlTs, setSqlTs] = useState("");
  const [sqlBusy, setSqlBusy] = useState(false);

  useEffect(() => {
    const u = getUser();
    setRole(u?.role ?? null);
  }, []);

  function guess(cols: string[], patterns: string[]): string {
    const lower = cols.map((c) => c.toLowerCase());
    for (const p of patterns) {
      const idx = lower.findIndex((c) => c.includes(p));
      if (idx >= 0) return cols[idx];
    }
    return "";
  }

  async function onFilePicked(f: File | undefined) {
    if (!f) return;
    setFile(f);
    setPreview(null);
    setError(null);
    setSuccess(null);
    if (f.name.toLowerCase().endsWith(".xes")) {
      setCaseCol("case:concept:name");
      setActivityCol("concept:name");
      setTsCol("time:timestamp");
      setName(f.name.replace(/\.xes$/i, ""));
      return;
    }
    try {
      const buf = await f.arrayBuffer();
      const b64 = btoa(
        new Uint8Array(buf).reduce((acc, b) => acc + String.fromCharCode(b), "")
      );
      const p = await api.post<Preview>("/api/ingest/preview-csv", { data_base64: b64 });
      setPreview(p);
      setCaseCol(guess(p.columns, ["case", "loan", "application", "customer"]));
      setActivityCol(guess(p.columns, ["activity", "event", "task", "step", "status"]));
      setTsCol(guess(p.columns, ["timestamp", "time", "date", "created"]));
      setLifecycleCol("");
      setAttrCols(
        p.columns
          .filter((c) => ![caseCol, activityCol, tsCol].includes(c))
          .slice(0, 6)
          .join(", ")
      );
      if (!name) setName(f.name.replace(/\.[^.]+$/, ""));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not preview file");
    }
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (!file) return;
    setBusy(true);
    setError(null);
    setSuccess(null);
    try {
      const form = new FormData();
      form.append("file", file);
      form.append("name", name || file.name);
      form.append("description", description);
      form.append("case_col", caseCol);
      form.append("activity_col", activityCol);
      form.append("timestamp_col", tsCol);
      form.append("lifecycle_col", lifecycleCol);
      form.append("attr_columns", attrCols);
      const res = await api.postForm<{ log_id: number; inserted: number; skipped: number }>(
        "/api/ingest/file",
        form
      );
      setSuccess(
        `Ingested ${res.inserted.toLocaleString()} events (${res.skipped.toLocaleString()} rows skipped). Opening log…`
      );
      setTimeout(() => router.push(`/logs/${res.log_id}`), 900);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Ingestion failed");
    } finally {
      setBusy(false);
    }
  }

  async function onSqlSubmit(e: FormEvent) {
    e.preventDefault();
    setSqlBusy(true);
    setError(null);
    try {
      const res = await api.post<{ log_id: number; inserted: number }>("/api/ingest/sql", {
        name: sqlName,
        source_url: sqlUrl,
        query: sqlQuery,
        mapping: { case_id: sqlCase, activity: sqlActivity, timestamp: sqlTs, attr_columns: [] },
      });
      setSuccess(`Pulled ${res.inserted.toLocaleString()} events from SQL. Opening log…`);
      setTimeout(() => router.push(`/logs/${res.log_id}`), 900);
    } catch (err) {
      setError(err instanceof Error ? err.message : "SQL ingestion failed");
    } finally {
      setSqlBusy(false);
    }
  }

  const cols = preview?.columns ?? [];
  const isXes = file?.name.toLowerCase().endsWith(".xes") ?? false;

  return (
    <Shell title="Ingest Data" subtitle="CSV / XES files, or a direct SQL pull from source systems">
      {error && <div className="error-banner">{error}</div>}
      {success && <div className="notice-banner">{success}</div>}

      <form className="panel" onSubmit={onSubmit}>
        <h2>① Upload an event file</h2>
        <div className="form-grid">
          <div className="form-row full">
            <label>File (CSV with header row, or XES)</label>
            <input
              ref={fileRef}
              type="file"
              accept=".csv,.xes,.txt"
              onChange={(e) => onFilePicked(e.target.files?.[0])}
            />
          </div>
          <div className="form-row">
            <label>Log name</label>
            <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Loan origination 2025" required />
          </div>
          <div className="form-row">
            <label>Description (optional)</label>
            <input value={description} onChange={(e) => setDescription(e.target.value)} placeholder="Core banking export, Q1" />
          </div>
        </div>

        {cols.length > 0 && (
          <>
            <h3 style={{ marginTop: 8 }}>② Map columns</h3>
            <div className="form-grid">
              <div className="form-row">
                <label>Case ID column</label>
                <select value={caseCol} onChange={(e) => setCaseCol(e.target.value)} required>
                  <option value="">— choose —</option>
                  {cols.map((c) => <option key={c} value={c}>{c}</option>)}
                </select>
              </div>
              <div className="form-row">
                <label>Activity column</label>
                <select value={activityCol} onChange={(e) => setActivityCol(e.target.value)} required>
                  <option value="">— choose —</option>
                  {cols.map((c) => <option key={c} value={c}>{c}</option>)}
                </select>
              </div>
              <div className="form-row">
                <label>Timestamp column</label>
                <select value={tsCol} onChange={(e) => setTsCol(e.target.value)} required>
                  <option value="">— choose —</option>
                  {cols.map((c) => <option key={c} value={c}>{c}</option>)}
                </select>
              </div>
              <div className="form-row">
                <label>Lifecycle column (optional)</label>
                <select value={lifecycleCol} onChange={(e) => setLifecycleCol(e.target.value)}>
                  <option value="">— none —</option>
                  {cols.map((c) => <option key={c} value={c}>{c}</option>)}
                </select>
              </div>
              <div className="form-row full">
                <label>Extra attribute columns (comma-separated)</label>
                <input value={attrCols} onChange={(e) => setAttrCols(e.target.value)} placeholder="amount, user, branch" />
              </div>
            </div>
            <h3>Preview</h3>
            <div style={{ overflowX: "auto" }}>
              <table className="data">
                <thead><tr>{cols.map((c) => <th key={c}>{c}</th>)}</tr></thead>
                <tbody>
                  {preview?.rows.slice(0, 5).map((r, i) => (
                    <tr key={i}>{cols.map((c) => <td key={c} className="mono">{String(r[c] ?? "")}</td>)}</tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}

        {isXes && (
          <div className="notice-banner" style={{ marginTop: 12 }}>
            XES: standard keys will be used (case:concept:name / concept:name / time:timestamp).
          </div>
        )}

        <div className="row end" style={{ marginTop: 16 }}>
          <button className="btn" disabled={!file || busy}>
            {busy ? "Ingesting…" : "Ingest events →"}
          </button>
        </div>
      </form>

      {role === "admin" && (
        <form className="panel" onSubmit={onSqlSubmit}>
          <h2>Pull from SQL (admin)</h2>
          <p className="muted" style={{ fontSize: 12 }}>
            Runs a read-only SELECT against an external database (e.g.{" "}
            <span className="mono">postgresql://user:pass@host/db</span>). Credentials are used for
            the query and never stored.
          </p>
          <div className="form-grid">
            <div className="form-row">
              <label>Log name</label>
              <input value={sqlName} onChange={(e) => setSqlName(e.target.value)} required />
            </div>
            <div className="form-row">
              <label>Source URL</label>
              <input value={sqlUrl} onChange={(e) => setSqlUrl(e.target.value)} placeholder="postgresql://…" required />
            </div>
            <div className="form-row full">
              <label>SELECT query</label>
              <textarea
                rows={4}
                className="mono"
                value={sqlQuery}
                onChange={(e) => setSqlQuery(e.target.value)}
                placeholder="SELECT application_id AS case_id, stage AS activity, created_at AS ts FROM loan_events ORDER BY 1, 3"
                required
              />
            </div>
            <div className="form-row">
              <label>Case column (from SELECT)</label>
              <input value={sqlCase} onChange={(e) => setSqlCase(e.target.value)} required />
            </div>
            <div className="form-row">
              <label>Activity column</label>
              <input value={sqlActivity} onChange={(e) => setSqlActivity(e.target.value)} required />
            </div>
            <div className="form-row">
              <label>Timestamp column</label>
              <input value={sqlTs} onChange={(e) => setSqlTs(e.target.value)} required />
            </div>
          </div>
          <div className="row end">
            <button className="btn secondary" disabled={sqlBusy}>
              {sqlBusy ? "Pulling…" : "Pull events →"}
            </button>
          </div>
        </form>
      )}

      <div className="muted" style={{ fontSize: 12 }}>
        API: <span className="mono">{API_URL}</span> — phase 2 adds a live stream source here
        without changing the schema.
      </div>
    </Shell>
  );
}
