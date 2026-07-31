// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import { useUpdateNamespaceStatus } from "../../../src/api-hooks/use-update-namespace-status";

const mockSend = vi.fn();
vi.mock("../../../src/components/ControlPlaneClientProvider", () => ({
  useControlPlaneClient: () => ({ send: mockSend }),
}));

vi.mock("@coa/control-plane-client", () => ({
  UpdateNamespaceStatusCommand: class {
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

describe("useUpdateNamespaceStatus", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("sends update command and returns result", async () => {
    mockSend.mockResolvedValueOnce({ namespace: { status: "ARCHIVED" } });

    const { result } = renderHook(() => useUpdateNamespaceStatus(), {
      wrapper,
    });

    act(() => {
      result.current.mutate({ namespaceId: "ns-1", status: "ARCHIVED" });
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(mockSend).toHaveBeenCalledTimes(1);
  });

  it("handles error on update", async () => {
    mockSend.mockRejectedValueOnce(new Error("Forbidden"));

    const { result } = renderHook(() => useUpdateNamespaceStatus(), {
      wrapper,
    });

    act(() => {
      result.current.mutate({ namespaceId: "ns-1", status: "DELETED" });
    });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error?.message).toBe("Forbidden");
  });
});
