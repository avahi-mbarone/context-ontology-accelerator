// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import React from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { ConnectSource } from "./ConnectSource";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

const NS_ID = "550e8400-e29b-41d4-a716-446655440000";

const mockCreate = vi.fn();
const mockCreateAsync = vi.fn();

vi.mock("@api-hooks", () => ({
  useCreateSource: ({
    onSuccess,
  }: {
    onSuccess?: (result: { body: { sourceId: string } }) => void;
  } = {}) => ({
    mutate: (args: unknown) => {
      mockCreate(args);
      onSuccess?.({ body: { sourceId: "src-new" } });
    },
    mutateAsync: (args: unknown) => {
      mockCreateAsync(args);
      return Promise.resolve({ body: { sourceId: "src-new" } });
    },
    isPending: false,
    error: null,
  }),
  useGetSourceUploadUrls: () => ({
    mutateAsync: vi.fn().mockResolvedValue({
      s3Prefix: "s3://bucket/prefix",
      uploadUrls: [],
    }),
    isPending: false,
  }),
}));

// Both DATABASE/DOCUMENTS enums and the exception class are imported in the
// component; provide a minimal shim that satisfies both call sites.
vi.mock("@coa/control-plane-client", () => ({
  SourceType: { DATABASE: "DATABASE", DOCUMENTS: "DOCUMENTS" },
  ControlPlaneServiceServiceException: class extends Error {
    constructor(msg = "ControlPlaneServiceServiceException") {
      super(msg);
      this.name = "ControlPlaneServiceServiceException";
    }
  },
}));

// Partial mock: the upload constraints are stubbed to keep this suite independent
// of the real MIME list, but PREVIEW_DATABASE_ENGINES comes from the actual module
// so the engine-picker assertions below test the real launch gate, not a fixture.
vi.mock("@coa/shared", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@coa/shared")>()),
  SUPPORTED_UPLOAD_CONTENT_TYPES: new Set<string>([
    "application/pdf",
    "text/plain",
  ]),
  MAX_UPLOAD_FILES: 100,
}));

vi.mock("@utils/helpers", () => ({
  S3_ARN_RE: /^arn:aws:s3:::[a-z0-9.-]+$/,
  validateS3Prefix: () => null,
}));

// ---------------------------------------------------------------------------
// Wrapper
// ---------------------------------------------------------------------------

const wrapper = ({ children }: { children: React.ReactNode }) => (
  <QueryClientProvider client={new QueryClient()}>
    <MemoryRouter initialEntries={[`/namespaces/${NS_ID}/sources/connect`]}>
      <Routes>
        <Route
          path="/namespaces/:namespaceId/sources/connect"
          element={children}
        />
        <Route
          path="/namespaces/:namespaceId/sources/:sourceId"
          element={<div>SOURCE_DETAIL</div>}
        />
        <Route
          path="/namespaces/:namespaceId/sources"
          element={<div>SOURCE_LIST</div>}
        />
      </Routes>
    </MemoryRouter>
  </QueryClientProvider>
);

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const user = userEvent.setup({ delay: null });

/** Click the wizard's "Next" button. Cloudscape renders it with that label. */
async function clickNext() {
  await user.click(screen.getByRole("button", { name: /^next$/i }));
}

/** Walk the Glue wizard from step 1 → step 3 (enrichment) with valid inputs. */
async function navigateToEnrichmentStep() {
  await clickNext();
  await user.type(screen.getByPlaceholderText("My Glue Database"), "my-db");
  await user.type(screen.getByPlaceholderText("123456789012"), "123456789012");
  await user.type(screen.getByPlaceholderText("my_glue_db"), "my_db");
  await clickNext();
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("ConnectSource — metadata enrichment toggle", () => {
  beforeEach(() => {
    mockCreate.mockReset();
    mockCreateAsync.mockReset();
  });

  it("renders the AI metadata enrichment toggle in the enrichment step", async () => {
    render(<ConnectSource />, { wrapper });

    await navigateToEnrichmentStep();

    expect(
      screen.getByText(/Enable AI metadata enrichment/i),
    ).toBeInTheDocument();
  });

  it("submits metadataEnrichmentEnabled=true when the toggle is left on", async () => {
    render(<ConnectSource />, { wrapper });

    await navigateToEnrichmentStep();
    // Step 3 — leave the toggle in its default (on) state, advance to review.
    await clickNext();
    // Step 4 — submit. The Wizard's submit button uses i18nStrings text.
    await user.click(screen.getByRole("button", { name: /^connect source$/i }));

    expect(mockCreate).toHaveBeenCalledTimes(1);
    const body = mockCreate.mock.calls[0][0].body;
    expect(body.databaseSource.metadataEnrichmentEnabled).toBe(true);
  });

  it("submits metadataEnrichmentEnabled=false after toggling the switch off", async () => {
    render(<ConnectSource />, { wrapper });

    await navigateToEnrichmentStep();

    // Cloudscape Toggle exposes a checkbox-role input under the hood; clicking
    // the visible label flips it.
    await user.click(screen.getByText(/Enable AI metadata enrichment/i));

    await clickNext();
    await user.click(screen.getByRole("button", { name: /^connect source$/i }));

    expect(mockCreate).toHaveBeenCalledTimes(1);
    const body = mockCreate.mock.calls[0][0].body;
    expect(body.databaseSource.metadataEnrichmentEnabled).toBe(false);
  });

  it("review step reflects the toggle state in the enrichment summary", async () => {
    render(<ConnectSource />, { wrapper });

    await navigateToEnrichmentStep();
    await user.click(screen.getByText(/Enable AI metadata enrichment/i));
    await clickNext();

    // Review step renders a "Metadata enrichment" KeyValuePair whose value
    // is "Disabled" when the toggle is off.
    expect(screen.getByText("Metadata enrichment")).toBeInTheDocument();
    expect(screen.getByText("Disabled")).toBeInTheDocument();
  });
});

describe("ConnectSource — advanced configuration", () => {
  beforeEach(() => {
    mockCreate.mockReset();
    mockCreateAsync.mockReset();
  });

  it("renders required field indicators on JDBC form", async () => {
    render(<ConnectSource />, { wrapper });

    // Select JDBC tile
    await user.click(screen.getByLabelText("JDBC database"));
    await clickNext();

    // Required fields should have asterisks
    expect(
      screen.getByText("Source name", { exact: false }),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Database engine", { exact: false }),
    ).toBeInTheDocument();
    expect(screen.getByText("Host", { exact: false })).toBeInTheDocument();
  });

  it("renders advanced configuration section for JDBC with new filter fields", async () => {
    render(<ConnectSource />, { wrapper });

    await user.click(screen.getByLabelText("JDBC database"));
    await clickNext();

    // Advanced section should be present
    const advancedSection = screen.getByText("Advanced configuration");
    expect(advancedSection).toBeInTheDocument();

    // Expand it
    await user.click(advancedSection);

    // New exclude filter fields should be present
    expect(screen.getByText("Schema exclude filter")).toBeInTheDocument();
    expect(screen.getByText("Table exclude filter")).toBeInTheDocument();
  });

  // Types out several long fields character-by-character across a multi-step
  // wizard — exceeds the 5000ms vitest default under CI load.
  it(
    "submits schemaExcludeFilter and tableExcludeFilter for JDBC when provided",
    { timeout: 15000 },
    async () => {
      render(<ConnectSource />, { wrapper });

      await user.click(screen.getByLabelText("JDBC database"));
      await clickNext();

      // Fill required fields
      await user.type(
        screen.getByPlaceholderText("My JDBC Database"),
        "test-db",
      );
      await user.click(screen.getByText("Select an engine"));
      await user.click(screen.getAllByText("PostgreSQL")[0]);
      await user.type(
        screen.getByPlaceholderText("db.example.com"),
        "localhost",
      );
      await user.type(screen.getByPlaceholderText("my_database"), "testdb");
      await user.type(
        screen.getByPlaceholderText("arn:aws:secretsmanager:..."),
        "arn:aws:secretsmanager:us-east-1:123456789012:secret:db",
      );

      // Expand advanced config
      await user.click(screen.getByText("Advanced configuration"));

      // Fill exclude filters
      await user.type(
        screen.getByPlaceholderText("temp_*|staging_*"),
        "temp_*|test_*",
      );
      await user.type(
        screen.getByPlaceholderText("tmp_*|staging_*"),
        "tmp_*|scratch_*",
      );

      await clickNext(); // → enrichment
      await clickNext(); // → review
      await user.click(
        screen.getByRole("button", { name: /^connect source$/i }),
      );

      expect(mockCreate).toHaveBeenCalledTimes(1);
      const cfg =
        mockCreate.mock.calls[0][0].body.databaseSource.jdbcConfiguration;
      expect(cfg.schemaExcludeFilter).toBe("temp_*|test_*");
      expect(cfg.tableExcludeFilter).toBe("tmp_*|scratch_*");
    },
  );

  it("renders tableExcludeFilter for Glue in advanced config", async () => {
    render(<ConnectSource />, { wrapper });

    // Glue is default
    await clickNext();

    // Fill required fields
    await user.type(screen.getByPlaceholderText("My Glue Database"), "test-db");
    await user.type(
      screen.getByPlaceholderText("123456789012"),
      "123456789012",
    );
    await user.type(screen.getByPlaceholderText("my_glue_db"), "testdb");

    // Expand advanced config
    await user.click(screen.getByText("Advanced configuration"));

    // New exclude filter field should be present
    expect(screen.getByText("Table exclude filter")).toBeInTheDocument();
  });

  it("submits tableExcludeFilter for Glue when provided", async () => {
    render(<ConnectSource />, { wrapper });

    await clickNext();
    await user.type(screen.getByPlaceholderText("My Glue Database"), "test-db");
    await user.type(
      screen.getByPlaceholderText("123456789012"),
      "123456789012",
    );
    await user.type(screen.getByPlaceholderText("my_glue_db"), "testdb");

    // Expand advanced and fill exclude filter
    await user.click(screen.getByText("Advanced configuration"));
    await user.type(
      screen.getByPlaceholderText("tmp_.*|staging_.*"),
      "tmp_.*|backup_.*",
    );

    await clickNext(); // → enrichment
    await clickNext(); // → review
    await user.click(screen.getByRole("button", { name: /^connect source$/i }));

    expect(mockCreate).toHaveBeenCalledTimes(1);
    const cfg =
      mockCreate.mock.calls[0][0].body.databaseSource.glueConfiguration;
    expect(cfg.tableExcludeFilter).toBe("tmp_.*|backup_.*");
  });

  it("does not offer engines withheld from the product", async () => {
    render(<ConnectSource />, { wrapper });

    await user.click(screen.getByLabelText("JDBC database"));
    await clickNext();
    await user.click(screen.getByText("Select an engine"));

    // Snowflake/Oracle dialects are implemented but withheld pending validation
    // (PREVIEW_DATABASE_ENGINES), so they must not appear in the engine picker.
    expect(screen.queryByText("Snowflake")).not.toBeInTheDocument();
    expect(screen.queryByText("Oracle")).not.toBeInTheDocument();
    // The enabled engines are still offered.
    expect(screen.getAllByText("PostgreSQL")[0]).toBeInTheDocument();
    expect(screen.getAllByText("SQL Server")[0]).toBeInTheDocument();
  });

  it("does not advertise withheld engines in the JDBC source description", () => {
    render(<ConnectSource />, { wrapper });

    const description = screen.getByText(/Supported engines:/);
    expect(description.textContent).toContain("PostgreSQL");
    expect(description.textContent).not.toContain("Snowflake");
    expect(description.textContent).not.toContain("Oracle");
  });
});

describe("ConnectSource — cross-account IAM role validation", () => {
  /**
   * Validate cross-account IAM role ARN format.
   * Backend IAM policy restricts AssumeRole to roles matching:
   *   arn:aws:iam::*:role/{prefix}-{env}-datasource-access-*
   * Default prefix is "coa", default env is "dev", so pattern becomes:
   *   arn:aws:iam::ACCOUNT:role/coa-dev-datasource-access-SUFFIX
   */
  function validateCrossAccountRoleArn(arn: string): string | undefined {
    if (!arn.trim()) return undefined;
    const roleArnPattern =
      /^arn:aws:iam::\d{12}:role\/[a-zA-Z0-9_+=,.@-]+-datasource-access-[a-zA-Z0-9_+=,.@-]+$/;
    if (!roleArnPattern.test(arn.trim())) {
      return "Role ARN must match pattern: arn:aws:iam::ACCOUNT:role/{prefix}-datasource-access-*";
    }
    return undefined;
  }

  it("accepts empty role ARN (optional field)", () => {
    expect(validateCrossAccountRoleArn("")).toBeUndefined();
    expect(validateCrossAccountRoleArn("   ")).toBeUndefined();
  });

  it("accepts valid role ARN with datasource-access pattern", () => {
    expect(
      validateCrossAccountRoleArn(
        "arn:aws:iam::123456789012:role/coa-dev-datasource-access-acme",
      ),
    ).toBeUndefined();
    expect(
      validateCrossAccountRoleArn(
        "arn:aws:iam::222222222222:role/coa-dev-datasource-access-glue-catalog",
      ),
    ).toBeUndefined();
  });

  it("rejects role ARN missing datasource-access infix", () => {
    const error = validateCrossAccountRoleArn(
      "arn:aws:iam::123456789012:role/coa-dev-my-role",
    );
    expect(error).toBe(
      "Role ARN must match pattern: arn:aws:iam::ACCOUNT:role/{prefix}-datasource-access-*",
    );
  });

  it("rejects role ARN with datasource-access but no prefix", () => {
    const error = validateCrossAccountRoleArn(
      "arn:aws:iam::123456789012:role/datasource-access-acme",
    );
    expect(error).toBe(
      "Role ARN must match pattern: arn:aws:iam::ACCOUNT:role/{prefix}-datasource-access-*",
    );
  });

  it("rejects role ARN with datasource-access but no suffix", () => {
    const error = validateCrossAccountRoleArn(
      "arn:aws:iam::123456789012:role/coa-dev-datasource-access-",
    );
    expect(error).toBe(
      "Role ARN must match pattern: arn:aws:iam::ACCOUNT:role/{prefix}-datasource-access-*",
    );
  });

  it("rejects invalid account number", () => {
    const error = validateCrossAccountRoleArn(
      "arn:aws:iam::12345:role/coa-dev-datasource-access-acme",
    );
    expect(error).toBe(
      "Role ARN must match pattern: arn:aws:iam::ACCOUNT:role/{prefix}-datasource-access-*",
    );
  });
});

describe("ConnectSource — cross-account IAM role", () => {
  beforeEach(() => {
    mockCreate.mockReset();
    mockCreateAsync.mockReset();
  });

  // Types out several long fields (including a full IAM role ARN)
  // character-by-character via user-event across a 3-step wizard, which is
  // consistently slower than the 5000ms vitest default under CI load —
  // bump the timeout for this test rather than the global default.
  it("submits the Glue cross-account role ARN and external ID when provided", async () => {
    render(<ConnectSource />, { wrapper });

    // Step 1 — Glue is the default tile.
    await clickNext();
    // Step 2 — required fields + cross-account fields.
    await user.type(screen.getByPlaceholderText("My Glue Database"), "my-db");
    await user.type(
      screen.getByPlaceholderText("123456789012"),
      "123456789012",
    );
    await user.type(screen.getByPlaceholderText("my_glue_db"), "my_db");
    await user.type(
      screen.getByPlaceholderText(
        "arn:aws:iam::222222222222:role/coa-dev-datasource-access-acme",
      ),
      "arn:aws:iam::222222222222:role/coa-dev-datasource-access-acme",
    );
    await user.type(
      screen.getByPlaceholderText("optional-external-id"),
      "ext-abc",
    );
    await clickNext(); // → enrichment step
    await clickNext(); // → review step
    await user.click(screen.getByRole("button", { name: /^connect source$/i }));

    expect(mockCreate).toHaveBeenCalledTimes(1);
    const cfg =
      mockCreate.mock.calls[0][0].body.databaseSource.glueConfiguration;
    expect(cfg.crossAccountRoleArn).toBe(
      "arn:aws:iam::222222222222:role/coa-dev-datasource-access-acme",
    );
    expect(cfg.externalId).toBe("ext-abc");
  }, 15000);

  it("blocks navigation to next step when Glue cross-account role ARN is invalid", async () => {
    render(<ConnectSource />, { wrapper });

    await clickNext();
    await user.type(screen.getByPlaceholderText("My Glue Database"), "my-db");
    await user.type(
      screen.getByPlaceholderText("123456789012"),
      "123456789012",
    );
    await user.type(screen.getByPlaceholderText("my_glue_db"), "my_db");
    // Type an invalid role ARN (missing datasource-access infix)
    await user.type(
      screen.getByPlaceholderText(
        "arn:aws:iam::222222222222:role/coa-dev-datasource-access-acme",
      ),
      "arn:aws:iam::222222222222:role/coa-dev-my-role",
    );
    await clickNext();

    // Should show error and block navigation
    expect(
      screen.getByText(/Role ARN must match pattern/i),
    ).toBeInTheDocument();
    // Still on step 2 — enrichment toggle not visible (only appears on enrichment step)
    expect(
      screen.queryByText(/Enable AI metadata enrichment/i),
    ).not.toBeInTheDocument();
  });

  // Types out several long fields (engine selection, host, database, a
  // Secrets Manager ARN, and a full IAM role ARN) character-by-character via
  // user-event across the wizard, which is consistently slower than the 5000ms
  // vitest default under CI load — bump the timeout for this test rather than
  // the global default.
  it("blocks navigation to next step when JDBC cross-account role ARN is invalid", async () => {
    render(<ConnectSource />, { wrapper });

    await user.click(screen.getByLabelText("JDBC database"));
    await clickNext();
    await user.type(screen.getByPlaceholderText("My JDBC Database"), "test-db");
    await user.click(screen.getByText("Select an engine"));
    await user.click(screen.getAllByText("PostgreSQL")[0]);
    await user.type(screen.getByPlaceholderText("db.example.com"), "localhost");
    await user.type(screen.getByPlaceholderText("my_database"), "testdb");
    await user.type(
      screen.getByPlaceholderText("arn:aws:secretsmanager:..."),
      "arn:aws:secretsmanager:us-east-1:123456789012:secret:db",
    );

    // Expand advanced config
    await user.click(screen.getByText("Advanced configuration"));

    // Type an invalid role ARN (no prefix before datasource-access)
    await user.type(
      screen.getByPlaceholderText(
        "arn:aws:iam::222222222222:role/coa-dev-datasource-access-acme",
      ),
      "arn:aws:iam::222222222222:role/datasource-access-acme",
    );
    await clickNext();

    // Should show error and block navigation
    expect(
      screen.getByText(/Role ARN must match pattern/i),
    ).toBeInTheDocument();
    // Still on step 2 — enrichment toggle not visible (only appears on enrichment step)
    expect(
      screen.queryByText(/Enable AI metadata enrichment/i),
    ).not.toBeInTheDocument();
  }, 15000);

  it("omits cross-account fields from the Glue payload when left blank", async () => {
    render(<ConnectSource />, { wrapper });

    await clickNext();
    await user.type(screen.getByPlaceholderText("My Glue Database"), "my-db");
    await user.type(
      screen.getByPlaceholderText("123456789012"),
      "123456789012",
    );
    await user.type(screen.getByPlaceholderText("my_glue_db"), "my_db");
    await clickNext();
    await clickNext();
    await user.click(screen.getByRole("button", { name: /^connect source$/i }));

    const cfg =
      mockCreate.mock.calls[0][0].body.databaseSource.glueConfiguration;
    expect(cfg.crossAccountRoleArn).toBeUndefined();
    expect(cfg.externalId).toBeUndefined();
  });
});
