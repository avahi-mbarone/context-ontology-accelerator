// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import React from "react";
import { render, screen, act, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { NamespacePermissions } from "./NamespacePermissions";

const deleteGrantMock = vi.hoisted(() => ({
  mutate: vi.fn(),
  mutateAsync: vi.fn().mockResolvedValue({}),
  isPending: false,
}));

vi.mock("../api-hooks/use-get-namespace", () => ({
  useGetNamespace: () => ({
    data: {
      namespace: {
        namespaceId: "ns-1",
        name: "test-ns",
        displayName: "Test Namespace",
      },
    },
    isLoading: false,
    error: null,
  }),
}));

vi.mock("../api-hooks/use-list-namespace-roles", () => ({
  useListNamespaceRoles: () => ({
    data: {
      roles: [
        {
          roleId: "namespace-owner",
          name: "Namespace Owner",
          description: "Full control within a namespace",
          scope: "NAMESPACE",
          isBuiltIn: true,
        },
      ],
    },
    isLoading: false,
    error: null,
  }),
}));

vi.mock("../api-hooks/use-list-namespace-grants", () => ({
  useListNamespaceGrants: () => ({
    data: {
      pages: [
        {
          grants: [
            {
              grantId: "g1",
              namespaceId: "ns-1",
              principalType: "User",
              principalId: "alice@example.com",
              role: "namespace-owner",
              grantedBy: "admin@example.com",
              grantedAt: "2026-01-01T00:00:00Z",
              tableAllowlist: ["orders"],
              allowedMetrics: ["revenue_total"],
              columnDenylist: { customers: ["ssn"] },
            },
            {
              grantId: "g2",
              namespaceId: "ns-1",
              principalType: "User",
              principalId: "bob@example.com",
              role: "namespace-owner",
              grantedBy: "admin@example.com",
              grantedAt: "2026-01-02T00:00:00Z",
            },
          ],
        },
      ],
    },
    isLoading: false,
    error: null,
    fetchNextPage: vi.fn(),
    hasNextPage: false,
    isFetchingNextPage: false,
  }),
}));

vi.mock("../api-hooks/use-create-grant", () => ({
  useCreateGrant: () => ({ mutate: vi.fn(), isPending: false }),
}));

vi.mock("../api-hooks/use-delete-grant", () => ({
  useDeleteGrant: () => deleteGrantMock,
}));

vi.mock("@coa/control-plane-client", () => ({
  PrincipalType: { USER: "User", GROUP: "Group", AGENT: "Agent" },
}));

const wrapper = ({ children }: { children: React.ReactNode }) => (
  <QueryClientProvider client={new QueryClient()}>
    <MemoryRouter initialEntries={["/namespaces/ns-1/permissions"]}>
      <Routes>
        <Route path="/namespaces/:namespaceId/permissions" element={children} />
      </Routes>
    </MemoryRouter>
  </QueryClientProvider>
);

describe("NamespacePermissions", () => {
  beforeEach(() => {
    deleteGrantMock.mutateAsync.mockClear();
    deleteGrantMock.mutateAsync.mockResolvedValue({});
  });

  it("renders the permissions header with the namespace name", () => {
    render(<NamespacePermissions />, { wrapper });
    expect(
      screen.getByRole("heading", { name: /Test Namespace — Permissions/i }),
    ).toBeInTheDocument();
  });

  it("renders Roles and Members tabs", () => {
    render(<NamespacePermissions />, { wrapper });
    expect(screen.getByRole("tab", { name: /Roles/i })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /Members/i })).toBeInTheDocument();
  });

  it("defaults to the Members tab", () => {
    render(<NamespacePermissions />, { wrapper });
    // Members content is shown without switching tabs.
    expect(screen.getByText("alice@example.com")).toBeInTheDocument();
  });

  it("shows the namespace role on the Roles tab", async () => {
    render(<NamespacePermissions />, { wrapper });
    await act(async () => {
      screen.getByRole("tab", { name: /Roles/i }).click();
    });
    expect(screen.getByText("Namespace Owner")).toBeInTheDocument();
  });

  it("shows grants and a Grant access button on the Members tab", async () => {
    render(<NamespacePermissions />, { wrapper });
    const membersTab = screen.getByRole("tab", { name: /Members/i });
    await act(async () => {
      membersTab.click();
    });
    expect(screen.getByText("alice@example.com")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /grant access/i }),
    ).toBeInTheDocument();
  });

  it("renders grant restrictions as chips and unrestricted grants as muted state labels", async () => {
    render(<NamespacePermissions />, { wrapper });
    await act(async () => {
      screen.getByRole("tab", { name: /Members/i }).click();
    });
    // alice's restricted grant → values render as individual badges/chips.
    expect(screen.getByText("orders")).toBeInTheDocument(); // allowed table
    expect(screen.getByText("revenue_total")).toBeInTheDocument(); // allowed metric
    expect(screen.getByText("customers")).toBeInTheDocument(); // denied-columns table group
    expect(screen.getByText("ssn")).toBeInTheDocument(); // denied column
    // bob's unrestricted grant → muted "All" (tables + metrics) and "None".
    expect(screen.getAllByText("All").length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText("None")).toBeInTheDocument();
  });

  it("revokes every selected member and clears the selection after success", async () => {
    render(<NamespacePermissions />, { wrapper });
    await act(async () => {
      screen.getByRole("tab", { name: /Members/i }).click();
    });

    // Select both member rows (skip the header select-all at index 0).
    const rowCheckboxes = screen.getAllByRole("checkbox").slice(1);
    await act(async () => {
      rowCheckboxes.forEach((cb) => cb.click());
    });

    const inDialog = (b: HTMLElement) => !!b.closest('[role="dialog"]');
    const revokeButtons = () =>
      screen.getAllByRole("button", { name: /^revoke$/i }) as HTMLElement[];
    const headerRevoke = () =>
      revokeButtons().find((b) => !inDialog(b)) as HTMLElement;
    const modalRevoke = () =>
      revokeButtons().find((b) => inDialog(b)) as HTMLElement;

    // Selecting rows enables the table's Revoke action.
    await waitFor(() => {
      expect(headerRevoke()).toBeEnabled();
    });
    await act(async () => {
      headerRevoke().click();
    });

    // Confirm inside the dialog — triggers the revoke of all selected grants.
    await act(async () => {
      modalRevoke().click();
    });

    // Both grants are revoked via mutateAsync (the single-observer bug would
    // have left one promise unresolved).
    await waitFor(() => {
      expect(deleteGrantMock.mutateAsync).toHaveBeenCalledTimes(2);
    });
    // The .then ran: selection cleared (so the action is disabled again),
    // which is the same state update that closes the modal.
    await waitFor(() => {
      expect(headerRevoke()).toBeDisabled();
    });
  });
});
