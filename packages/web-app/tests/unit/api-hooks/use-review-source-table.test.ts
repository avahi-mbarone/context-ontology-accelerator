// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import { ReviewDecision } from "@coa/control-plane-client";
import { useReviewSourceTable } from "../../../src/api-hooks/use-review-source-table";

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

describe("useReviewSourceTable", () => {
  beforeEach(() => vi.clearAllMocks());

  it("sends ReviewSourceTableCommand with decision", async () => {
    mockSend.mockResolvedValueOnce({ tableId: "t1", reviewStatus: "APPROVED" });

    const { result } = renderHook(
      () => useReviewSourceTable("ns-1", "src-1", "t1"),
      { wrapper },
    );

    act(() => { result.current.mutate({ decision: ReviewDecision.APPROVED }); });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.reviewStatus).toBe("APPROVED");
    expect(mockSend).toHaveBeenCalledTimes(1);
  });

  it("handles error", async () => {
    mockSend.mockRejectedValueOnce(new Error("409 Conflict"));

    const { result } = renderHook(
      () => useReviewSourceTable("ns-1", "src-1", "t1"),
      { wrapper },
    );

    act(() => { result.current.mutate({ decision: ReviewDecision.APPROVED }); });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error?.message).toBe("409 Conflict");
  });
});
