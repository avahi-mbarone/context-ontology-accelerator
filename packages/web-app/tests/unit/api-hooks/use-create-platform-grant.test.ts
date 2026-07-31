// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor, act } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import { useCreatePlatformGrant } from "../../../src/api-hooks/use-create-platform-grant";

const mockSend = vi.fn();
vi.mock("../../../src/components/ControlPlaneClientProvider", () => ({
  useControlPlaneClient: () => ({ send: mockSend }),
}));

vi.mock("@coa/control-plane-client", () => ({
  CreatePlatformGrantCommand: class {
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

describe("useCreatePlatformGrant", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("sends CreatePlatformGrantCommand and returns the result", async () => {
    mockSend.mockResolvedValueOnce({
      grant: { grantId: "pg-new", role: "platform-admin" },
    });
    const { wrapper } = makeWrapper();

    const { result } = renderHook(() => useCreatePlatformGrant(), { wrapper });

    act(() => {
      result.current.mutate({
        body: {
          principalType: "User",
          principalId: "admin@example.com",
          role: "platform-admin",
        },
      });
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(mockSend).toHaveBeenCalledTimes(1);
    const command = mockSend.mock.calls[0][0];
    expect(command.input.body.role).toBe("platform-admin");
  });

  it("invalidates the platform-grants query on success", async () => {
    mockSend.mockResolvedValueOnce({ grant: { grantId: "pg-new" } });
    const { wrapper, invalidateSpy } = makeWrapper();

    const { result } = renderHook(() => useCreatePlatformGrant(), { wrapper });
    act(() => {
      result.current.mutate({
        body: {
          principalType: "User",
          principalId: "a@b.com",
          role: "platform-viewer",
        },
      });
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(invalidateSpy).toHaveBeenCalledWith({
      queryKey: ["platform-grants"],
    });
  });

  it("handles error on create", async () => {
    mockSend.mockRejectedValueOnce(new Error("Access denied"));
    const { wrapper } = makeWrapper();

    const { result } = renderHook(() => useCreatePlatformGrant(), { wrapper });
    act(() => {
      result.current.mutate({
        body: { principalType: "User", principalId: "a@b.com", role: "x" },
      });
    });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error?.message).toBe("Access denied");
  });
});
