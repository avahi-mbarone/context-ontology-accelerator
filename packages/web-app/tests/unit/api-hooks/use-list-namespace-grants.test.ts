// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import { useListNamespaceGrants } from "../../../src/api-hooks/use-list-namespace-grants";

const mockSend = vi.fn();
vi.mock("../../../src/components/ControlPlaneClientProvider", () => ({
  useControlPlaneClient: () => ({ send: mockSend }),
}));

vi.mock("@coa/control-plane-client", () => ({
  ListNamespaceGrantsCommand: class {
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

describe("useListNamespaceGrants", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("returns grants on success", async () => {
    mockSend.mockResolvedValueOnce({
      grants: [
        {
          grantId: "g1",
          namespaceId: "ns-1",
          principalType: "User",
          principalId: "user@example.com",
          role: "owner",
          grantedBy: "admin@example.com",
          grantedAt: "2026-05-01T00:00:00Z",
        },
      ],
    });

    const { result } = renderHook(() => useListNamespaceGrants("ns-1"), {
      wrapper,
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.pages[0].grants).toHaveLength(1);
    expect(result.current.data?.pages[0].grants?.[0].principalId).toBe(
      "user@example.com",
    );
  });

  it("sends namespaceId in command", async () => {
    mockSend.mockResolvedValueOnce({ grants: [] });

    renderHook(() => useListNamespaceGrants("ns-42"), { wrapper });

    await waitFor(() => expect(mockSend).toHaveBeenCalled());
    const command = mockSend.mock.calls[0][0];
    expect(command.input.namespaceId).toBe("ns-42");
  });

  it("does not fetch when namespaceId is empty", async () => {
    const { result } = renderHook(() => useListNamespaceGrants(""), {
      wrapper,
    });

    await new Promise((r) => setTimeout(r, 50));
    expect(result.current.fetchStatus).toBe("idle");
    expect(mockSend).not.toHaveBeenCalled();
  });

  it("handles error state", async () => {
    mockSend.mockRejectedValueOnce(new Error("Access denied"));

    const { result } = renderHook(() => useListNamespaceGrants("ns-1"), {
      wrapper,
    });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error?.message).toBe("Access denied");
  });
});
