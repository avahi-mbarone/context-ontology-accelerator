// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, it, expect, vi, beforeEach } from "vitest";
import React from "react";
import { useListNamespaceRoles } from "./use-list-namespace-roles";

const mockSend = vi.fn();

beforeEach(() => {
  mockSend.mockReset();
});

vi.mock("@components/ControlPlaneClientProvider", () => ({
  useControlPlaneClient: () => ({ send: mockSend }),
}));

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return ({ children }: { children: React.ReactNode }) =>
    React.createElement(QueryClientProvider, { client: queryClient }, children);
}

describe("useListNamespaceRoles", () => {
  it("fetches roles for a namespace", async () => {
    const roles = [{ roleId: "owner", name: "Owner" }];
    mockSend.mockResolvedValueOnce({ roles });

    const { result } = renderHook(() => useListNamespaceRoles("ns-1"), {
      wrapper: createWrapper(),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.roles).toEqual(roles);
    expect(mockSend).toHaveBeenCalledWith(
      expect.objectContaining({ input: { namespaceId: "ns-1" } }),
    );
  });

  it("is disabled when namespaceId is empty", () => {
    const { result } = renderHook(() => useListNamespaceRoles(""), {
      wrapper: createWrapper(),
    });

    expect(result.current.fetchStatus).toBe("idle");
    expect(mockSend).not.toHaveBeenCalled();
  });

  it("handles errors", async () => {
    mockSend.mockRejectedValueOnce(new Error("Network error"));

    const { result } = renderHook(() => useListNamespaceRoles("ns-1"), {
      wrapper: createWrapper(),
    });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error?.message).toBe("Network error");
  });
});
