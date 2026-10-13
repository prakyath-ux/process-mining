"use client";

/** Case drill-down: one case's full event trace as a vertical timeline,
 * with wait time between steps highlighted (queueing evidence per case). */

import { useEffect, useState } from "react";
import { api, fmtDuration, type CaseTrace } from "@/lib/api";

export default function CaseDrilldown({
  logId,
  caseId,
  onClose,
}: {
  logId: number;
  caseId: string;
  onClose: () => void;
}) {
  const [trace, setTrace] = useState<CaseTrace | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setTrace(null);
    api
      .get<CaseTrace>(`/api/logs/${logId}/cases/${encodeURIComponent(caseId)}`)
      .then(setTrace)
      .catch((e) => setError(e instanceof Error ? e.message : "Failed to load case"));
  }, [logId, caseId]);

  if (error) return <div className="error-banner">{error}</div>;
  if (!trace) return <div className="loading">Loading case trace…</div>;

  const waits: number[] = trace.events.map((e, i) => {
    if (i === 0) return 0;
    const prev = new Date(trace.events[i - 1].timestamp).getTime();
    const cur = new Date(e.timestamp).getTime();
    return Math.max(0, (cur - prev) / 1000);
  });
  const maxWait = Math.max(...waits, 1);
  const totalWait = waits.reduce((a, b) => a + b, 0);

  return (
    <div className="panel" style={{ marginBottom: 0 }}>
      <div className="row" style={{ justifyContent: "space-between", marginBottom: 12 }}>
        <h2 style={{ margin: 0 }}>
          Case <span className="mono">{trace.case_id}</span>
        </h2>
        <button className="btn sm secondary" onClick={onClose}>
          ✕ Close
        </button>
      </div>
      <div className="muted" style={{ fontSize: 12, marginBottom: 14 }}>
        {trace.events.length} events · total time in process:{" "}
        <strong style={{ color: "var(--text)" }}>{fmtDuration(totalWait)}</strong>
      </div>

      <div className="timeline">
        {trace.events.map((e, i) => {
          const wait = waits[i];
          const isBigWait = wait > maxWait * 0.4 && wait > 3600;
          return (
            <div className="timeline-row" key={i}>
              <div className="timeline-gutter">
                <span className="timeline-dot" />
                {i < trace.events.length - 1 && <span className="timeline-line" />}
              </div>
              <div className="timeline-body">
                <div className="row" style={{ justifyContent: "space-between" }}>
                  <strong>{e.activity}</strong>
                  <span className="muted mono" style={{ fontSize: 11 }}>
                    {new Date(e.timestamp).toLocaleString()}
                  </span>
                </div>
                {i > 0 && (
                  <div className={`timeline-wait${isBigWait ? " hot" : ""}`}>
                    ⏳ waited {fmtDuration(wait)}
                    <span className="timeline-bar">
                      <span
                        className={`timeline-bar-fill${isBigWait ? " hot" : ""}`}
                        style={{ width: `${Math.max(3, (wait / maxWait) * 100)}%` }}
                      />
                    </span>
                  </div>
                )}
                {e.attrs && Object.keys(e.attrs).length > 0 && (
                  <div className="row" style={{ marginTop: 4 }}>
                    {Object.entries(e.attrs).map(([k, v]) => (
                      <span key={k} className="badge muted">
                        {k}: {String(v)}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
