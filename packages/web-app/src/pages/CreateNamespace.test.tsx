// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import React from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, it, expect, vi } from "vitest";
import { CreateNamespace } from "./CreateNamespace";

vi.mock("../api-hooks", () => ({
  useCreateNamespace: () => ({
    mutate: vi.fn(),
    isPending: false,
    error: null,
  }),
}));

vi.mock("../auth", () => ({
  useUser: () => ({ user: { userid: "user-123", email: "test@example.com" } }),
}));

vi.mock("@coa/control-plane-client", () => ({
  AccessDeniedError: class AccessDeniedError extends Error {
    constructor() {
      super("Access denied");
      this.name = "AccessDeniedError";
    }
  },
}));

const wrapper = ({ children }: { children: React.ReactNode }) => (
  <QueryClientProvider client={new QueryClient()}>
    <MemoryRouter>{children}</MemoryRouter>
  </QueryClientProvider>
);

describe("CreateNamespace", () => {
  it("renders the form header", () => {
    render(<CreateNamespace />, { wrapper });
    expect(
      screen.getByRole("heading", { name: /create namespace/i }),
    ).toBeInTheDocument();
  });

  it("renders name and description fields", () => {
    render(<CreateNamespace />, { wrapper });
    expect(screen.getByText("Namespace name")).toBeInTheDocument();
    expect(screen.getByText(/Description/)).toBeInTheDocument();
  });

  it("shows validation error for empty name on submit", async () => {
    const user = userEvent.setup();
    render(<CreateNamespace />, { wrapper });
    await user.click(screen.getByRole("button", { name: /create namespace/i }));
    expect(screen.getByText("Namespace name is required.")).toBeInTheDocument();
  });

  it("derives machine-friendly name from display name", async () => {
    const user = userEvent.setup();
    render(<CreateNamespace />, { wrapper });
    const input = screen.getByPlaceholderText("e.g., Insurance Prod");
    await user.type(input, "My Namespace");
    expect(screen.getByText(/my-namespace/)).toBeInTheDocument();
  });

  it("collapses consecutive spaces into single hyphen", async () => {
    const user = userEvent.setup();
    render(<CreateNamespace />, { wrapper });
    const input = screen.getByPlaceholderText("e.g., Insurance Prod");
    await user.type(input, "Test  Name");
    expect(screen.getByText(/test-name/)).toBeInTheDocument();
  });

  it("strips special characters from machine name", async () => {
    const user = userEvent.setup();
    render(<CreateNamespace />, { wrapper });
    const input = screen.getByPlaceholderText("e.g., Insurance Prod");
    await user.type(input, "Hello! World@2024");
    expect(screen.getByText(/hello-world2024/)).toBeInTheDocument();
  });

  it("shows validation error for name starting with number", async () => {
    const user = userEvent.setup();
    render(<CreateNamespace />, { wrapper });
    const input = screen.getByPlaceholderText("e.g., Insurance Prod");
    await user.type(input, "123 Test");
    await user.click(screen.getByRole("button", { name: /create namespace/i }));
    expect(
      screen.getByText(/must start with a lowercase letter/),
    ).toBeInTheDocument();
  });
});
