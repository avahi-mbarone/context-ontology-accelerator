// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import { ReviewDecision } from "@coa/control-plane-client";
import { useReviewSourceColumn } from "../../../src/api-hooks/use-review-source-column";

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

describe("useReviewSourceColumn", () => {
  beforeEach(() => vi.clearAllMocks());

  it("sends ReviewSourceColumnCommand with columnName and decision", async () => {
    mockSend.mockResolvedValueOnce({
      tableId: "t1",
      columnName: "col1",
      reviewStatus: "APPROVED",
    });

    const { result } = renderHook(
      () => useReviewSourceColumn("ns-1", "src-1", "t1"),
      { wrapper },
    );

    act(() => {
      result.current.mutate({
        columnName: "col1",
        decision: ReviewDecision.APPROVED,
      });
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.columnName).toBe("col1");
    expect(result.current.data?.reviewStatus).toBe("APPROVED");
    expect(mockSend).toHaveBeenCalledTimes(1);
  });

  it("handles error", async () => {
    mockSend.mockRejectedValueOnce(new Error("Not found"));

    const { result } = renderHook(
      () => useReviewSourceColumn("ns-1", "src-1", "t1"),
      { wrapper },
    );

    act(() => {
      result.current.mutate({
        columnName: "col1",
        decision: ReviewDecision.REJECTED,
      });
    });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error?.message).toBe("Not found");
  });
});
