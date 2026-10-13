"use client";

/** Dotted timeline: x = event time, one row per case, dot per event colored
 * by activity. Cases are stride-sampled so huge logs stay responsive.
 *
 * Rows get a minimum height (chart scrolls inside its container) and hovering
 * uses a nearest-dot search with an 8px hit radius + custom tooltip, so the
 * dots are actually hittable regardless of sample size. */

import { useEffect, useMemo, useRef, useState } from "react";
import { api, qs, type LogFilters, type TimelineResponse } from "@/lib/api";

const W = 1400;
const PAD_L = 8;
const PAD_R = 8;
const PAD_T = 18;
const PAD_B = 26;
const ROW_H_MIN = 5; // px per case row — keeps dots hittable
const ROW_H_MAX = 14;
const CHART_H_TARGET = 640; // grow beyond this only if rows demand it
const HIT_RADIUS = 8; // px around a dot that still triggers the tooltip

type Dot = { x: number; y: number; color: string; caseId: string; activity: string; when: string };

function palette(activity: string, activities: string[]): string {
  const hue = (activities.indexOf(activity) * 47) % 360;
  return `hsl(${hue} 70% 60%)`;
}

export default function TimelineChart({
  logId,
  filters,
}: {
  logId: number;
  filters?: LogFilters;
}) {
  const [data, setData] = useState<TimelineResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [hover, setHover] = useState<{ dot: Dot; x: number; y: number } | null>(null);
  const svgRef = useRef<SVGSVGElement | null>(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    setHover(null);
    api
      .get<TimelineResponse>(`/api/logs/${logId}/timeline${qs(filters, { limit: 400 })}`)
      .then(setData)
      .catch((e) => setError(e instanceof Error ? e.message : "Failed to load timeline"))
      .finally(() => setLoading(false));
  }, [logId, filters]);

  const geom = useMemo(() => {
    if (!data || data.cases.length === 0) return null;
    const times: number[] = [];
    for (const c of data.cases)
      for (const e of c.events) times.push(new Date(e.ts).getTime());
    const minT = Math.min(...times);
    const maxT = Math.max(...times);
    const span = Math.max(1, maxT - minT);

    const rowH = Math.max(
      ROW_H_MIN,
      Math.min(ROW_H_MAX, CHART_H_TARGET / Math.max(1, data.cases.length))
    );
    const H = PAD_T + PAD_B + rowH * data.cases.length;
    const innerW = W - PAD_L - PAD_R;

    const dots: Dot[] = [];
    data.cases.forEach((c, i) => {
      const y = PAD_T + rowH * i + rowH / 2;
      for (const e of c.events) {
        const t = new Date(e.ts).getTime();
        dots.push({
          x: PAD_L + ((t - minT) / span) * innerW,
          y,
          color: palette(e.activity, data.activities),
          caseId: c.case_id,
          activity: e.activity,
          when: new Date(e.ts).toLocaleString(),
        });
      }
    });
    return { minT, maxT, H, rowH, dots };
  }, [data]);

  function onMouseMove(e: React.MouseEvent<SVGSVGElement>) {
    const svg = svgRef.current;
    if (!svg || !geom) return;
    const rect = svg.getBoundingClientRect();
    // svg has explicit width/height equal to its viewBox → 1:1 mapping
    const mx = ((e.clientX - rect.left) * W) / rect.width;
    const my = ((e.clientY - rect.top) * geom.H) / rect.height;

    let best: Dot | null = null;
    let bestD2 = HIT_RADIUS * HIT_RADIUS * 4; // allow a generous radius (scaled)
    for (const d of geom.dots) {
      const dx = d.x - mx;
      const dy = d.y - my;
      const d2 = dx * dx + dy * dy;
      if (d2 < bestD2) {
        bestD2 = d2;
        best = d;
      }
    }
    if (best) {
      setHover({ dot: best, x: e.clientX, y: e.clientY });
    } else if (hover) {
      setHover(null);
    }
  }

  if (error) return <div className="error-banner">{error}</div>;
  if (loading) return <div className="loading">Sampling cases…</div>;
  if (!data || !geom) return <div className="empty">No cases in the selected range.</div>;

  const fmtDate = (t: number) =>
    new Date(t).toLocaleDateString("en-US", { month: "short", day: "numeric" });
  const dotR = Math.max(2, Math.min(4.5, geom.rowH * 0.45));
  const anyGap = geom.maxT - geom.minT;

  return (
    <div>
      <p className="muted" style={{ fontSize: 12, marginTop: 0 }}>
        One row per case (sorted by start time) · x = calendar time · dot color = activity.
        Vertical stripes of one color = batch/nightly runs · long sparse rows = stuck cases ·
        density gaps = quiet periods. Hover any dot for case/step detail.
      </p>
      <div className="chart-wrap" style={{ maxHeight: 660 }}>
        <svg
          ref={svgRef}
          viewBox={`0 0 ${W} ${geom.H}`}
          width={W}
          height={geom.H}
          onMouseMove={onMouseMove}
          onMouseLeave={() => setHover(null)}
          role="img"
          aria-label="Case timeline"
          style={{ display: "block" }}
        >
          {/* x axis */}
          {[0, 0.25, 0.5, 0.75, 1].map((f) => {
            const t = geom.minT + f * anyGap;
            const x = PAD_L + f * (W - PAD_L - PAD_R);
            return (
              <g key={f}>
                <line
                  x1={x}
                  y1={PAD_T}
                  x2={x}
                  y2={geom.H - PAD_B}
                  stroke="#2a3347"
                  strokeDasharray="3 5"
                />
                <text
                  x={x}
                  y={geom.H - 8}
                  fill="#8b95ab"
                  fontSize="11"
                  textAnchor={f === 0 ? "start" : f === 1 ? "end" : "middle"}
                >
                  {fmtDate(t)}
                </text>
              </g>
            );
          })}
          {/* guide line on hovered row */}
          {hover && (
            <line
              x1={PAD_L}
              y1={hover.dot.y}
              x2={W - PAD_R}
              y2={hover.dot.y}
              stroke="#4f8cff"
              strokeOpacity={0.35}
              strokeDasharray="2 4"
            />
          )}
          {geom.dots.map((d, i) => (
            <circle
              key={i}
              cx={d.x}
              cy={d.y}
              r={hover && hover.dot === d ? dotR + 1.5 : dotR}
              fill={d.color}
              opacity={hover && hover.dot !== d ? 0.55 : 0.95}
              stroke={hover && hover.dot === d ? "#fff" : "none"}
              strokeWidth={hover && hover.dot === d ? 1.5 : 0}
            />
          ))}
        </svg>
      </div>

      {hover && (
        <div className="tt-tooltip" style={{ left: hover.x + 14, top: hover.y + 14 }}>
          <strong>{hover.dot.caseId}</strong>
          <div>{hover.dot.activity}</div>
          <div className="muted">{hover.dot.when}</div>
        </div>
      )}

      <div className="row" style={{ justifyContent: "space-between", marginTop: 8 }}>
        <span className="muted" style={{ fontSize: 12 }}>
          {data.sampled_cases.toLocaleString()} of {data.total_cases.toLocaleString()} cases
          sampled · {geom.dots.length.toLocaleString()} dots · chart scrolls vertically
        </span>
      </div>
      <div className="legend">
        {data.activities.map((a) => (
          <span className="item" key={a}>
            <span className="swatch" style={{ background: palette(a, data.activities) }} />
            {a}
          </span>
        ))}
      </div>
    </div>
  );
}
