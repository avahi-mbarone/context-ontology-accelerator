// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import { useGetNamespace } from "../../../src/api-hooks/use-get-namespace";

const mockSend = vi.fn();
vi.mock("../../../src/components/ControlPlaneClientProvider", () => ({
  useControlPlaneClient: () => ({ send: mockSend }),
}));

vi.mock("@coa/control-plane-client", () => ({
  GetNamespaceCommand: class {
    input: Record<string, unknown>;
    constructor(input: Record<string, unknown>) {
      this.input = input;
    }
  },
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

describe("useGetNamespace", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("returns namespace on success", async () => {
    mockSend.mockResolvedValueOnce({
      namespace: {
        namespaceId: "ns-1",
        name: "test-ns",
        displayName: "Test NS",
        status: "ACTIVE",
      },
    });

    const { result } = renderHook(() => useGetNamespace("ns-1"), { wrapper });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.namespace?.namespaceId).toBe("ns-1");
  });

  it("sends namespaceId in command", async () => {
    mockSend.mockResolvedValueOnce({ namespace: {} });

    renderHook(() => useGetNamespace("ns-42"), { wrapper });

    await waitFor(() => expect(mockSend).toHaveBeenCalled());
    const command = mockSend.mock.calls[0][0];
    expect(command.input.namespaceId).toBe("ns-42");
  });

  it("does not fetch when namespaceId is empty", async () => {
    const { result } = renderHook(() => useGetNamespace(""), { wrapper });

    await new Promise((r) => setTimeout(r, 50));
    expect(result.current.fetchStatus).toBe("idle");
    expect(mockSend).not.toHaveBeenCalled();
  });

  it("handles error state", async () => {
    mockSend.mockRejectedValueOnce(new Error("Not found"));

    const { result } = renderHook(() => useGetNamespace("ns-bad"), { wrapper });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error?.message).toBe("Not found");
  });
});
