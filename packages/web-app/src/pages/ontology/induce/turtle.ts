// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

export interface TurtleEntity {
  subject: string;
  fullSubject: string;
  body: string;
  kind: string;
}

export interface ParsedTurtle {
  entities: TurtleEntity[];
  prelude: string;
  ontologyDecl: string | null;
}

export function parseTurtleEntities(turtle: string): ParsedTurtle {
  const blocks = turtle
    .split(/\n\s*\n/)
    .map((b) => b.trim())
    .filter(Boolean);

  let prelude = "";
  let ontologyDecl: string | null = null;
  const entities: TurtleEntity[] = [];

  for (const block of blocks) {
    const isPrefix = block
      .split("\n")
      .every((l) => l.trim().startsWith("@prefix") || l.trim() === "");
    if (isPrefix) {
      prelude += (prelude ? "\n\n" : "") + block;
      continue;
    }
    if (/a\s+owl:Ontology/i.test(block)) {
      ontologyDecl = block;
      continue;
    }
    const firstLine = block.split("\n")[0]?.trim() ?? "";
    const subjMatch = firstLine.match(/^(\S+)\s+a\s+([^\s;,.]+)/);
    const subject = subjMatch?.[1] ?? firstLine.split(/\s+/)[0] ?? firstLine;
    const kind = subjMatch?.[2] ?? "";
    const local = subject.split(/[#/]/).pop() ?? subject;
    entities.push({ subject: local, fullSubject: subject, body: block, kind });
  }

  const kindOrder: Record<string, number> = {
    "owl:Class": 0,
    "owl:ObjectProperty": 1,
    "owl:DatatypeProperty": 2,
  };
  // Sort by kind (Classes → object properties → datatype properties), then
  // alphabetically by name (case-insensitive) within each kind. The proposal
  // entities panel and graph derive their ordering from this list, so this
  // makes classes/properties read in a predictable lexicographic order instead
  // of the inducer's raw emit order.
  entities.sort(
    (a, b) =>
      (kindOrder[a.kind] ?? 9) - (kindOrder[b.kind] ?? 9) ||
      a.subject.localeCompare(b.subject, undefined, { sensitivity: "base" }),
  );

  return { entities, prelude, ontologyDecl };
}
