"use client";

/** Admin-only audit trail of who did what (compliance evidence). */

import { useEffect, useState } from "react";
import Shell from "@/components/Shell";
import { api, type AuditRow } from "@/lib/api";

export default function AuditPage() {
  const [rows, setRows] = useState<AuditRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .get<AuditRow[]>("/api/audit?limit=500")
      .then(setRows)
      .catch((e) => setError(e instanceof Error ? e.message : "Failed to load"));
  }, []);

  return (
    <Shell
      title="Audit Trail"
      subtitle="Immutable record of logins, ingests, discoveries, and conformance runs"
    >
      {error && <div className="error-banner">{error}</div>}
      {!rows && !error && <div className="loading">Loading…</div>}
      {rows && (
        <div className="panel">
          <table className="data">
            <thead>
              <tr>
                <th>Time</th>
                <th>User</th>
                <th>Action</th>
                <th>Resource</th>
                <th>Detail</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id}>
                  <td className="muted" style={{ whiteSpace: "nowrap" }}>
                    {r.created_at ? new Date(r.created_at).toLocaleString() : "—"}
                  </td>
                  <td>{r.user_email ?? "—"}</td>
                  <td>
                    <span
                      className={`badge ${
                        r.action.includes("fail") || r.action.includes("delete")
                          ? "danger"
                          : r.action === "login"
                            ? "muted"
                            : "info"
                      }`}
                    >
                      {r.action}
                    </span>
                  </td>
                  <td className="mono">{r.resource}</td>
                  <td className="mono" style={{ maxWidth: 380, overflow: "hidden", textOverflow: "ellipsis" }}>
                    {r.detail && Object.keys(r.detail).length ? JSON.stringify(r.detail) : "—"}
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
