// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import React from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { HomePage } from "./HomePage";

const navigate = vi.fn();

vi.mock("react-router-dom", async (importOriginal) => {
  const actual = await importOriginal<typeof import("react-router-dom")>();
  return { ...actual, useNavigate: () => navigate };
});

vi.mock("../auth", () => ({
  useUser: () => ({
    user: {
      userid: "u1",
      name: "Ada Lovelace",
      email: "ada@example.com",
      groups: [],
    },
    logout: vi.fn(),
  }),
}));

const renderHome = () =>
  render(
    <MemoryRouter>
      <HomePage />
    </MemoryRouter>,
  );

describe("HomePage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders the Context Ontology Accelerator hero and tagline", () => {
    renderHome();
    expect(
      screen.getByText("Context Ontology Accelerator"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("The governed context layer for enterprise AI."),
    ).toBeInTheDocument();
  });

  it("greets the signed-in user by name", () => {
    renderHome();
    expect(screen.getByText(/Welcome, Ada Lovelace\./)).toBeInTheDocument();
  });

  it("renders the Scan / Ontology / Serve overview", () => {
    renderHome();
    expect(screen.getByText("Scan")).toBeInTheDocument();
    expect(screen.getByText("Ontology")).toBeInTheDocument();
    expect(screen.getByText("Serve")).toBeInTheDocument();
  });

  it("routes to namespace creation from Get started", async () => {
    renderHome();
    await userEvent.click(screen.getByRole("button", { name: /get started/i }));
    expect(navigate).toHaveBeenCalledWith("/namespaces/create");
  });

  it("routes to the namespace list from View namespaces", async () => {
    renderHome();
    await userEvent.click(
      screen.getByRole("button", { name: /view namespaces/i }),
    );
    expect(navigate).toHaveBeenCalledWith("/namespaces");
  });
});
