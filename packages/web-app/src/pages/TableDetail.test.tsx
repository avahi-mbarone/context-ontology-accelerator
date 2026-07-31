// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import React from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { TableDetail } from "./TableDetail";

const mockUseGetSource = vi.fn();

vi.mock("@api-hooks", () => ({
  useGetSourceTable: () => ({
    data: {
      tableId: "sales.orders",
      name: "orders",
      database: "sales",
      reviewStatus: "PENDING_REVIEW",
      businessMetadata: {
        description: "Transactional order records (S3-backed CSV)",
        enrichmentSource: "DETERMINISTIC",
        tags: ["transactional", "s3-backed"],
      },
      primaryKey: {
        columns: ["order_id"],
        source: "DETERMINISTIC",
        confidence: 0,
      },
      foreignKeys: [
        {
          column: "customer_id",
          targetTable: "customers",
          targetColumn: "id",
          source: "AI_INFERRED",
          confidence: 0.92,
        },
      ],
      columns: [
        {
          name: "order_id",
          dataType: "bigint",
          nullable: false,
          businessMetadata: {
            description: "Order id",
            enrichmentSource: "AI_GENERATED",
            confidence: 0.77,
          },
        },
        {
          name: "status",
          dataType: "varchar",
          nullable: false,
          businessMetadata: {
            description: "Order status, curated by data steward",
            enrichmentSource: "STEWARD_EDITED",
            tags: ["lifecycle"],
          },
        },
      ],
      technicalMetadata: {},
    },
    isLoading: false,
    error: null,
  }),
  useGetSource: () => mockUseGetSource(),
  useReviewSourceTable: () => ({ mutate: vi.fn(), isPending: false }),
  useReviewSourceColumn: () => ({ mutate: vi.fn(), isPending: false }),
  useUpdateSourceTableMetadata: () => ({ mutate: vi.fn(), isPending: false }),
  useUpdateSourceColumnMetadata: () => ({ mutate: vi.fn(), isPending: false }),
  useUpdateSourceTableKeys: () => ({
    mutate: vi.fn(),
    isPending: false,
    reset: vi.fn(),
    error: null,
  }),
}));

vi.mock("@coa/control-plane-client", () => ({
  ReviewStatus: {
    APPROVED: "APPROVED",
    PENDING_REVIEW: "PENDING_REVIEW",
    REJECTED: "REJECTED",
  },
  ReviewDecision: { APPROVED: "APPROVED", REJECTED: "REJECTED" },
}));

const wrapper = ({ children }: { children: React.ReactNode }) => (
  <MemoryRouter
    initialEntries={["/namespaces/ns-1/sources/src-1/tables/sales.orders"]}
  >
    <Routes>
      <Route
        path="/namespaces/:namespaceId/sources/:dataSourceId/tables/:tableId"
        element={children}
      />
    </Routes>
  </MemoryRouter>
);

beforeEach(() => {
  mockUseGetSource.mockReset();
  mockUseGetSource.mockReturnValue({
    data: { body: { databaseDetails: { metadataEnrichmentEnabled: true } } },
    isLoading: false,
    error: null,
  });
});

describe("TableDetail keys & relationships", () => {
  it("renders the primary key columns and source", () => {
    render(<TableDetail />, { wrapper });
    expect(screen.getByText("Keys & relationships")).toBeInTheDocument();
    expect(screen.getAllByText("order_id").length).toBeGreaterThan(0);
    expect(screen.getByText("DETERMINISTIC")).toBeInTheDocument();
  });

  it("renders foreign keys with their reference and confidence score", () => {
    render(<TableDetail />, { wrapper });
    expect(screen.getByText("customer_id")).toBeInTheDocument();
    expect(screen.getByText("customers.id")).toBeInTheDocument();
    expect(screen.getByText("AI_INFERRED")).toBeInTheDocument();
    expect(screen.getByText("92%")).toBeInTheDocument();
  });

  it("shows confidence for AI-generated column metadata", () => {
    render(<TableDetail />, { wrapper });
    expect(screen.getByText("77%")).toBeInTheDocument();
  });

  it("opens the edit keys modal", () => {
    render(<TableDetail />, { wrapper });
    fireEvent.click(screen.getByRole("button", { name: /edit keys/i }));
    expect(screen.getByText("Primary key columns")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /add foreign key/i }),
    ).toBeInTheDocument();
  });
});

// DETERMINISTIC only describes the *description* field's
// provenance. Tags/synonyms/glossary terms can still be AI-generated even
// when enrichmentSource is DETERMINISTIC — the UI must not imply the whole
// metadata block came from the source system.
describe("TableDetail enrichment source provenance", () => {
  it("labels the field as 'Description source', not 'Enrichment source'", () => {
    render(<TableDetail />, { wrapper });
    expect(screen.getAllByText("Description source").length).toBeGreaterThan(0);
    expect(screen.queryByText("Enrichment source")).not.toBeInTheDocument();
  });

  it("renders a human-readable provenance label instead of the raw enum", () => {
    render(<TableDetail />, { wrapper });
    expect(screen.getByText("Source catalog")).toBeInTheDocument();
    expect(screen.getByText("Steward-edited")).toBeInTheDocument();
  });

  it("shows an AI-enriched hint icon next to the description source badge when the description is DETERMINISTIC but tags are present", () => {
    render(<TableDetail />, { wrapper });
    // Table-level summary + the "status" column row both qualify — assert at least one hint renders.
    expect(
      screen.getAllByRole("img", { name: "AI-enriched hint" }).length,
    ).toBeGreaterThan(0);
    // Must not render as a plain Badge indistinguishable from real tags.
    expect(screen.queryByText("AI-enriched")).not.toBeInTheDocument();
  });

  it("shows the hint next to the steward-edited column's description source badge, not inside the Tags cell or the name cell", () => {
    render(<TableDetail />, { wrapper });
    const statusRow = screen.getByText("status").closest("tr");
    expect(statusRow).not.toBeNull();
    if (!statusRow) return;

    const hintIcon = statusRow.querySelector(
      '[role="img"][aria-label="AI-enriched hint"]',
    );
    expect(hintIcon).not.toBeNull();

    // The hint must sit in the same cell as the "Steward-edited"
    // description-source badge — not the row's name cell (isRowHeader) or
    // the Tags cell.
    const hintCell = hintIcon?.closest("td, th");
    expect(hintCell?.textContent).toContain("Steward-edited");

    const rowHeaderCell = statusRow.querySelector("th");
    expect(rowHeaderCell?.textContent).toBe("status");
    expect(
      rowHeaderCell?.querySelector(
        '[role="img"][aria-label="AI-enriched hint"]',
      ),
    ).toBeNull();
  });
});

// follow-up: when metadataEnrichmentEnabled is false, the scan
// pipeline never runs the enrichment step at all, so tags/synonyms/glossary
// terms can't be AI-generated regardless of enrichmentSource. The hint must
// not render in that case — showing it would itself be misleading.
describe("TableDetail AI-enriched hint respects metadataEnrichmentEnabled", () => {
  it("suppresses the hint when the source has metadata enrichment disabled", () => {
    mockUseGetSource.mockReturnValue({
      data: {
        body: { databaseDetails: { metadataEnrichmentEnabled: false } },
      },
      isLoading: false,
      error: null,
    });
    render(<TableDetail />, { wrapper });
    expect(
      screen.queryByRole("img", { name: "AI-enriched hint" }),
    ).not.toBeInTheDocument();
  });

  it("shows the hint when metadataEnrichmentEnabled is true", () => {
    mockUseGetSource.mockReturnValue({
      data: {
        body: { databaseDetails: { metadataEnrichmentEnabled: true } },
      },
      isLoading: false,
      error: null,
    });
    render(<TableDetail />, { wrapper });
    expect(
      screen.getAllByRole("img", { name: "AI-enriched hint" }).length,
    ).toBeGreaterThan(0);
  });

  it("defaults to showing the hint when metadataEnrichmentEnabled is undefined (legacy sources)", () => {
    mockUseGetSource.mockReturnValue({
      data: { body: { databaseDetails: {} } },
      isLoading: false,
      error: null,
    });
    render(<TableDetail />, { wrapper });
    expect(
      screen.getAllByRole("img", { name: "AI-enriched hint" }).length,
    ).toBeGreaterThan(0);
  });
});
