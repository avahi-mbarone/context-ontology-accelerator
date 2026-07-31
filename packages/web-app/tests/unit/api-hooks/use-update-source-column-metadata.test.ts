// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import { useUpdateSourceColumnMetadata } from "../../../src/api-hooks/use-update-source-column-metadata";

const mockSend = vi.fn();
vi.mock("../../../src/components/ControlPlaneClientProvider", () => ({
  useControlPlaneClient: () => ({ send: mockSend }),
}));

function wrapper({ children }: { children: React.ReactNode }) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return React.createElement(
    QueryClientProvider,
    { client: queryClient },
    children,
  );
}

describe("useUpdateSourceColumnMetadata", () => {
  beforeEach(() => vi.clearAllMocks());

  it("sends UpdateSourceColumnMetadataCommand with columnName and overrides", async () => {
    mockSend.mockResolvedValueOnce({
      tableId: "t1",
      columnName: "col1",
      reviewStatus: "PENDING_REVIEW",
    });

    const { result } = renderHook(
      () => useUpdateSourceColumnMetadata("ns-1", "src-1", "t1"),
      { wrapper },
    );

    act(() => {
      result.current.mutate({
        columnName: "col1",
        overrides: { description: "New desc", synonyms: ["alias"] },
      });
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.columnName).toBe("col1");
    expect(mockSend).toHaveBeenCalledTimes(1);
  });

  it("handles error", async () => {
    mockSend.mockRejectedValueOnce(new Error("Not found"));

    const { result } = renderHook(
      () => useUpdateSourceColumnMetadata("ns-1", "src-1", "t1"),
      { wrapper },
    );

    act(() => {
      result.current.mutate({
        columnName: "col1",
        overrides: { description: "x" },
      });
    });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error?.message).toBe("Not found");
  });
});
