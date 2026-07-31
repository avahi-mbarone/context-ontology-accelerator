// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, expect, it } from "vitest";

import { parseTurtleEntities } from "./turtle";

describe("parseTurtleEntities ordering", () => {
  it("orders by kind (Class → ObjectProperty → DatatypeProperty) then alphabetically (case-insensitive) within each kind", () => {
    // Deliberately out of order and mixed-case to exercise both the kind
    // grouping and the case-insensitive alphabetical secondary sort.
    const ttl = `@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix ind: <http://example.com/ind#> .

ind:Zebra a owl:Class ;
    rdfs:label "Zebra" .

ind:apple a owl:Class ;
    rdfs:label "apple" .

ind:Mango a owl:Class .

ind:zeta_rel a owl:ObjectProperty ;
    rdfs:domain ind:Zebra .

ind:alpha_rel a owl:ObjectProperty ;
    rdfs:domain ind:apple .

ind:beta_attr a owl:DatatypeProperty .`;

    const { entities, prelude } = parseTurtleEntities(ttl);

    expect(entities.map((e) => e.subject)).toEqual([
      // Classes, A→Z case-insensitive (apple < Mango < Zebra)
      "ind:apple",
      "ind:Mango",
      "ind:Zebra",
      // Object properties, A→Z
      "ind:alpha_rel",
      "ind:zeta_rel",
      // Datatype properties
      "ind:beta_attr",
    ]);
    expect(prelude).toContain("@prefix owl:");
  });
});
