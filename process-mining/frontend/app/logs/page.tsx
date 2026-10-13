"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import Shell from "@/components/Shell";
import { api, fmtDate, fmtNumber, type LogSummary } from "@/lib/api";

export default function LogsPage() {
  const [logs, setLogs] = useState<LogSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .get<LogSummary[]>("/api/logs")
      .then(setLogs)
      .catch((e) => setError(e instanceof Error ? e.message : "Failed to load"));
  }, []);

  return (
    <Shell
      title="Event Logs"
      subtitle="Normalized event logs ingested from files, databases, or streams"
      actions={
        <Link href="/ingest" className="btn">
          + Ingest log
        </Link>
      }
    >
      {error && <div className="error-banner">{error}</div>}
      {!logs && !error && <div className="loading">Loading…</div>}
      {logs && logs.length === 0 && (
        <div className="empty">
          No event logs yet. <Link href="/ingest">Ingest your first log</Link> — CSV, XES, or an SQL
          export.
        </div>
      )}
      {logs && logs.length > 0 && (
        <div className="panel">
          <table className="data">
            <thead>
              <tr>
                <th>Name</th>
                <th>Source</th>
                <th>Cases</th>
                <th>Events</th>
                <th>Activities</th>
                <th>Period</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {logs.map((l) => (
                <tr key={l.id}>
                  <td>
                    <Link href={`/logs/${l.id}`}>
                      <strong>{l.name}</strong>
                    </Link>
                    <div className="muted" style={{ fontSize: 11 }}>
                      {l.description || `#${l.id}`}
                    </div>
                  </td>
                  <td>
                    <span className="badge info">{l.source_type}</span>
                  </td>
                  <td>{fmtNumber(l.case_count)}</td>
                  <td>{fmtNumber(l.event_count)}</td>
                  <td>{fmtNumber(l.activity_count)}</td>
                  <td className="muted">
                    {fmtDate(l.start_time)} → {fmtDate(l.end_time)}
                  </td>
                  <td>
                    <span
                      className={`badge ${
                        l.status === "ready" ? "ok" : l.status === "failed" ? "danger" : "warn"
                      }`}
                    >
                      {l.status}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Shell>
  );
}
