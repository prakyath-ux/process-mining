"use client";

/** Interactive process map: dagre auto-layout + React Flow pan/zoom.
 * Node border/heat encodes the bottleneck score; edge width encodes frequency. */

import { useCallback, useMemo } from "react";
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
  type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import dagre from "dagre";
import type { MapNode, ProcessMap } from "@/lib/api";
import { fmtDuration, fmtNumber } from "@/lib/api";

const NODE_W = 210;
const NODE_H = 76;

type HeatFn = (n: MapNode) => { border: string; bg: string; badge?: string };

function heat(n: MapNode, score: number): { border: string; bg: string } {
  if (n.kind !== "activity") {
    const c = n.kind === "start" ? "#37c98b" : "#4f8cff";
    return { border: c, bg: "rgba(23,28,40,0.98)" };
  }
  // score 0..1 → blue (healthy) to red (bottleneck)
  if (score >= 0.75) return { border: "#f2555a", bg: "rgba(60,22,26,0.95)" };
  if (score >= 0.5) return { border: "#f2b13c", bg: "rgba(52,42,20,0.95)" };
  if (score >= 0.25) return { border: "#4f8cff", bg: "rgba(22,30,48,0.95)" };
  return { border: "#2a3347", bg: "rgba(20,25,36,0.95)" };
}

function ActivityNode({ data }: NodeProps) {
  const d = data as unknown as { map: MapNode; score: number };
  const n = d.map;
  const h = heat(n, d.score);
  return (
    <div
      style={{
        width: NODE_W,
        height: NODE_H,
        border: `1.5px solid ${h.border}`,
        background: h.bg,
        borderRadius: 10,
        padding: "9px 12px",
        fontFamily: "inherit",
        color: "#e6eaf2",
        boxShadow: "0 4px 14px rgba(0,0,0,0.35)",
      }}
    >
      <Handle type="target" position={Position.Left} style={{ opacity: 0 }} />
      <div style={{ fontWeight: 700, fontSize: 13, lineHeight: 1.25, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={n.label}>
        {n.label}
      </div>
      <div style={{ display: "flex", justifyContent: "space-between", marginTop: 7, fontSize: 11, color: "#8b95ab" }}>
        <span>{fmtNumber(n.count)} ev</span>
        <span>
          wait p50 {fmtDuration(n.wait ? n.wait.p50_s : null)}
        </span>
      </div>
      <div style={{ display: "flex", justifyContent: "space-between", marginTop: 4, fontSize: 11, color: "#8b95ab" }}>
        <span title="bottleneck score">{d.score >= 0.75 ? "🔴" : d.score >= 0.5 ? "🟡" : "🟢"} {Math.round(d.score * 100)}</span>
        <span>active {fmtDuration(n.active ? n.active.avg_s : null)}</span>
      </div>
      <Handle type="source" position={Position.Right} style={{ opacity: 0 }} />
    </div>
  );
}

const nodeTypes = { pm: ActivityNode };

function layout(map: ProcessMap): { nodes: Node[]; edges: Edge[] } {
  const g = new dagre.graphlib.Graph();
  g.setDefaultEdgeLabel(() => ({}));
  g.setGraph({ rankdir: "LR", nodesep: 34, ranksep: 105, marginx: 24, marginy: 24 });

  for (const n of map.nodes) {
    g.setNode(n.id, { width: NODE_W, height: NODE_H });
  }
  for (const e of map.edges) {
    g.setEdge(e.source, e.target);
  }
  dagre.layout(g);

  const maxCount = Math.max(...map.edges.map((e) => e.count), 1);
  const kindById = new Map(map.nodes.map((n) => [n.id, n.kind]));

  const nodes: Node[] = map.nodes.map((n) => {
    const pos = g.node(n.id);
    return {
      id: n.id,
      type: "pm",
      position: { x: pos.x - NODE_W / 2, y: pos.y - NODE_H / 2 },
      data: { map: n, score: map.bottleneck_scores[n.id] ?? 0 },
      draggable: true,
    };
  });

  const edges: Edge[] = map.edges.map((e, i) => {
    const width = 1 + 5 * (e.count / maxCount);
    const startNode = kindById.get(e.source);
    const endNode = kindById.get(e.target);
    const color = startNode === "start" || endNode === "end" ? "#37c98b" : "#4f8cff";
    return {
      id: `e${i}-${e.source}-${e.target}`,
      source: e.source,
      target: e.target,
      animated: false,
      style: { stroke: color, strokeWidth: width, opacity: 0.75 },
      label: `${fmtNumber(e.count)}${e.duration ? ` · ${fmtDuration(e.duration.avg_s)}` : ""}`,
      labelStyle: { fill: "#8b95ab", fontSize: 10, fontWeight: 600 },
      labelBgStyle: { fill: "#0b0e14", fillOpacity: 0.85 },
      markerEnd: { type: MarkerType.ArrowClosed, width: 14, height: 14, color },
      curvature: 0.28,
    };
  });

  return { nodes, edges };
}

export default function ProcessMap({ map }: { map: ProcessMap }) {
  const { nodes, edges } = useMemo(() => layout(map), [map]);
  const onNodeClick = useCallback((_evt: unknown, node: Node) => {
    const n = (node.data as unknown as { map: MapNode }).map;
    const score = (node.data as unknown as { score: number }).score;
    window.alert(
      `${n.label}\n\ncases via activity: ${fmtNumber(n.count)}\n` +
        `starts: ${fmtNumber(n.starts ?? 0)}  ends: ${fmtNumber(n.ends ?? 0)}\n` +
        `wait p50: ${fmtDuration(n.wait?.p50_s)}  p90: ${fmtDuration(n.wait?.p90_s)}\n` +
        `active p50: ${fmtDuration(n.active?.p50_s)}\n` +
        `bottleneck score: ${(score * 100).toFixed(0)}/100`
    );
  }, []);

  return (
    <div className="graph-wrap">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        onNodeClick={onNodeClick}
        fitView
        minZoom={0.15}
        maxZoom={2}
        proOptions={{ hideAttribution: true }}
        nodesDraggable
      >
        <Background color="#2a3347" gap={18} />
        <Controls />
        <MiniMap pannable zoomable nodeColor={(n) => {
          const d = (n.data as unknown as { map: MapNode; score: number });
          return heat(d.map, d.score).border;
        }} />
      </ReactFlow>
    </div>
  );
}
