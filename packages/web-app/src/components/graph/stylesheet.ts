// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

type ColorMode = "light" | "dark";

const light = {
  nodeLabelColor: "#1e293b",
  nodeLabelBg: "#f8fafc",
  edgeColor: "#cbd5e1",
  edgeLabel: "#64748b",
  edgeLabelBg: "#f8fafc",
  subClassEdge: "#8b5cf6",
};

const dark = {
  nodeLabelColor: "#e2e8f0",
  nodeLabelBg: "#0f172a",
  edgeColor: "#334155",
  edgeLabel: "#64748b",
  edgeLabelBg: "#0f172a",
  subClassEdge: "#a78bfa",
};

export function buildStylesheet(mode: ColorMode = "light") {
  const c = mode === "dark" ? dark : light;
  const isDark = mode === "dark";

  // Status colors — the ONLY use of saturated color in the graph.
  const status = {
    violation: isDark ? "#ef4444" : "#dc2626",
    violationGlow: isDark
      ? "rgba(239, 68, 68, 0.3)"
      : "rgba(220, 38, 38, 0.15)",
    warning: isDark ? "#f59e0b" : "#d97706",
    warningGlow: isDark ? "rgba(245, 158, 11, 0.25)" : "rgba(217, 119, 6, 0.1)",
    proposed: isDark ? "#3b82f6" : "#2563eb",
    unmapped: isDark ? "#6b7280" : "#9ca3af",
  };

  return [
    // --- Nodes: monochrome base ---
    {
      selector: "node",
      style: {
        "background-color": "data(tintColor)",
        "background-opacity": 1,
        "border-width": 1.5,
        "border-color": "data(typeColor)",
        "border-opacity": 0.7,
        width: "data(nodeSize)",
        height: "data(nodeSize)",
        shape: "ellipse",
        label: "data(prefLabel)",
        "text-valign": "bottom",
        "text-halign": "center",
        "text-margin-y": 6,
        "font-size": 10,
        "font-family":
          "'Amazon Ember', 'Noto Sans', -apple-system, BlinkMacSystemFont, sans-serif",
        "font-weight": 400,
        color: c.nodeLabelColor,
        "text-background-color": c.nodeLabelBg,
        "text-background-opacity": 1,
        "text-background-padding": "2px",
        "text-background-shape": "roundrectangle",
        "min-zoomed-font-size": 7,
        "overlay-padding": 4,
        "overlay-opacity": 0,
        "transition-property":
          "border-width, border-opacity, border-color, background-opacity, width, height, shadow-blur, shadow-opacity",
        "transition-duration": 200,
        "transition-timing-function": "ease-out",
      },
    },
    // Hero/native nodes: slightly more present
    {
      selector: 'node[source = "native"]',
      style: {
        "border-width": 2,
        "border-opacity": 0.85,
        "font-weight": 500,
        "font-size": 11,
      },
    },
    // Induced nodes: ghostly, recedes
    {
      selector: 'node[source = "induced"]',
      style: {
        "border-width": 1,
        "border-opacity": 0.35,
        "background-opacity": 0.7,
        "font-size": 9,
        color: isDark ? "#94a3b8" : "#64748b",
      },
    },
    // ═══════════════════════════════════════════════════════════════
    // STATUS — the only saturated color. This is the signal layer.
    // ═══════════════════════════════════════════════════════════════
    {
      selector: "node[?hasViolation]",
      style: {
        "border-color": status.violation,
        "border-width": 3,
        "border-opacity": 1,
        "shadow-blur": 10,
        "shadow-color": status.violation,
        "shadow-opacity": isDark ? 0.35 : 0.2,
        "shadow-offset-x": 0,
        "shadow-offset-y": 0,
      },
    },
    {
      selector: "node[?hasWarning]",
      style: {
        "border-color": status.warning,
        "border-width": 2.5,
        "border-opacity": 1,
        "shadow-blur": 8,
        "shadow-color": status.warning,
        "shadow-opacity": isDark ? 0.25 : 0.12,
        "shadow-offset-x": 0,
        "shadow-offset-y": 0,
      },
    },
    {
      selector: "node[?isProposed]",
      style: {
        "border-color": status.proposed,
        "border-width": 2,
        "border-opacity": 0.85,
        "border-style": "dashed",
      },
    },
    {
      selector: "node[?isUnmapped]",
      style: {
        "border-color": status.unmapped,
        "border-width": 1.5,
        "border-opacity": 0.6,
        "border-style": "dotted",
      },
    },
    {
      selector: "node[?isGrounded]",
      style: {
        "border-color": isDark ? "#22c55e" : "#16a34a",
        "border-width": 2.5,
        "border-opacity": 1,
        "background-color": isDark ? "#052e16" : "#dcfce7",
      },
    },
    // Selected: accent ring + bold label
    {
      selector: "node:selected",
      style: {
        "border-width": 3,
        "border-color": "#0972d3",
        "border-opacity": 1,
        "background-opacity": 1,
        "shadow-blur": 16,
        "shadow-color": "#0972d3",
        "shadow-opacity": isDark ? 0.4 : 0.2,
        "shadow-offset-x": 0,
        "shadow-offset-y": 0,
        "font-weight": 700,
      },
    },
    {
      selector: "node:active",
      style: {
        "overlay-opacity": 0.06,
        "overlay-color": "#0972d3",
      },
    },
    // Module compound nodes (bubble chart view)
    {
      selector: "node[?isModule]",
      style: {
        "background-opacity": isDark ? 0.12 : 0.06,
        "border-width": 1.5,
        "border-opacity": 0.4,
        "font-size": 12,
        "font-weight": 600,
        "text-valign": "center",
        "text-halign": "center",
        "text-margin-y": 0,
        "text-background-opacity": 0,
      },
    },
    // --- Edges ---
    {
      selector: "edge",
      style: {
        "curve-style": "unbundled-bezier",
        "control-point-distances": [20],
        "control-point-weights": [0.5],
        width: 0.8,
        "line-color": c.edgeColor,
        "line-opacity": 0.45,
        "target-arrow-shape": "triangle",
        "target-arrow-color": c.edgeColor,
        "arrow-scale": 0.5,
        label: "data(predicateLabel)",
        "font-size": 8,
        "font-weight": 400,
        "font-family": "'Amazon Ember', 'Noto Sans', -apple-system, sans-serif",
        color: c.edgeLabel,
        "text-background-color": c.edgeLabelBg,
        "text-background-opacity": 1,
        "text-background-padding": "2px",
        "text-background-shape": "roundrectangle",
        "text-rotation": "autorotate",
        "text-margin-y": -7,
        "transition-property": "line-opacity, width",
        "transition-duration": 200,
      },
    },
    // Hierarchy: structural backbone — UML-style hollow triangle on the
    // parent end signals inheritance the way most schema readers expect.
    {
      selector: "edge.subClassOf",
      style: {
        "line-color": c.subClassEdge,
        "line-opacity": 0.55,
        "target-arrow-color": c.subClassEdge,
        "target-arrow-shape": "triangle-tee",
        "target-arrow-fill": "hollow",
        "line-style": "solid",
        width: 1.4,
        "arrow-scale": 1.1,
        "curve-style": "bezier",
      },
    },
    // Property: associative, quiet
    {
      selector: "edge.objectProperty",
      style: {
        "line-style": "dashed",
        "line-dash-pattern": [5, 3],
        "line-opacity": 0.3,
        width: 0.7,
      },
    },
    // Induced edges: barely there
    {
      selector: "edge[?isInduced]",
      style: {
        "line-opacity": 0.18,
        "line-dash-pattern": [3, 4],
        width: 0.5,
      },
    },
    {
      selector: "edge.equivalentClass",
      style: {
        "line-style": "solid",
        "line-color": isDark ? "#a78bfa" : "#7c3aed",
        "target-arrow-color": isDark ? "#a78bfa" : "#7c3aed",
        "source-arrow-shape": "triangle",
        "source-arrow-color": isDark ? "#a78bfa" : "#7c3aed",
        "line-opacity": 0.5,
      },
    },
    // Neighborhood highlight / dim
    {
      selector: "node.highlighted",
      style: {
        "border-opacity": 1,
        "background-opacity": 1,
      },
    },
    {
      selector: "node.dimmed",
      style: {
        "background-opacity": 0.25,
        "border-opacity": 0.15,
        "text-opacity": 0.3,
      },
    },
    {
      selector: "edge.dimmed",
      style: {
        "line-opacity": 0.06,
        "text-opacity": 0,
      },
    },
    {
      selector: "edge.highlighted",
      style: {
        "line-opacity": 0.85,
        width: 1.8,
      },
    },
  ];
}

export const stylesheet = buildStylesheet("light");
