// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import type { ElementDefinition } from "cytoscape";
import { colorForType, tintForType, sizeForInstances } from "./palette";

type InputNode = {
  id: string;
  data: Record<string, unknown>;
  type?: string;
};

type InputEdge = {
  id: string;
  source: string;
  target: string;
  label?: string;
  type?: string;
  data?: Record<string, unknown>;
};

type InputData = {
  nodes: InputNode[];
  edges: InputEdge[];
  colorMode?: "light" | "dark";
};

function edgeClass(kind: string | undefined): string {
  if (kind === "subclassOf" || kind === "subClassOf") return "subClassOf";
  if (kind === "equivalentClass") return "equivalentClass";
  return "objectProperty";
}

export function toCytoscapeElements(data: InputData): ElementDefinition[] {
  const elements: ElementDefinition[] = [];
  const mode = data.colorMode ?? "light";

  for (const node of data.nodes) {
    const d = node.data;
    const typeIri =
      (d["typeIri"] as string) ?? (d["module"] as string) ?? node.type;
    const prefLabel =
      (d["prefLabel"] as string) ?? (d["label"] as string) ?? node.id;
    const explicitSize = d["moduleNodeSize"] as number | undefined;
    const cls = d["cls"] as { instances?: number; source?: string } | undefined;
    const instances = cls?.instances;
    const nodeSize = explicitSize ?? sizeForInstances(instances);
    const source = cls?.source;
    const status = d["status"] as string | undefined;
    const violationCount = d["violationCount"] as number | undefined;
    const warningCount = d["warningCount"] as number | undefined;

    elements.push({
      data: {
        id: node.id,
        prefLabel,
        typeIri,
        typeColor: colorForType(typeIri, mode),
        tintColor: tintForType(typeIri, mode),
        nodeSize,
        source: source ?? "native",
        isModule: d["isModule"] ?? false,
        hasViolation: (violationCount ?? 0) > 0,
        hasWarning: (warningCount ?? 0) > 0 && (violationCount ?? 0) === 0,
        isProposed: status === "proposed",
        isUnmapped: status === "unmapped",
        ...d,
      },
    });
  }

  for (const edge of data.edges) {
    const ed = edge.data ?? {};
    const kind = (ed["kind"] as string) ?? edge.type;
    const predicateLabel =
      (ed["predicateLabel"] as string) ??
      edge.label ??
      (ed["property"] as string) ??
      "";
    const isInduced = (ed["provenance"] as string) === "induced";
    elements.push({
      data: {
        id: edge.id,
        source: edge.source,
        target: edge.target,
        predicateLabel,
        predicateIri: kind,
        isInduced,
        ...ed,
      },
      classes: edgeClass(kind),
    });
  }

  return elements;
}
