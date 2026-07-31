// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import { useListNamespaces } from "../../../src/api-hooks/use-list-namespaces";

const mockSend = vi.fn();
vi.mock("../../../src/components/ControlPlaneClientProvider", () => ({
  useControlPlaneClient: () => ({ send: mockSend }),
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

describe("useListNamespaces", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("returns namespaces on success", async () => {
    mockSend.mockResolvedValueOnce({
      namespaces: [{ namespaceId: "ns-1", name: "test" }],
      nextToken: undefined,
    });

    const { result } = renderHook(() => useListNamespaces(), { wrapper });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.pages[0].namespaces).toHaveLength(1);
    expect(result.current.data?.pages[0].namespaces?.[0].name).toBe("test");
  });

  it("reports hasNextPage when nextToken is present", async () => {
    mockSend.mockResolvedValueOnce({
      namespaces: [{ namespaceId: "ns-1", name: "a" }],
      nextToken: "tok",
    });

    const { result } = renderHook(() => useListNamespaces(), { wrapper });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.hasNextPage).toBe(true);
  });

  it("sets error when query fails", async () => {
    mockSend.mockRejectedValueOnce(new Error("Network error"));

    const { result } = renderHook(() => useListNamespaces(), { wrapper });

    await waitFor(() => expect(result.current.error).not.toBeNull());
    expect(result.current.error?.message).toBe("Network error");
  });
});
