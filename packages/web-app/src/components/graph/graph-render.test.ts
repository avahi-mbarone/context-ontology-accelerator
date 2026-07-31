// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect } from "vitest";
import {
  colorForType,
  tintForType,
  inducedColor,
  sizeForInstances,
} from "./palette";
import { buildStylesheet } from "./stylesheet";
import { toCytoscapeElements } from "./transform";

describe("palette", () => {
  it("returns hero border color per mode", () => {
    expect(colorForType("x", "light")).toBe("#64748b");
    expect(colorForType("x", "dark")).toBe("#64748b");
    // default mode is light
    expect(colorForType(undefined)).toBe("#64748b");
  });

  it("returns hero fill tint per mode", () => {
    expect(tintForType("x", "light")).toBe("#cbd5e1");
    expect(tintForType("x", "dark")).toBe("#334155");
  });

  it("returns induced fill/border per mode", () => {
    expect(inducedColor("light")).toEqual({
      fill: "#e2e8f0",
      border: "#94a3b8",
    });
    expect(inducedColor("dark")).toEqual({
      fill: "#1e293b",
      border: "#475569",
    });
    expect(inducedColor()).toEqual({ fill: "#e2e8f0", border: "#94a3b8" });
  });

  describe("sizeForInstances", () => {
    it("returns the minimum size for zero/undefined/negative", () => {
      expect(sizeForInstances(undefined)).toBe(22);
      expect(sizeForInstances(0)).toBe(22);
      expect(sizeForInstances(-5)).toBe(22);
    });

    it("scales logarithmically and clamps to [22, 64]", () => {
      const small = sizeForInstances(10);
      const big = sizeForInstances(10_000_000);
      expect(small).toBeGreaterThanOrEqual(22);
      expect(big).toBeLessThanOrEqual(64);
      expect(big).toBeGreaterThan(small);
    });
  });
});

describe("buildStylesheet", () => {
  it("builds a non-empty style array with node and edge selectors", () => {
    const sheet = buildStylesheet("light");
    expect(Array.isArray(sheet)).toBe(true);
    const selectors = sheet.map((r) => r.selector);
    expect(selectors).toContain("node");
    expect(selectors).toContain("edge");
    expect(selectors).toContain("edge.subClassOf");
    expect(selectors).toContain("node:selected");
  });

  it("uses light vs dark label colors", () => {
    const nodeRuleFor = (mode: "light" | "dark") =>
      buildStylesheet(mode).find((r) => r.selector === "node")!.style as Record<
        string,
        unknown
      >;
    expect(nodeRuleFor("light").color).toBe("#1e293b");
    expect(nodeRuleFor("dark").color).toBe("#e2e8f0");
  });

  it("defaults to light mode", () => {
    const def = buildStylesheet();
    const light = buildStylesheet("light");
    expect(JSON.stringify(def)).toBe(JSON.stringify(light));
  });
});

describe("toCytoscapeElements", () => {
  it("maps a node with derived label, size, and status flags", () => {
    const els = toCytoscapeElements({
      nodes: [
        {
          id: "n1",
          type: "Class",
          data: {
            prefLabel: "Customer",
            typeIri: "http://ex/Class",
            cls: { instances: 100, source: "induced" },
            violationCount: 2,
          },
        },
      ],
      edges: [],
    });
    expect(els).toHaveLength(1);
    const d = els[0].data as Record<string, unknown>;
    expect(d.id).toBe("n1");
    expect(d.prefLabel).toBe("Customer");
    expect(d.source).toBe("induced");
    expect(d.hasViolation).toBe(true);
    expect(d.hasWarning).toBe(false); // suppressed when a violation exists
    expect(typeof d.nodeSize).toBe("number");
  });

  it("prefers label fallbacks: prefLabel -> label -> id", () => {
    const [byLabel] = toCytoscapeElements({
      nodes: [{ id: "n1", data: { label: "L" } }],
      edges: [],
    });
    expect((byLabel.data as Record<string, unknown>).prefLabel).toBe("L");

    const [byId] = toCytoscapeElements({
      nodes: [{ id: "onlyId", data: {} }],
      edges: [],
    });
    expect((byId.data as Record<string, unknown>).prefLabel).toBe("onlyId");
  });

  it("flags warning only when there is no violation", () => {
    const [n] = toCytoscapeElements({
      nodes: [{ id: "n", data: { warningCount: 3, violationCount: 0 } }],
      edges: [],
    });
    const d = n.data as Record<string, unknown>;
    expect(d.hasWarning).toBe(true);
    expect(d.hasViolation).toBe(false);
  });

  it("marks proposed and unmapped status", () => {
    const [proposed] = toCytoscapeElements({
      nodes: [{ id: "p", data: { status: "proposed" } }],
      edges: [],
    });
    const [unmapped] = toCytoscapeElements({
      nodes: [{ id: "u", data: { status: "unmapped" } }],
      edges: [],
    });
    expect((proposed.data as Record<string, unknown>).isProposed).toBe(true);
    expect((unmapped.data as Record<string, unknown>).isUnmapped).toBe(true);
  });

  it("honors an explicit moduleNodeSize over instance-derived size", () => {
    const [n] = toCytoscapeElements({
      nodes: [{ id: "m", data: { moduleNodeSize: 50, cls: { instances: 1 } } }],
      edges: [],
    });
    expect((n.data as Record<string, unknown>).nodeSize).toBe(50);
  });

  it("classifies edges: subclass, equivalent, and object property", () => {
    const els = toCytoscapeElements({
      nodes: [],
      edges: [
        { id: "e1", source: "a", target: "b", type: "subClassOf" },
        { id: "e2", source: "a", target: "b", type: "equivalentClass" },
        { id: "e3", source: "a", target: "b", type: "hasPart" },
      ],
    });
    expect(els[0].classes).toBe("subClassOf");
    expect(els[1].classes).toBe("equivalentClass");
    expect(els[2].classes).toBe("objectProperty");
  });

  it("derives edge predicate label and induced flag", () => {
    const [e] = toCytoscapeElements({
      nodes: [],
      edges: [
        {
          id: "e",
          source: "a",
          target: "b",
          data: {
            predicateLabel: "owns",
            provenance: "induced",
            kind: "objectProperty",
          },
        },
      ],
    });
    const d = e.data as Record<string, unknown>;
    expect(d.predicateLabel).toBe("owns");
    expect(d.isInduced).toBe(true);
    expect(d.predicateIri).toBe("objectProperty");
  });

  it("accepts the alternate 'subclassOf' spelling", () => {
    const [e] = toCytoscapeElements({
      nodes: [],
      edges: [{ id: "e", source: "a", target: "b", type: "subclassOf" }],
    });
    expect(e.classes).toBe("subClassOf");
  });
});
