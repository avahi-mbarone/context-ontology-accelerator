// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { InducedOntologyDetailPage } from "./InducedOntologyDetail";

const OVERVIEW = {
  ontologyId: "http://ex.org/o#",
  namespace: "ns",
  graphUri: "https://ontology-workbench.local/ns/o",
  classes: [
    {
      uri: "http://ex.org/o#Claim",
      label: "Claim",
      comment: "A claim.",
      groundedTo: "http://customer.example/onto#Party",
      matchType: "exact",
    },
    { uri: "http://ex.org/o#Policy", label: "Policy", comment: undefined },
  ],
  objectProperties: [
    {
      uri: "http://ex.org/o#hasPolicy",
      label: "has policy",
      domain: "http://ex.org/o#Claim",
      range: "http://ex.org/o#Policy",
    },
  ],
  datatypeProperties: [
    {
      uri: "http://ex.org/o#amount",
      label: "amount",
      domain: "http://ex.org/o#Claim",
      range: "http://www.w3.org/2001/XMLSchema#decimal",
    },
  ],
};

vi.mock("@api-hooks/use-ontology-overview", () => ({
  useOntologyOverview: () => ({
    data: OVERVIEW,
    isLoading: false,
    error: null,
  }),
}));

vi.mock("@api-hooks/use-list-ontologies", () => ({
  useListOntologies: () => ({
    data: [
      {
        ontologyId: "http://ex.org/o#",
        title: "Claims Ontology",
        uri: "http://ex.org/o#",
      },
    ],
  }),
}));

const downloadOntology = vi.fn();
vi.mock("../../services/ontology-engine", () => ({
  downloadOntology: (...args: unknown[]) => downloadOntology(...args),
}));

vi.mock("@components/ontology/PendingReviewBanner", () => ({
  PendingReviewBanner: () => null,
}));

vi.mock("@components/ApiClientProvider", () => ({
  useApiClient: () => ({ get: vi.fn(), getText: vi.fn() }),
}));

function renderAt(search: string) {
  return render(
    <MemoryRouter initialEntries={[`/namespaces/ns/ontology/induced${search}`]}>
      <Routes>
        <Route
          path="/namespaces/:namespaceId/ontology/induced"
          element={<InducedOntologyDetailPage />}
        />
        <Route
          path="/namespaces/:namespaceId/ontology/induced/class"
          element={<div>CLASS_PAGE</div>}
        />
      </Routes>
    </MemoryRouter>,
  );
}

const search = "?ontology_id=http%3A%2F%2Fex.org%2Fo%23";

describe("InducedOntologyDetailPage", () => {
  beforeEach(() => {
    downloadOntology.mockResolvedValue("@prefix ex: <http://ex.org/o#> .");
  });

  it("renders tab counts and origin badges from the hook data", () => {
    const { container } = renderAt(search);
    expect(container.textContent).toContain("Induced Ontology");
    expect(container.textContent).toContain("Classes (2)");
    expect(container.textContent).toContain("Relationships (1)");
    expect(container.textContent).toContain("Attributes (1)");
    expect(container.textContent).toContain("Grounded (exact)");
    expect(container.textContent).toContain("Novel");
  });

  it("navigates to the class drill-down when a class is clicked", async () => {
    const { container } = renderAt(search);
    const claimLink = Array.from(container.querySelectorAll("a")).find(
      (a) => a.textContent === "Claim",
    );
    expect(claimLink).toBeTruthy();
    fireEvent.click(claimLink!);
    expect(container.textContent).toContain("CLASS_PAGE");
  });

  it("loads the Turtle source when the Source tab is opened", async () => {
    const { container } = renderAt(search);
    await userEvent.click(screen.getByText("Source (Turtle)"));
    await vi.waitFor(() => expect(downloadOntology).toHaveBeenCalled());
    await vi.waitFor(() =>
      expect(container.textContent).toContain("@prefix ex:"),
    );
  });

  it("fetches the Turtle when Download .ttl is clicked", async () => {
    const createObjectURL = vi.fn().mockReturnValue("blob:mock");
    const revokeObjectURL = vi.fn();
    vi.stubGlobal("URL", { ...URL, createObjectURL, revokeObjectURL });
    renderAt(search);
    await userEvent.click(screen.getByText("Download .ttl"));
    await vi.waitFor(() => expect(downloadOntology).toHaveBeenCalled());
    expect(createObjectURL).toHaveBeenCalled();
    vi.unstubAllGlobals();
  });

  it("shows an error when ontology_id is missing", () => {
    renderAt("");
    expect(screen.getByText("Missing ontology")).toBeInTheDocument();
  });
});
