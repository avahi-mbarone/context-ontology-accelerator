// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import { useGetSourceTable } from "../../../src/api-hooks/use-get-source-table";

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

const MOCK_TABLE = {
  tableId: "tbl-1",
  name: "orders",
  description: "Order records",
  columns: [],
};

describe("useGetSourceTable", () => {
  beforeEach(() => vi.clearAllMocks());

  it("fetches table detail when all IDs are provided", async () => {
    mockSend.mockResolvedValueOnce(MOCK_TABLE);

    const { result } = renderHook(
      () => useGetSourceTable("ns-1", "src-1", "tbl-1"),
      { wrapper },
    );

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual(MOCK_TABLE);
    expect(mockSend).toHaveBeenCalledTimes(1);
  });

  it("is disabled when namespaceId is empty", () => {
    const { result } = renderHook(
      () => useGetSourceTable("", "src-1", "tbl-1"),
      { wrapper },
    );

    expect(result.current.fetchStatus).toBe("idle");
    expect(mockSend).not.toHaveBeenCalled();
  });

  it("is disabled when sourceId is empty", () => {
    const { result } = renderHook(
      () => useGetSourceTable("ns-1", "", "tbl-1"),
      { wrapper },
    );

    expect(result.current.fetchStatus).toBe("idle");
    expect(mockSend).not.toHaveBeenCalled();
  });

  it("is disabled when tableId is empty", () => {
    const { result } = renderHook(
      () => useGetSourceTable("ns-1", "src-1", ""),
      { wrapper },
    );
    expect(result.current.fetchStatus).toBe("idle");
    expect(mockSend).not.toHaveBeenCalled();
  });

  it("handles API error", async () => {
    mockSend.mockRejectedValueOnce(new Error("Not found"));

    const { result } = renderHook(
      () => useGetSourceTable("ns-1", "src-1", "tbl-1"),
      { wrapper },
    );

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error?.message).toBe("Not found");
  });
});
