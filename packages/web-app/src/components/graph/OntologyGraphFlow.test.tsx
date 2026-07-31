// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import React from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import {
  OntologyGraphFlow,
  radialPositions,
  type GraphNodeData,
  type GraphEdgeData,
} from "./OntologyGraphFlow";

// React Flow needs ResizeObserver
class ResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}
globalThis.ResizeObserver =
  ResizeObserver as unknown as typeof globalThis.ResizeObserver;

const nodes: GraphNodeData[] = [
  { id: "ex:Claim", label: "Claim", kind: "class" },
  { id: "ex:Policy", label: "Policy", kind: "grounded" },
  { id: "ex:hasPolicy", label: "has policy", kind: "object-property" },
];

const edges: GraphEdgeData[] = [
  { id: "e1", source: "ex:Claim", target: "ex:Policy", label: "hasPolicy" },
];

describe("OntologyGraphFlow", () => {
  it("renders without crashing", () => {
    const { container } = render(
      <OntologyGraphFlow nodes={nodes} edges={edges} />,
    );
    expect(container.querySelector(".react-flow")).toBeTruthy();
  });

  it("renders nodes with labels", () => {
    render(<OntologyGraphFlow nodes={nodes} edges={edges} />);
    expect(screen.getByText("Claim")).toBeTruthy();
    expect(screen.getByText("Policy")).toBeTruthy();
  });

  it("calls onNodeSelect when a node is clicked", () => {
    const onNodeSelect = vi.fn();
    render(
      <OntologyGraphFlow
        nodes={nodes}
        edges={edges}
        onNodeSelect={onNodeSelect}
      />,
    );
    fireEvent.click(screen.getByText("Claim"));
    expect(onNodeSelect).toHaveBeenCalledWith(
      expect.objectContaining({ id: "ex:Claim" }),
    );
  });

  it("renders with empty nodes/edges", () => {
    const { container } = render(<OntologyGraphFlow nodes={[]} edges={[]} />);
    expect(container.querySelector(".react-flow")).toBeTruthy();
  });

  it("lays out edge-less nodes on a circle (not a single row)", () => {
    const pts = radialPositions(6);
    // A flat row collapses to one y; a circle uses many distinct y values.
    expect(new Set(pts.map((p) => Math.round(p.y))).size).toBeGreaterThan(1);
    // All points are roughly equidistant from the centre (on a circle).
    const radii = pts.map((p) => Math.hypot(p.x, p.y));
    const maxR = Math.max(...radii);
    const minR = Math.min(...radii);
    expect(maxR - minR).toBeLessThan(1);
  });

  it("places a single node at the origin", () => {
    expect(radialPositions(1)).toEqual([{ x: 0, y: 0 }]);
  });

  it("calls onNodeExpand when a node is double-clicked", () => {
    const onNodeExpand = vi.fn();
    render(
      <OntologyGraphFlow
        nodes={nodes}
        edges={edges}
        onNodeExpand={onNodeExpand}
      />,
    );
    fireEvent.doubleClick(screen.getByText("Claim"));
    expect(onNodeExpand).toHaveBeenCalledWith(
      expect.objectContaining({ id: "ex:Claim" }),
    );
  });

  it("shows an expand affordance for collapsed nodes with children", () => {
    const withChildren: GraphNodeData[] = [
      { id: "ex:Claim", label: "Claim", kind: "class", hasChildren: true },
    ];
    render(<OntologyGraphFlow nodes={withChildren} edges={[]} />);
    expect(screen.getByText("+")).toBeTruthy();
  });

  it("shows a collapse affordance for expanded nodes", () => {
    const expandedNode: GraphNodeData[] = [
      {
        id: "ex:Claim",
        label: "Claim",
        kind: "class",
        hasChildren: true,
        expanded: true,
      },
    ];
    render(<OntologyGraphFlow nodes={expandedNode} edges={[]} />);
    expect(screen.getByText("−")).toBeTruthy();
  });
});
