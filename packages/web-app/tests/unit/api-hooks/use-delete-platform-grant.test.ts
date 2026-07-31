// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import { useDeletePlatformGrant } from "../../../src/api-hooks/use-delete-platform-grant";

const mockSend = vi.fn();
vi.mock("../../../src/components/ControlPlaneClientProvider", () => ({
  useControlPlaneClient: () => ({ send: mockSend }),
}));

vi.mock("@coa/control-plane-client", () => ({
  DeletePlatformGrantCommand: class {
    input: Record<string, unknown>;
    constructor(input: Record<string, unknown>) {
      this.input = input;
    }
  },
  ControlPlaneServiceServiceException: class extends Error {},
}));

function makeWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");
  const wrapper = ({ children }: { children: React.ReactNode }) =>
    React.createElement(QueryClientProvider, { client: queryClient }, children);
  return { wrapper, invalidateSpy };
}

describe("useDeletePlatformGrant", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("sends DeletePlatformGrantCommand and returns the result", async () => {
    mockSend.mockResolvedValueOnce({});
    const { wrapper } = makeWrapper();

    const { result } = renderHook(() => useDeletePlatformGrant(), { wrapper });
    act(() => {
      result.current.mutate({ grantId: "pg-1" });
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(mockSend).toHaveBeenCalledTimes(1);
    expect(mockSend.mock.calls[0][0].input.grantId).toBe("pg-1");
  });

  it("invalidates the platform-grants query on success", async () => {
    mockSend.mockResolvedValueOnce({});
    const { wrapper, invalidateSpy } = makeWrapper();

    const { result } = renderHook(() => useDeletePlatformGrant(), { wrapper });
    act(() => {
      result.current.mutate({ grantId: "pg-1" });
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(invalidateSpy).toHaveBeenCalledWith({
      queryKey: ["platform-grants"],
    });
  });

  it("handles error on delete", async () => {
    mockSend.mockRejectedValueOnce(new Error("Not found"));
    const { wrapper } = makeWrapper();

    const { result } = renderHook(() => useDeletePlatformGrant(), { wrapper });
    act(() => {
      result.current.mutate({ grantId: "pg-bad" });
    });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error?.message).toBe("Not found");
  });
});
