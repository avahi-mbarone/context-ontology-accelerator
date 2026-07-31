// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import { useCreateNamespace } from "../../../src/api-hooks/use-create-namespace";

const mockSend = vi.fn();
vi.mock("../../../src/components/ControlPlaneClientProvider", () => ({
  useControlPlaneClient: () => ({ send: mockSend }),
}));

function wrapper({ children }: { children: React.ReactNode }) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return React.createElement(
    QueryClientProvider,
    { client: queryClient },
    children,
  );
}

describe("useCreateNamespace", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("calls CreateNamespaceCommand and returns result", async () => {
    mockSend.mockResolvedValueOnce({ namespaceId: "ns-new", name: "test-ns" });

    const { result } = renderHook(() => useCreateNamespace(), { wrapper });

    act(() => {
      result.current.mutate({ name: "test-ns", displayName: "Test NS" });
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.namespaceId).toBe("ns-new");
    expect(mockSend.mock.calls[0][0].input.name).toBe("test-ns");
  });

  it("calls onSuccess callback after creation", async () => {
    const onSuccess = vi.fn();
    mockSend.mockResolvedValueOnce({ namespaceId: "ns-1", name: "ns" });

    const { result } = renderHook(() => useCreateNamespace({ onSuccess }), {
      wrapper,
    });

    act(() => {
      result.current.mutate({ name: "ns" });
    });

    await waitFor(() => expect(onSuccess).toHaveBeenCalledOnce());
  });

  it("surfaces error on failure", async () => {
    mockSend.mockRejectedValueOnce(new Error("Conflict"));

    const { result } = renderHook(() => useCreateNamespace(), { wrapper });

    act(() => {
      result.current.mutate({ name: "ns" });
    });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error?.message).toBe("Conflict");
  });
});
