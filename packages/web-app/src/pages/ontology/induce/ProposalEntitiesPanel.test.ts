// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect } from "vitest";
import { groupByClass } from "./ProposalEntitiesPanel";
import type { TurtleEntity } from "./turtle";

const NS = "http://coa.amazon.com/namespace/x/ontology/unstructured";

const procedureCls: TurtleEntity = {
  subject: "Banking-Procedure",
  fullSubject: `<${NS}/class/Banking-Procedure>`,
  kind: "owl:Class",
  body:
    `<${NS}/class/Banking-Procedure> a owl:Class ;\n` +
    `    rdfs:label "BankingProcedure"^^xsd:string .`,
};

// The close-match is authored ONLY on Banking-Process, and its target is a
// full IRI containing dots (coa.amazon.com...). This is the exact shape that
// previously truncated at the first dot and produced 0 matches on both sides.
const processCls: TurtleEntity = {
  subject: "Banking-Process",
  fullSubject: `<${NS}/class/Banking-Process>`,
  kind: "owl:Class",
  body:
    `<${NS}/class/Banking-Process> a owl:Class ;\n` +
    `    rdfs:label "BankingProcess"^^xsd:string ;\n` +
    `    skos:closeMatch <${NS}/class/Banking-Procedure> .`,
};

const objProp: TurtleEntity = {
  subject: "associated_with",
  fullSubject: `<${NS}/Banking-Procedure/ObjectProperty/associated_with>`,
  kind: "owl:ObjectProperty",
  body:
    `<${NS}/Banking-Procedure/ObjectProperty/associated_with> a owl:ObjectProperty ;\n` +
    `    rdfs:domain <${NS}/class/Banking-Procedure> ;\n` +
    `    rdfs:range <${NS}/class/System> .`,
};

const dataProp: TurtleEntity = {
  subject: "described_as",
  fullSubject: `<${NS}/Banking-Procedure/DatatypeProperty/described_as>`,
  kind: "owl:DatatypeProperty",
  body:
    `<${NS}/Banking-Procedure/DatatypeProperty/described_as> a owl:DatatypeProperty ;\n` +
    `    rdfs:domain <${NS}/class/Banking-Procedure> ;\n` +
    `    rdfs:range xsd:string .`,
};

describe("groupByClass", () => {
  const { groups } = groupByClass([
    procedureCls,
    processCls,
    objProp,
    dataProp,
  ]);
  const procG = groups.find(
    (g) => g.classEntity.subject === "Banking-Procedure",
  )!;
  const processG = groups.find(
    (g) => g.classEntity.subject === "Banking-Process",
  )!;

  it("splits relationships (object props) from attributes (datatype props) by domain", () => {
    expect(procG.relationships.map((r) => r.subject)).toEqual([
      "associated_with",
    ]);
    expect(procG.attributes.map((a) => a.subject)).toEqual(["described_as"]);
  });

  it("records sibling close-match bidirectionally, resolving full IRIs with dots", () => {
    // Banking-Process authors skos:closeMatch → Banking-Procedure (a SIBLING
    // proposal class — the pattern the unstructured/RIGOR normalizer emits via
    // its per-run dedup index). Both sides get a ``matches`` entry (the target
    // side too), and the dotted class IRI resolves. This feeds the main-table
    // "Matches" column + the card's "Matches" tab.
    expect(processG.matches?.map((m) => m.classUri)).toEqual([
      "Banking-Procedure",
    ]);
    expect(procG.matches?.map((m) => m.classUri)).toEqual(["Banking-Process"]);
    expect(procG.matches?.[0]?.matchType).toBe("close");
  });

  it("does NOT set groundedTo for sibling-to-sibling skos matches", () => {
    // Banking-Process closeMatches Banking-Procedure — both are proposal
    // classes, so this is a dedup relationship (→ ``matches``), NOT foundational
    // grounding, so groundedTo stays null on both.
    expect(processG.groundedTo).toBeNull();
    expect(procG.groundedTo).toBeNull();
  });
});

// ── Item 8: grounding re-keyed to skos:*; Item 2: PK + inheritance ──
describe("groupByClass grounding + inheritance (Item 2 + 8)", () => {
  const groundedCls: TurtleEntity = {
    subject: "ClinicalTrial",
    fullSubject: "ind:ClinicalTrial",
    kind: "owl:Class",
    body:
      `ind:ClinicalTrial a owl:Class ;\n` +
      `    rdfs:label "Clinical Trial" ;\n` +
      // coa:groundedTo is co-emitted on OLD ontologies but must be IGNORED —
      // grounding is read from skos:exactMatch now.
      `    coa:groundedTo <https://parallax.aws/onto/ClinicalStudy> ;\n` +
      `    skos:exactMatch <https://parallax.aws/onto/ClinicalStudy> ;\n` +
      `    owl:hasKey ( ind:clinicalTrial_trialId ) .`,
  };
  const pkSharingCls: TurtleEntity = {
    subject: "Arm",
    fullSubject: "ind:Arm",
    kind: "owl:Class",
    body:
      `ind:Arm a owl:Class ;\n` +
      `    rdfs:label "Arm" ;\n` +
      `    rdfs:subClassOf ind:ClinicalTrial ;\n` +
      `    coa:subClassProvenance "PK_SHARING" ;\n` +
      `    coa:suggestedSubClassOf ind:ClinicalTrial ;\n` +
      `    owl:hasKey ( ind:arm_armId ind:arm_trialId ) .`,
  };
  const { groups } = groupByClass([groundedCls, pkSharingCls]);
  const ct = groups.find((g) => g.classEntity.subject === "ClinicalTrial")!;
  const arm = groups.find((g) => g.classEntity.subject === "Arm")!;

  it("reads foundational grounding from skos:exactMatch (not coa:groundedTo)", () => {
    expect(ct.groundedTo).toBe("ClinicalStudy");
    expect(ct.matchType).toBe("exact");
  });

  it("extracts owl:hasKey columns as bare names", () => {
    expect(ct.pkColumns).toEqual(["clinicalTrial_trialId"]);
    expect(arm.pkColumns).toEqual(["arm_armId", "arm_trialId"]);
  });

  it("surfaces subClassProvenance + suggested-parent flags", () => {
    expect(arm.subClassProvenance).toBe("PK_SHARING");
    expect(arm.hasSuggestedParent).toBe(true);
    // The PK-sharing subClassOf points at a SIBLING ind: class — that must
    // NOT be mistaken for foundational grounding.
    expect(arm.groundedTo).toBeNull();
    expect(ct.hasSuggestedParent).toBe(false);
  });
});

// ── Substring class-name collision: Claim must not absorb ClaimAmount ──
describe("groupByClass domain matching (word-boundary, not substring)", () => {
  const claimCls: TurtleEntity = {
    subject: "Claim",
    fullSubject: "ind:Claim",
    kind: "owl:Class",
    body: `ind:Claim a owl:Class ;\n    rdfs:label "Claim" .`,
  };
  const claimAmountCls: TurtleEntity = {
    subject: "ClaimAmount",
    fullSubject: "ind:ClaimAmount",
    kind: "owl:Class",
    body: `ind:ClaimAmount a owl:Class ;\n    rdfs:label "Claim Amount" .`,
  };
  // A datatype property whose domain is ClaimAmount. ``rdfs:domain ind:Claim``
  // is a substring of ``rdfs:domain ind:ClaimAmount`` — the old ``includes``
  // test wrongly claimed this under ``Claim`` too.
  const amountProp: TurtleEntity = {
    subject: "claimAmount_value",
    fullSubject: "ind:claimAmount_value",
    kind: "owl:DatatypeProperty",
    body:
      `ind:claimAmount_value a owl:DatatypeProperty ;\n` +
      `    rdfs:domain ind:ClaimAmount ;\n` +
      `    rdfs:range xsd:decimal .`,
  };
  // A relationship whose domain IS Claim — must land under Claim only.
  const claimRel: TurtleEntity = {
    subject: "claim_amountRef",
    fullSubject: "ind:claim_amountRef",
    kind: "owl:ObjectProperty",
    body:
      `ind:claim_amountRef a owl:ObjectProperty ;\n` +
      `    rdfs:domain ind:Claim ;\n` +
      `    rdfs:range ind:ClaimAmount .`,
  };
  const { groups } = groupByClass([
    claimCls,
    claimAmountCls,
    amountProp,
    claimRel,
  ]);
  const claim = groups.find((g) => g.classEntity.subject === "Claim")!;
  const claimAmount = groups.find(
    (g) => g.classEntity.subject === "ClaimAmount",
  )!;

  it("groups ClaimAmount's attribute under ClaimAmount, NOT Claim", () => {
    expect(claimAmount.attributes.map((a) => a.subject)).toEqual([
      "claimAmount_value",
    ]);
    // Claim must NOT absorb ClaimAmount's attribute via substring match.
    expect(claim.attributes.map((a) => a.subject)).toEqual([]);
  });

  it("still groups the property whose domain IS Claim under Claim", () => {
    expect(claim.relationships.map((r) => r.subject)).toEqual([
      "claim_amountRef",
    ]);
    expect(claimAmount.relationships.map((r) => r.subject)).toEqual([]);
  });
});
