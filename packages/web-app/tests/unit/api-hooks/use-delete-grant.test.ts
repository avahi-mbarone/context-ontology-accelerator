// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import { useDeleteGrant } from "../../../src/api-hooks/use-delete-grant";

const mockSend = vi.fn();
vi.mock("../../../src/components/ControlPlaneClientProvider", () => ({
  useControlPlaneClient: () => ({ send: mockSend }),
}));

vi.mock("@coa/control-plane-client", () => ({
  DeleteGrantCommand: class {
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

describe("useDeleteGrant", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("sends delete command and returns result", async () => {
    mockSend.mockResolvedValueOnce({});

    const { result } = renderHook(() => useDeleteGrant(), { wrapper });

    act(() => {
      result.current.mutate({ namespaceId: "ns-1", grantId: "g-1" });
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(mockSend).toHaveBeenCalledTimes(1);
  });

  it("handles error on delete", async () => {
    mockSend.mockRejectedValueOnce(new Error("Not found"));

    const { result } = renderHook(() => useDeleteGrant(), { wrapper });

    act(() => {
      result.current.mutate({ namespaceId: "ns-1", grantId: "g-bad" });
    });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error?.message).toBe("Not found");
  });
});
