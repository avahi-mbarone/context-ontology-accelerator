// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { renderHook, waitFor, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, it, expect, vi } from "vitest";
import React from "react";
import { useUpdateNamespace } from "./use-update-namespace";

const mockSend = vi.fn();

vi.mock("@components/ControlPlaneClientProvider", () => ({
  useControlPlaneClient: () => ({ send: mockSend }),
}));

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return {
    wrapper: ({ children }: { children: React.ReactNode }) =>
      React.createElement(
        QueryClientProvider,
        { client: queryClient },
        children,
      ),
    queryClient,
  };
}

describe("useUpdateNamespace", () => {
  it("sends update command and invalidates caches", async () => {
    mockSend.mockResolvedValueOnce({ namespace: { namespaceId: "ns-1" } });
    const { wrapper, queryClient } = createWrapper();
    const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");

    const { result } = renderHook(() => useUpdateNamespace(), { wrapper });

    act(() => {
      result.current.mutate({
        namespaceId: "ns-1",
        displayName: "Updated",
        description: "New desc",
      });
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(mockSend).toHaveBeenCalledOnce();
    expect(invalidateSpy).toHaveBeenCalledWith({
      queryKey: ["namespace", "ns-1"],
    });
    expect(invalidateSpy).toHaveBeenCalledWith({
      queryKey: ["namespaces"],
    });
  });

  it("handles mutation errors", async () => {
    mockSend.mockRejectedValueOnce(new Error("Update failed"));
    const { wrapper } = createWrapper();

    const { result } = renderHook(() => useUpdateNamespace(), { wrapper });

    act(() => {
      result.current.mutate({
        namespaceId: "ns-1",
        displayName: "X",
        description: "Y",
      });
    });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error?.message).toBe("Update failed");
  });
});
