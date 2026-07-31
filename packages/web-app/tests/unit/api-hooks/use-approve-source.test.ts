// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import { useApproveSource } from "../../../src/api-hooks/use-approve-source";

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

describe("useApproveSource", () => {
  beforeEach(() => vi.clearAllMocks());

  it("sends ApproveSourceCommand and returns result", async () => {
    mockSend.mockResolvedValueOnce({ status: "APPROVING" });

    const { result } = renderHook(
      () => useApproveSource("ns-1", "src-1"),
      { wrapper },
    );

    act(() => { result.current.mutate({}); });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.status).toBe("APPROVING");
    expect(mockSend).toHaveBeenCalledTimes(1);
  });

  it("handles error", async () => {
    mockSend.mockRejectedValueOnce(new Error("Conflict"));

    const { result } = renderHook(
      () => useApproveSource("ns-1", "src-1"),
      { wrapper },
    );

    act(() => { result.current.mutate({}); });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error?.message).toBe("Conflict");
  });
});
