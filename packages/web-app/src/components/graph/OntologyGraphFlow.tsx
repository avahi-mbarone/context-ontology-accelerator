// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * OntologyGraphFlow — React Flow-based ontology graph visualization.
 *
 * Replaces the cytoscape-based OntologyGraph with @xyflow/react for
 * richer node UX (HTML inside nodes, badges, click-to-inspect).
 * Uses dagre for automatic hierarchical layout.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ReactFlow,
  Background,
  BackgroundVariant,
  Controls,
  MiniMap,
  Panel,
  type Node,
  type Edge,
  type NodeTypes,
  type NodeChange,
  Handle,
  Position,
  ReactFlowProvider,
  applyNodeChanges,
  useStore,
  useReactFlow,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import Dagre from "@dagrejs/dagre";

// ─── Types ──────────────────────────────────────────────────────────

export interface GraphNodeData {
  id: string;
  label: string;
  kind:
    | "class"
    | "object-property"
    | "datatype-property"
    | "grounded"
    | "unknown";
  uri?: string;
  /** True when the node has sub-classes that can be revealed by expanding. */
  hasChildren?: boolean;
  /** True when the node's sub-classes are currently all visible. */
  expanded?: boolean;
  [key: string]: unknown;
}

export interface GraphEdgeData {
  id: string;
  source: string;
  target: string;
  label?: string;
}

interface Props {
  nodes: GraphNodeData[];
  edges: GraphEdgeData[];
  onNodeSelect?: (node: GraphNodeData | null) => void;
  /**
   * Called when a node is double-clicked. Used to lazily expand a class's
   * sub-classes (or collapse them again when already expanded).
   */
  onNodeExpand?: (node: GraphNodeData) => void;
}

/** React Flow node carrying our typed ontology payload. */
type OntologyFlowNode = Node<GraphNodeData>;

// ─── Layout ─────────────────────────────────────────────────────────

/**
 * Evenly spaced points around a circle, starting at the top (12 o'clock)
 * and going clockwise. Radius grows with the node count so neighbours stay
 * ~110px apart along the circumference.
 */
export function radialPositions(count: number): { x: number; y: number }[] {
  if (count <= 0) return [];
  if (count === 1) return [{ x: 0, y: 0 }];
  const radius = Math.max(160, (count * 110) / (2 * Math.PI));
  return Array.from({ length: count }, (_, i) => {
    const angle = (2 * Math.PI * i) / count - Math.PI / 2;
    return { x: radius * Math.cos(angle), y: radius * Math.sin(angle) };
  });
}

/**
 * Arrange edge-less nodes evenly around a circle.
 *
 * Dagre stacks disconnected nodes into a single horizontal row, which is
 * what the initial "root classes" view is (no edges until a class is
 * expanded). A circular arrangement reads as a graph cluster instead of a
 * line and scales gracefully as the count grows.
 */
function circularLayout<T extends Node>(
  nodes: T[],
  edges: Edge[],
): {
  nodes: T[];
  edges: Edge[];
} {
  const positions = radialPositions(nodes.length);
  return {
    nodes: nodes.map((node, i) => ({ ...node, position: positions[i] })),
    edges,
  };
}

function layoutGraph<T extends Node>(
  nodes: T[],
  edges: Edge[],
): { nodes: T[]; edges: Edge[] } {
  // No edges → circular cluster (initial root view). Dagre would otherwise
  // lay these out as one flat row.
  if (edges.length === 0) {
    return circularLayout(nodes, edges);
  }

  const g = new Dagre.graphlib.Graph().setDefaultEdgeLabel(() => ({}));
  g.setGraph({ rankdir: "TB", ranksep: 100, nodesep: 80 });

  for (const node of nodes) {
    g.setNode(node.id, { width: 80, height: 80 });
  }
  for (const edge of edges) {
    g.setEdge(edge.source, edge.target);
  }

  Dagre.layout(g);

  return {
    nodes: nodes.map((node) => {
      const pos = g.node(node.id);
      // Defensive: dagre returns undefined for a node it never positioned
      // (shouldn't happen since every node is added above, but guard anyway).
      if (!pos) return { ...node, position: { x: 0, y: 0 } };
      return { ...node, position: { x: pos.x - 40, y: pos.y - 40 } };
    }),
    edges,
  };
}

// ─── Custom Node ────────────────────────────────────────────────────

const KIND_COLORS: Record<string, { bg: string; border: string }> = {
  class: { bg: "#dbeafe", border: "#3b82f6" }, // blue — novel induced class
  grounded: { bg: "#ccfbf1", border: "#0d9488" }, // teal — grounded to reference ontology
  "object-property": { bg: "#fef3c7", border: "#f59e0b" }, // amber — relationship
  "datatype-property": { bg: "#d1fae5", border: "#10b981" }, // green — attribute
  unknown: { bg: "#f3f4f6", border: "#9ca3af" },
};

const LEGEND_ITEMS = [
  { kind: "class", label: "Novel class" },
  { kind: "grounded", label: "Grounded class" },
  { kind: "object-property", label: "Relationship" },
  { kind: "datatype-property", label: "Attribute" },
];

function OntologyNode({ data }: { data: GraphNodeData }) {
  const colors = KIND_COLORS[data.kind] ?? KIND_COLORS.unknown;
  const size = 72;
  return (
    <div
      title={
        data.hasChildren ? "Double-click to expand sub-classes" : undefined
      }
      style={{
        position: "relative",
        width: size,
        height: size,
        borderRadius: "50%",
        border: `3px solid ${colors.border}`,
        background: colors.bg,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        fontSize: 10,
        fontFamily: "system-ui, sans-serif",
        textAlign: "center",
        cursor: "grab",
        overflow: "hidden",
        padding: 4,
      }}
    >
      <Handle type="target" position={Position.Top} style={{ opacity: 0 }} />
      <div
        style={{
          fontWeight: 600,
          lineHeight: 1.2,
          wordBreak: "break-word",
          color: "#000000",
        }}
      >
        {data.label}
      </div>
      {data.hasChildren && (
        <span
          style={{
            position: "absolute",
            bottom: -4,
            right: -4,
            width: 18,
            height: 18,
            borderRadius: "50%",
            background: colors.border,
            color: "#ffffff",
            fontSize: 13,
            fontWeight: 700,
            lineHeight: "16px",
            textAlign: "center",
            border: "2px solid #ffffff",
            overflow: "hidden",
          }}
        >
          {data.expanded ? "−" : "+"}
        </span>
      )}
      <Handle type="source" position={Position.Bottom} style={{ opacity: 0 }} />
    </div>
  );
}

const nodeTypes: NodeTypes = {
  ontology: OntologyNode,
};

/**
 * Keep the graph's focal point pinned when the pane is resized.
 *
 * React Flow's viewport transform is anchored at the flow origin, so growing
 * the pane opens the new space at the right/bottom and whatever you were
 * looking at drifts toward the top-left corner. To hold the pane CENTER
 * stationary we shift the viewport by half the size delta: the flow point shown
 * at screen-center is `((w / 2) - x) / zoom`; keeping it fixed as `w → w'` gives
 * `x' = x + (w' - w) / 2` (same for height/y). Zoom is untouched — unlike
 * fitView, this preserves the user's current zoom and pan.
 */
function usePreserveCenterOnResize() {
  const width = useStore((s) => s.width);
  const height = useStore((s) => s.height);
  const { getViewport, setViewport } = useReactFlow();
  const prev = useRef<{ width: number; height: number } | null>(null);

  useEffect(() => {
    if (!width || !height) return; // pane not measured yet
    const last = prev.current;
    prev.current = { width, height };
    if (!last) return; // first measurement — nothing to compensate against
    const dw = width - last.width;
    const dh = height - last.height;
    if (dw === 0 && dh === 0) return;
    const vp = getViewport();
    setViewport({ x: vp.x + dw / 2, y: vp.y + dh / 2, zoom: vp.zoom });
  }, [width, height, getViewport, setViewport]);
}

// ─── Component ──────────────────────────────────────────────────────

function OntologyGraphFlowInner({
  nodes,
  edges,
  onNodeSelect,
  onNodeExpand,
}: Props) {
  const flowNodes: OntologyFlowNode[] = useMemo(
    () =>
      nodes.map((n) => ({
        id: n.id,
        type: "ontology",
        position: { x: 0, y: 0 },
        data: n,
        draggable: true,
      })),
    [nodes],
  );

  const flowEdges: Edge[] = useMemo(
    () =>
      edges.map((e) => ({
        id: e.id,
        source: e.source,
        target: e.target,
        label: e.label,
        style: { stroke: "#94a3b8" },
        labelStyle: { fontSize: 10, fill: "#000000" },
      })),
    [edges],
  );

  const { nodes: initialNodes, edges: layoutEdges } = useMemo(
    () => layoutGraph(flowNodes, flowEdges),
    [flowNodes, flowEdges],
  );

  // Hold the focal point centered across pane resizes (see hook doc).
  usePreserveCenterOnResize();

  const [liveNodes, setLiveNodes] = useState<OntologyFlowNode[]>(initialNodes);

  // Keep in sync when input data changes
  useMemo(() => {
    setLiveNodes(initialNodes);
  }, [initialNodes]);

  const onNodesChange = useCallback(
    (changes: NodeChange<OntologyFlowNode>[]) =>
      setLiveNodes((nds) => applyNodeChanges(changes, nds)),
    [],
  );

  const handleNodeClick = useCallback(
    (_: unknown, node: OntologyFlowNode) => {
      onNodeSelect?.(node.data);
    },
    [onNodeSelect],
  );

  const handleNodeDoubleClick = useCallback(
    (_: unknown, node: OntologyFlowNode) => {
      onNodeExpand?.(node.data);
    },
    [onNodeExpand],
  );

  const handlePaneClick = useCallback(() => {
    onNodeSelect?.(null);
  }, [onNodeSelect]);

  return (
    <ReactFlow
      nodes={liveNodes}
      edges={layoutEdges}
      onNodesChange={onNodesChange}
      nodeTypes={nodeTypes}
      onNodeClick={handleNodeClick}
      onNodeDoubleClick={handleNodeDoubleClick}
      onPaneClick={handlePaneClick}
      fitView
      minZoom={0.3}
      maxZoom={2}
      nodesDraggable
      proOptions={{ hideAttribution: true }}
    >
      <Background variant={BackgroundVariant.Dots} gap={16} size={1} />
      <Controls showInteractive={false} />
      <MiniMap
        nodeColor={(n) => {
          const kind =
            typeof n.data?.kind === "string" ? n.data.kind : "unknown";
          return KIND_COLORS[kind]?.border ?? "#9ca3af";
        }}
        style={{ height: 80, width: 120 }}
      />
      <Panel position="top-right">
        <div
          style={{
            background: "white",
            borderRadius: 6,
            padding: "8px 12px",
            fontSize: 11,
            color: "#000000",
            border: "1px solid #e5e7eb",
          }}
        >
          {LEGEND_ITEMS.map(({ kind, label }) => (
            <div
              key={kind}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 6,
                marginBottom: 3,
              }}
            >
              <span
                style={{
                  width: 10,
                  height: 10,
                  borderRadius: "50%",
                  background: KIND_COLORS[kind].border,
                  display: "inline-block",
                }}
              />
              <span>{label}</span>
            </div>
          ))}
        </div>
      </Panel>
    </ReactFlow>
  );
}

export function OntologyGraphFlow(props: Props) {
  return (
    <ReactFlowProvider>
      <OntologyGraphFlowInner {...props} />
    </ReactFlowProvider>
  );
}
