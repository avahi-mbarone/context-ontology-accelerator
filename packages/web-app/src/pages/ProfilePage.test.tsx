// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import React from "react";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { ProfilePage } from "./ProfilePage";

type GrantsQuery = {
  data?: { grants: unknown[] };
  isLoading: boolean;
  error: Error | null;
};

let grantsQuery: GrantsQuery;

vi.mock("../api-hooks/index", () => ({
  useListPrincipalGrants: () => ({
    ...grantsQuery,
    refetch: vi.fn(),
    isFetching: false,
  }),
  useListPlatformRoles: () => ({ data: { roles: [] } }),
}));

vi.mock("../auth", () => ({
  useUser: () => ({
    user: {
      userid: "u1",
      name: "Ada Lovelace",
      email: "ada@example.com",
      groups: [],
    },
  }),
}));

vi.mock("../components/NamespaceProvider", () => ({
  useCurrentNamespace: () => ({ namespaces: [] }),
}));

vi.mock("../components/ControlPlaneClientProvider", () => ({
  useControlPlaneClient: () => ({ send: vi.fn() }),
}));

const renderProfile = () =>
  render(
    <MemoryRouter>
      <ProfilePage />
    </MemoryRouter>,
  );

describe("ProfilePage roles tab", () => {
  beforeEach(() => {
    grantsQuery = { data: { grants: [] }, isLoading: false, error: null };
  });

  it("shows the no-roles empty state when the grants query succeeds with none", () => {
    renderProfile();
    expect(screen.getByText("No roles assigned.")).toBeInTheDocument();
    expect(
      screen.queryByText("Failed to load your roles"),
    ).not.toBeInTheDocument();
  });

  it("surfaces a failed grants query instead of claiming no roles", () => {
    grantsQuery = {
      data: undefined,
      isLoading: false,
      error: new Error("Internal server error"),
    };
    renderProfile();
    expect(screen.getByText("Failed to load your roles")).toBeInTheDocument();
    expect(screen.getByText("Internal server error")).toBeInTheDocument();
    expect(screen.getByText("Roles could not be loaded.")).toBeInTheDocument();
    expect(screen.queryByText("No roles assigned.")).not.toBeInTheDocument();
  });
});
