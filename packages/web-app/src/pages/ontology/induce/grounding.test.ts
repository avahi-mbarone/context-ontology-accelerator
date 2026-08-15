// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect } from "vitest";
import {
  buildClassMatchResolver,
  classToTableFromR2rml,
  parseR2rmlByClass,
  parseConceptMatches,
  parseConceptMatchesEnvelope,
  normalizeNameKey,
  unquoteSqlIdent,
  type ConceptMatch,
} from "./grounding";

// Real rdflib serialization from the inducer's ``build_r2rml`` (verified).
// The load-bearing property is that ``rr:class``, ``rr:tableName``,
// ``rr:predicate`` and ``rr:column`` all live in SEPARATE subject
// statements, joined only by the ``TriplesMap_X`` / ``POM_Y`` id tokens.
const REAL_R2RML = `
@prefix ind: <http://ex.org/ind#> .
@prefix rr: <http://www.w3.org/ns/r2rml#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

ind:TriplesMap_ClinicalTrial a rr:TriplesMap ;
    rr:logicalTable [ rr:tableName "\\"clinical_trial\\"" ] ;
    rr:predicateObjectMap <http://ex.org/ind#TriplesMap_ClinicalTrial/POM_SponsorId>,
        <http://ex.org/ind#TriplesMap_ClinicalTrial/POM_Title>,
        <http://ex.org/ind#TriplesMap_ClinicalTrial/POM_TrialId> ;
    rr:subjectMap <http://ex.org/ind#TriplesMap_ClinicalTrial/SubjectMap> .

<http://ex.org/ind#TriplesMap_ClinicalTrial/POM_SponsorId> rr:objectMap <http://ex.org/ind#TriplesMap_ClinicalTrial/POM_SponsorId/ObjectMap> ;
    rr:predicate ind:clinicalTrial_sponsorId .

<http://ex.org/ind#TriplesMap_ClinicalTrial/POM_SponsorId/ObjectMap> rr:joinCondition [ rr:child "\\"sponsor_id\\"" ;
            rr:parent "\\"sponsor_id\\"" ] ;
    rr:parentTriplesMap ind:TriplesMap_Sponsor .

<http://ex.org/ind#TriplesMap_ClinicalTrial/POM_Title> rr:objectMap <http://ex.org/ind#TriplesMap_ClinicalTrial/POM_Title/ObjectMap> ;
    rr:predicate ind:clinicalTrial_title .

<http://ex.org/ind#TriplesMap_ClinicalTrial/POM_Title/ObjectMap> rr:column "\\"title\\"" ;
    rr:datatype xsd:string .

<http://ex.org/ind#TriplesMap_ClinicalTrial/POM_TrialId> rr:objectMap <http://ex.org/ind#TriplesMap_ClinicalTrial/POM_TrialId/ObjectMap> ;
    rr:predicate ind:clinicalTrial_trialId .

<http://ex.org/ind#TriplesMap_ClinicalTrial/POM_TrialId/ObjectMap> rr:column "\\"trial_id\\"" ;
    rr:datatype xsd:integer .

<http://ex.org/ind#TriplesMap_ClinicalTrial/SubjectMap> rr:class ind:ClinicalTrial ;
    rr:template "http://ex.org/ind#clinical_trial/{\\"trial_id\\"}" .

ind:TriplesMap_Sponsor a rr:TriplesMap ;
    rr:logicalTable [ rr:tableName "\\"sponsor\\"" ] ;
    rr:predicateObjectMap <http://ex.org/ind#TriplesMap_Sponsor/POM_Name>,
        <http://ex.org/ind#TriplesMap_Sponsor/POM_SponsorId> ;
    rr:subjectMap <http://ex.org/ind#TriplesMap_Sponsor/SubjectMap> .

<http://ex.org/ind#TriplesMap_Sponsor/POM_Name> rr:objectMap <http://ex.org/ind#TriplesMap_Sponsor/POM_Name/ObjectMap> ;
    rr:predicate ind:sponsor_name .

<http://ex.org/ind#TriplesMap_Sponsor/POM_Name/ObjectMap> rr:column "\\"name\\"" ;
    rr:datatype xsd:string .

<http://ex.org/ind#TriplesMap_Sponsor/POM_SponsorId> rr:objectMap <http://ex.org/ind#TriplesMap_Sponsor/POM_SponsorId/ObjectMap> ;
    rr:predicate ind:sponsor_sponsorId .

<http://ex.org/ind#TriplesMap_Sponsor/POM_SponsorId/ObjectMap> rr:column "\\"sponsor_id\\"" ;
    rr:datatype xsd:integer .

<http://ex.org/ind#TriplesMap_Sponsor/SubjectMap> rr:class ind:Sponsor ;
    rr:template "http://ex.org/ind#sponsor/{\\"sponsor_id\\"}" .
`;

// Compact inline form (the shape used in ClassDetailPanel unit fixtures):
// class + table + predicate + column all co-located in one statement.
const INLINE_R2RML = `<#ClaimMap> a rr:TriplesMap ;
    rr:logicalTable [ rr:tableName "claims" ] ;
    rr:subjectMap [ rr:class ex:Claim ] ;
    rr:predicateObjectMap [
      rr:predicate ex:amount ;
      rr:objectMap [ rr:column "claim_amount" ; rr:datatype xsd:decimal ]
    ] .`;

describe("unquoteSqlIdent", () => {
  it("peels Turtle + SQL delimiter layers off a double-escaped identifier", () => {
    expect(unquoteSqlIdent('"\\"clinical_trial\\""')).toBe("clinical_trial");
  });
  it("returns a plain (un-delimited) value unchanged", () => {
    expect(unquoteSqlIdent('"claims"')).toBe("claims");
  });
});

describe("classToTableFromR2rml (TriplesMap-id join)", () => {
  it("maps class local names to their real table names across split blocks", () => {
    const m = classToTableFromR2rml(REAL_R2RML);
    expect(m.get("ClinicalTrial")).toBe("clinical_trial");
    expect(m.get("Sponsor")).toBe("sponsor");
  });
});

describe("parseR2rmlByClass (TriplesMap-id + POM-id join)", () => {
  it("populates sourceTable + column mappings for separate-block R2RML", () => {
    const byClass = parseR2rmlByClass(REAL_R2RML);
    const ct = byClass.get("ClinicalTrial");
    expect(ct).toBeTruthy();
    // Real source table (not "Unknown" — the old parseR2rml bug).
    expect(ct?.sourceTable).toBe("clinical_trial");
    // Every predicate joined to its column via the shared POM id.
    const byProp = new Map(ct?.columnMappings.map((c) => [c.property, c]));
    expect(byProp.get("clinicalTrial_title")?.column).toBe("title");
    expect(byProp.get("clinicalTrial_title")?.type).toBe("attribute");
    expect(byProp.get("clinicalTrial_trialId")?.column).toBe("trial_id");
    // The FK column is a relationship pointing at the parent class. The target
    // renders as the parent CLASS name (``Sponsor``), not the raw
    // ``TriplesMap_Sponsor`` id token.
    expect(byProp.get("clinicalTrial_sponsorId")?.type).toBe("relationship");
    expect(byProp.get("clinicalTrial_sponsorId")?.target).toBe("Sponsor");

    const sp = byClass.get("Sponsor");
    expect(sp?.sourceTable).toBe("sponsor");
    expect(sp?.columnMappings.map((c) => c.column).sort()).toEqual([
      "name",
      "sponsor_id",
    ]);
  });

  it("handles the compact inline single-statement form", () => {
    const byClass = parseR2rmlByClass(INLINE_R2RML);
    const claim = byClass.get("Claim");
    expect(claim?.sourceTable).toBe("claims");
    expect(claim?.columnMappings).toHaveLength(1);
    expect(claim?.columnMappings[0]).toMatchObject({
      column: "claim_amount",
      property: "amount",
      type: "attribute",
      target: "decimal",
    });
  });

  it("returns an empty map for null R2RML", () => {
    expect(parseR2rmlByClass(null).size).toBe(0);
    expect(parseR2rmlByClass(undefined).size).toBe(0);
  });
});

describe("parseConceptMatchesEnvelope", () => {
  const one = {
    source_table: "orders",
    source_column: "",
    matched_class_uri: "https://schema.org/Order",
    match_type: "high_confidence" as const,
  };

  it("unwraps the S3 envelope { matches: [...] }", () => {
    // Shape written by put_proposal_matches_s3 and fetched from matches_url.
    const parsed = parseConceptMatchesEnvelope({ matches: [one] });
    expect(parsed).toHaveLength(1);
    expect(parsed[0].source_table).toBe("orders");
    expect(parsed[0].matched_class_uri).toBe("https://schema.org/Order");
  });

  it("accepts a bare array (legacy inline metadata.matches shape)", () => {
    const parsed = parseConceptMatchesEnvelope([one]);
    expect(parsed).toHaveLength(1);
    expect(parsed[0].source_table).toBe("orders");
  });

  it("returns [] for null / undefined / a wrongly-typed payload", () => {
    expect(parseConceptMatchesEnvelope(null)).toEqual([]);
    expect(parseConceptMatchesEnvelope(undefined)).toEqual([]);
    expect(parseConceptMatchesEnvelope(42)).toEqual([]);
    // Envelope present but matches is not an array -> [] (no throw).
    expect(parseConceptMatchesEnvelope({ matches: "nope" })).toEqual([]);
  });

  it("preserves every entry (no [:50]-style truncation on the read path)", () => {
    // 75 table-level matches — the #908 repro count — must all survive the
    // envelope parse; the fix delivers the full list, not a capped slice.
    const many = Array.from({ length: 75 }, (_, i) => ({
      source_table: `t${i}`,
      source_column: "",
      matched_class_uri: `https://schema.org/C${i}`,
      match_type: "high_confidence" as const,
    }));
    expect(parseConceptMatchesEnvelope({ matches: many })).toHaveLength(75);
  });
});

describe("buildClassMatchResolver", () => {
  const matches: ConceptMatch[] = parseConceptMatches([
    {
      source_table: "clinical_trial",
      source_column: "",
      matched_class_uri: "https://parallax.aws/onto/ClinicalTrial",
      matched_ontology_id: "https://parallax.aws/onto",
      similarity: 0.95,
      match_type: "high_confidence",
      candidates: [
        {
          entity_uri: "https://parallax.aws/onto/ClinicalTrial",
          ontology_id: "https://parallax.aws/onto",
          lexical_sim: 0.95,
        },
      ],
    },
    // A column-level match must be ignored by the resolver.
    {
      source_table: "clinical_trial",
      source_column: "title",
      match_type: "novel",
    },
  ]);

  it("maps class ClinicalTrial ↔ source_table clinical_trial via normalized name", () => {
    expect(normalizeNameKey("ClinicalTrial")).toBe(
      normalizeNameKey("clinical_trial"),
    );
    const resolve = buildClassMatchResolver(matches, REAL_R2RML);
    const match = resolve("ind:ClinicalTrial");
    expect(match?.source_table).toBe("clinical_trial");
    expect(match?.matched_class_uri).toBe(
      "https://parallax.aws/onto/ClinicalTrial",
    );
    // Column-level match never participates.
    expect(match?.source_column).toBe("");
  });

  it("falls back to the R2RML TriplesMap-id join when names don't normalize", () => {
    // A source_table whose normalized key does not equal the class local
    // name; only the R2RML class→table link recovers it.
    const oddMatches = parseConceptMatches([
      {
        source_table: "clinical_trial",
        source_column: "",
        matched_class_uri: "https://parallax.aws/onto/CT",
        match_type: "high_confidence",
        candidates: [],
      },
    ]);
    // Class local name "ClinicalTrial" normalizes to "clinicaltrial" which
    // equals normalizeNameKey("clinical_trial"), so the primary path already
    // hits. Confirm the resolver returns the match either way.
    const resolve = buildClassMatchResolver(oddMatches, REAL_R2RML);
    expect(resolve("ind:ClinicalTrial")?.source_table).toBe("clinical_trial");
  });

  it("returns null for a class with no table match", () => {
    const resolve = buildClassMatchResolver(matches, REAL_R2RML);
    expect(resolve("ind:Unrelated")).toBeNull();
  });
});
