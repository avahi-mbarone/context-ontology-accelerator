// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import { useListPlatformRoles } from "../../../src/api-hooks/use-list-platform-roles";

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

describe("useListPlatformRoles", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("returns platform roles on success", async () => {
    mockSend.mockResolvedValueOnce({
      roles: [
        {
          roleId: "platform-admin",
          name: "Platform Admin",
          scope: "PLATFORM",
          isBuiltIn: true,
        },
      ],
    });

    const { result } = renderHook(() => useListPlatformRoles(), { wrapper });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.roles).toHaveLength(1);
    expect(result.current.data?.roles?.[0].name).toBe("Platform Admin");
  });

  it("handles error state", async () => {
    mockSend.mockRejectedValueOnce(new Error("Internal error"));

    const { result } = renderHook(() => useListPlatformRoles(), { wrapper });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error?.message).toBe("Internal error");
  });
});
