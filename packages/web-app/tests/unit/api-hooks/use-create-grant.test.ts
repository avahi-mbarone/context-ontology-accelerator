// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import { useCreateGrant } from "../../../src/api-hooks/use-create-grant";

const mockSend = vi.fn();
vi.mock("../../../src/components/ControlPlaneClientProvider", () => ({
  useControlPlaneClient: () => ({ send: mockSend }),
}));

vi.mock("@coa/control-plane-client", () => ({
  CreateGrantCommand: class {
    input: Record<string, unknown>;
    constructor(input: Record<string, unknown>) {
      this.input = input;
    }
  },
  ControlPlaneServiceServiceException: class extends Error {},
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

describe("useCreateGrant", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("sends create command and returns result", async () => {
    mockSend.mockResolvedValueOnce({
      grant: { grantId: "g-new", role: "viewer" },
    });

    const { result } = renderHook(() => useCreateGrant(), { wrapper });

    act(() => {
      result.current.mutate({
        namespaceId: "ns-1",
        body: {
          principalType: "User",
          principalId: "user@example.com",
          role: "viewer",
        },
      });
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(mockSend).toHaveBeenCalledTimes(1);
  });

  it("handles error on create", async () => {
    mockSend.mockRejectedValueOnce(new Error("Validation failed"));

    const { result } = renderHook(() => useCreateGrant(), { wrapper });

    act(() => {
      result.current.mutate({
        namespaceId: "ns-1",
        body: {
          principalType: "User",
          principalId: "bad",
          role: "viewer",
        },
      });
    });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error?.message).toBe("Validation failed");
  });
});
