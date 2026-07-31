// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

"use client";
import CytoscapeComponent from "react-cytoscapejs";
import cytoscape from "cytoscape";
import fcose from "cytoscape-fcose";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { buildStylesheet } from "./stylesheet";
import { layoutConfig } from "./layout";
import { toCytoscapeElements } from "./transform";

type CytoscapeWithFcoseFlag = typeof cytoscape & {
  __fcoseRegistered?: boolean;
};
const cy = cytoscape as CytoscapeWithFcoseFlag;
if (!cy.__fcoseRegistered) {
  cytoscape.use(fcose);
  cy.__fcoseRegistered = true;
}

export type GraphNodeData = Record<string, unknown> & {
  id?: string;
  prefLabel?: string;
};

type GraphNode = {
  id: string;
  type?: string;
  data: Record<string, unknown>;
};

type GraphEdge = {
  id: string;
  source: string;
  target: string;
  label?: string;
  type?: string;
  data?: Record<string, unknown>;
};

type Props = {
  data: { nodes: GraphNode[]; edges: GraphEdge[] };
  colorMode?: "light" | "dark";
  onNodeSelect?: (nodeData: GraphNodeData | null) => void;
  onNodeDoubleClick?: (nodeData: GraphNodeData) => void;
  onNodeFocus?: (nodeId: string) => void;
  onNodeHide?: (nodeId: string) => void;
  onNodeExpand?: (nodeId: string, hops: number) => void;
};

type ContextMenu = {
  x: number;
  y: number;
  nodeId: string;
  nodeData: GraphNodeData;
} | null;

export function OntologyGraph({
  data,
  colorMode = "light",
  onNodeSelect,
  onNodeDoubleClick,
  onNodeFocus,
  onNodeHide,
  onNodeExpand,
}: Props) {
  const cyRef = useRef<cytoscape.Core | null>(null);
  const [showEdgeLabels, setShowEdgeLabels] = useState(true);
  const [tooltip, setTooltip] = useState<{
    x: number;
    y: number;
    label: string;
    meta: string;
    module?: string;
  } | null>(null);
  const [contextMenu, setContextMenu] = useState<ContextMenu>(null);
  const [hoveredNode, setHoveredNode] = useState<string | null>(null);
  const isDark = colorMode === "dark";

  const elements = useMemo(
    () => toCytoscapeElements({ ...data, colorMode }),
    [data, colorMode],
  );
  const cyStylesheet = useMemo(() => buildStylesheet(colorMode), [colorMode]);
  const hasEdges = data.edges.length > 0;
  const activeLayout = hasEdges
    ? layoutConfig
    : {
        name: "fcose",
        randomize: true,
        animate: false,
        nodeRepulsion: 3000,
        idealEdgeLength: 60,
        gravity: 1.0,
        gravityRange: 80,
        nodeSeparation: 30,
      };

  const handleCy = useCallback(
    (cy: cytoscape.Core) => {
      if (cyRef.current === cy) return;
      cyRef.current = cy;

      cy.nodes().ungrabify();
      cy.nodes().grabify();

      cy.on("tap", "node", (evt) => {
        setContextMenu(null);
        onNodeSelect?.(evt.target.data());
      });
      cy.on("dbltap", "node", (evt) => onNodeDoubleClick?.(evt.target.data()));
      cy.on("tap", (evt) => {
        if (evt.target === cy) {
          onNodeSelect?.(null);
          setContextMenu(null);
          setHoveredNode(null);
        }
      });

      cy.on("mouseover", "node", (evt) => {
        const node = evt.target;
        const pos = node.renderedPosition();
        const d = node.data() as Record<string, unknown>;
        const cls = d["cls"] as
          | { instances?: number; properties?: number; module?: string }
          | undefined;
        const summary = d["summary"] as { classCount?: number } | undefined;
        const moduleId = d["moduleId"] as string | undefined;
        const meta = cls
          ? `${(cls.instances ?? 0).toLocaleString()} instances · ${cls.properties ?? 0} properties`
          : moduleId
            ? `${summary?.classCount ?? 0} classes`
            : "";
        setTooltip({
          x: pos.x,
          y: pos.y - node.renderedWidth() / 2 - 10,
          label:
            (d["prefLabel"] as string | undefined) ??
            (d["id"] as string | undefined) ??
            "",
          meta,
          module: cls?.module ?? moduleId,
        });
        setHoveredNode(node.id());
      });
      cy.on("mouseout", "node", () => {
        setTooltip(null);
        setHoveredNode(null);
      });

      cy.on("cxttap", "node", (evt) => {
        const node = evt.target;
        const pos = evt.renderedPosition ?? node.renderedPosition();
        setContextMenu({
          x: pos.x,
          y: pos.y,
          nodeId: node.id(),
          nodeData: node.data(),
        });
      });

      cy.on("layoutstop", () => {
        cy.fit(undefined, 60);
        // Offset center to account for the right-side panel overlay
        cy.panBy({ x: -160, y: 0 });
      });
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );

  // Neighborhood highlight on hover
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    if (hoveredNode) {
      const node = cy.getElementById(hoveredNode);
      if (node.empty()) return;
      const neighborhood = node.neighborhood().add(node);
      cy.elements().not(neighborhood).addClass("dimmed");
      neighborhood.addClass("highlighted");
      neighborhood.connectedEdges().addClass("highlighted");
    } else {
      cy.elements().removeClass("dimmed highlighted");
    }
  }, [hoveredNode]);

  const toggleLabels = () => {
    setShowEdgeLabels((prev) => {
      const next = !prev;
      if (cyRef.current) {
        cyRef.current
          .edges()
          .style("label", next ? "data(predicateLabel)" : "");
      }
      return next;
    });
  };

  const handleContextAction = (action: string) => {
    if (!contextMenu) return;
    const { nodeId } = contextMenu;
    setContextMenu(null);
    switch (action) {
      case "focus":
        onNodeFocus?.(nodeId);
        break;
      case "hide":
        onNodeHide?.(nodeId);
        if (cyRef.current) {
          cyRef.current.getElementById(nodeId).style("display", "none");
        }
        break;
      case "expand1":
        onNodeExpand?.(nodeId, 1);
        break;
      case "expand2":
        onNodeExpand?.(nodeId, 2);
        break;
    }
  };

  return (
    <div className={`coa-graph ${isDark ? "coa-graph--dark" : ""}`}>
      <CytoscapeComponent
        elements={elements}
        stylesheet={cyStylesheet as cytoscape.StylesheetJson}
        layout={activeLayout}
        cy={handleCy}
        style={{ width: "100%", height: "100%" }}
        wheelSensitivity={0.18}
      />

      {/* Tooltip */}
      {tooltip && (
        <div
          className="coa-graph__tooltip"
          style={{ left: tooltip.x, top: tooltip.y }}
        >
          <span className="coa-graph__tooltip-label">{tooltip.label}</span>
          {tooltip.meta && (
            <span className="coa-graph__tooltip-meta">{tooltip.meta}</span>
          )}
        </div>
      )}

      {/* Context menu */}
      {contextMenu && (
        <div
          className="coa-graph__context-menu"
          style={{ left: contextMenu.x, top: contextMenu.y }}
        >
          <button
            type="button"
            className="coa-graph__context-item"
            onClick={() => handleContextAction("focus")}
          >
            Focus on this class
          </button>
          <button
            type="button"
            className="coa-graph__context-item"
            onClick={() => handleContextAction("expand1")}
          >
            Expand 1 hop
          </button>
          <button
            type="button"
            className="coa-graph__context-item"
            onClick={() => handleContextAction("expand2")}
          >
            Expand 2 hops
          </button>
          <div className="coa-graph__context-divider" />
          <button
            type="button"
            className="coa-graph__context-item coa-graph__context-item--danger"
            onClick={() => handleContextAction("hide")}
          >
            Hide from graph
          </button>
        </div>
      )}

      {/* Controls strip */}
      <div className="coa-graph__controls">
        <label className="coa-graph__control-label">
          <input
            type="checkbox"
            checked={showEdgeLabels}
            onChange={toggleLabels}
            className="coa-graph__control-checkbox"
          />
          <span>Edge labels</span>
        </label>
        <span className="coa-graph__control-divider" />
        <span className="coa-graph__control-hint">
          Scroll to zoom · Drag to pan · Right-click for options
        </span>
      </div>
    </div>
  );
}
