// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import { useListPrincipalGrants } from "../../../src/api-hooks/use-list-principal-grants";

const mockSend = vi.fn();
vi.mock("../../../src/components/ControlPlaneClientProvider", () => ({
  useControlPlaneClient: () => ({ send: mockSend }),
}));

vi.mock("@coa/control-plane-client", () => ({
  ListPrincipalGrantsCommand: class {
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

describe("useListPrincipalGrants", () => {
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
          principalId: "a@b.com",
          role: "owner",
          grantedBy: "admin@b.com",
          grantedAt: "2026-05-01T00:00:00Z",
        },
      ],
    });

    const { result } = renderHook(() => useListPrincipalGrants(), { wrapper });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.grants).toHaveLength(1);
    expect(result.current.data?.grants?.[0].role).toBe("owner");
  });

  it("sends principalId as 'me'", async () => {
    mockSend.mockResolvedValueOnce({ grants: [] });

    renderHook(() => useListPrincipalGrants(), { wrapper });

    await waitFor(() => expect(mockSend).toHaveBeenCalled());
    const command = mockSend.mock.calls[0][0];
    expect(command.input.principalId).toBe("me");
  });

  it("handles error state", async () => {
    mockSend.mockRejectedValueOnce(new Error("Forbidden"));

    const { result } = renderHook(() => useListPrincipalGrants(), { wrapper });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error?.message).toBe("Forbidden");
  });
});
