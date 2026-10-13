"use client";

/** Organizational mining: who hands work to whom (humans, agents, bots).
 * Nodes = actors from the configured attribute (default "user"), edges =
 * handovers with count + average wait until the next actor picked it up. */

import { useEffect, useMemo, useState } from "react";
import {
  Background,
  Controls,
  Handle,
  MarkerType,
  MiniMap,
  Position,
  ReactFlow,
  type Edge,
  type Node,
} from "@xyflow/react";
import dagre from "dagre";
import { api, fmtDuration, fmtNumber, type HandoverResponse, type LogFilters } from "@/lib/api";
import { qs } from "@/lib/api";

const NODE_W = 180;
const NODE_H = 70;

function ActorNode({ data }: { data: { actor: HandoverResponse["nodes"][number] } }) {
  const a = data.actor;
  return (
    <div
      style={{
        width: NODE_W,
        height: NODE_H,
        border: "1.5px solid #7c5cff",
        background: "rgba(38,26,64,0.95)",
        borderRadius: 10,
        padding: "9px 12px",
        color: "#e6eaf2",
        fontFamily: "inherit",
        boxShadow: "0 4px 14px rgba(0,0,0,0.35)",
      }}
    >
      <Handle type="target" position={Position.Left} style={{ opacity: 0 }} />
      <div style={{ fontWeight: 700, fontSize: 13, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={a.id}>
        {a.id}
      </div>
      <div style={{ fontSize: 11, color: "#8b95ab", marginTop: 6 }}>
        {fmtNumber(a.events)} events
      </div>
      <div style={{ fontSize: 10, color: "#8b95ab", marginTop: 3, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
        {a.top_activities.slice(0, 2).map((t) => t.activity).join(", ")}
      </div>
      <Handle type="source" position={Position.Right} style={{ opacity: 0 }} />
    </div>
  );
}

const nodeTypes = { actor: ActorNode };

export default function HandoverGraph({
  logId,
  filters,
  actorAttr = "user",
}: {
  logId: number;
  filters?: LogFilters;
  actorAttr?: string;
}) {
  const [data, setData] = useState<HandoverResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    setError(null);
    api
      .get<HandoverResponse>(`/api/logs/${logId}/handover${qs(filters, { actor_attr: actorAttr })}`)
      .then(setData)
      .catch((e) => setError(e instanceof Error ? e.message : "Failed to load handover"))
      .finally(() => setLoading(false));
  }, [logId, filters, actorAttr]);

  const { nodes, edges } = useMemo(() => {
    if (!data) return { nodes: [] as Node[], edges: [] as Edge[] };
    const g = new dagre.graphlib.Graph();
    g.setDefaultEdgeLabel(() => ({}));
    g.setGraph({ rankdir: "LR", nodesep: 55, ranksep: 120, marginx: 24, marginy: 24 });
    for (const n of data.nodes) g.setNode(n.id, { width: NODE_W, height: NODE_H });
    for (const e of data.edges) g.setEdge(e.source, e.target);
    dagre.layout(g);

    const maxCount = Math.max(...data.edges.map((e) => e.count), 1);
    const nodes: Node[] = data.nodes.map((n) => {
      const pos = g.node(n.id);
      return {
        id: n.id,
        type: "actor",
        position: { x: pos.x - NODE_W / 2, y: pos.y - NODE_H / 2 },
        data: { actor: n },
      };
    });
    const edges: Edge[] = data.edges.map((e, i) => ({
      id: `h${i}`,
      source: e.source,
      target: e.target,
      style: { stroke: "#7c5cff", strokeWidth: 1 + 6 * (e.count / maxCount), opacity: 0.8 },
      label: `${fmtNumber(e.count)}× · avg ${fmtDuration(e.avg_wait_s)}`,
      labelStyle: { fill: "#8b95ab", fontSize: 10, fontWeight: 600 },
      labelBgStyle: { fill: "#0b0e14", fillOpacity: 0.85 },
      markerEnd: { type: MarkerType.ArrowClosed, width: 14, height: 14, color: "#7c5cff" },
      curvature: 0.3,
    }));
    return { nodes, edges };
  }, [data]);

  if (error) return <div className="error-banner">{error}</div>;
  if (loading) return <div className="loading">Building handover network…</div>;
  if (!data || data.actors === 0)
    return (
      <div className="empty">
        No "{actorAttr}" attribute found on this log. Handover mining needs an actor column
        (user, agent, bot) — check the Attributes list to see which keys exist.
      </div>
    );

  return (
    <div>
      <div className="graph-wrap">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          fitView
          minZoom={0.15}
          maxZoom={2}
          proOptions={{ hideAttribution: true }}
        >
          <Background color="#2a3347" gap={18} />
          <Controls />
          <MiniMap pannable zoomable nodeColor="#7c5cff" />
        </ReactFlow>
      </div>
      <div className="muted" style={{ fontSize: 12, marginTop: 8 }}>
        {data.actors} actors · {data.handovers} handover types · edge label = handover count and
        average wait until the next actor picked the work up (reading the{" "}
        <span className="mono">{data.actor_attr}</span> attribute)
      </div>
    </div>
  );
}
