// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { vi, describe, it, expect, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import React from "react";
import { MemoryRouter } from "react-router-dom";
import { AuthenticatePage } from "./AuthenticatePage";
import {
  RuntimeConfigContext,
  RuntimeContext,
} from "../components/RuntimeContext";
import { OIDCProvider } from "../auth";

vi.mock("../auth", () => ({
  OIDCProvider: { build: vi.fn() },
}));

const mockProvider = {
  authenticationCallback: vi.fn(),
};

const runtimeContext: RuntimeContext = {
  region: "us-east-1",
  authority: "https://mock",
  clientId: "mock-id",
  oidcConfig: { authority: "https://mock", clientId: "mock-id" },
};

function renderWithContext(searchParams = "") {
  return render(
    <RuntimeConfigContext.Provider value={runtimeContext}>
      <MemoryRouter initialEntries={[`/authenticate${searchParams}`]}>
        <AuthenticatePage title="Test App" />
      </MemoryRouter>
    </RuntimeConfigContext.Provider>,
  );
}

describe("AuthenticatePage", () => {
  let replaceSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(OIDCProvider.build).mockReturnValue(
      mockProvider as unknown as OIDCProvider,
    );
    replaceSpy = vi
      .spyOn(window.location, "replace")
      .mockImplementation(() => {});
  });

  it("renders the title", () => {
    mockProvider.authenticationCallback.mockReturnValue(new Promise(() => {}));
    renderWithContext("?code=123&state=456");
    expect(screen.getAllByText("Test App").length).toBeGreaterThan(0);
  });

  it("shows processing message while authenticating", () => {
    mockProvider.authenticationCallback.mockReturnValue(new Promise(() => {}));
    renderWithContext("?code=123&state=456");
    expect(
      screen.getByText(/Authenticating with the configured Identity Provider/i),
    ).toBeInTheDocument();
  });

  it("redirects to / on success", async () => {
    mockProvider.authenticationCallback.mockResolvedValue({ id_token: "tok" });
    renderWithContext("?code=123&state=456");

    await waitFor(() => {
      expect(replaceSpy).toHaveBeenCalledWith("/");
    });
  });

  it("redirects to /login when callback returns undefined", async () => {
    mockProvider.authenticationCallback.mockResolvedValue(undefined);
    renderWithContext("?code=123&state=456");

    await waitFor(() => {
      expect(replaceSpy).toHaveBeenCalledWith("/login");
    });
  });

  it("redirects to /login when callback throws", async () => {
    mockProvider.authenticationCallback.mockRejectedValue(new Error("fail"));
    renderWithContext("?code=123&state=456");

    await waitFor(() => {
      expect(replaceSpy).toHaveBeenCalledWith("/login");
    });
  });

  it("redirects to /login when code or state params are missing", async () => {
    renderWithContext("");

    await waitFor(() => {
      expect(replaceSpy).toHaveBeenCalledWith("/login");
    });
  });
});
