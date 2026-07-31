// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { vi, describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";
import { LoginPage } from "../../../src/pages/LoginPage";
import { RuntimeConfigContext } from "../../../src/components/RuntimeContext";

const mockAuthenticate = vi.fn();

vi.mock("../../../src/auth", () => ({
  OIDCProvider: {
    build: () => ({ authenticate: mockAuthenticate }),
  },
}));

const runtimeConfig = {
  region: "us-east-1",
  authority: "https://cognito.example.com",
  clientId: "test-client",
  apiEndpoint: "https://api.example.com",
  oidcConfig: {
    authority: "https://cognito.example.com",
    clientId: "test-client",
  },
};

describe("LoginPage", () => {
  it("renders the title and sign-in button", () => {
    render(
      <RuntimeConfigContext.Provider value={runtimeConfig}>
        <LoginPage title="My App" />
      </RuntimeConfigContext.Provider>,
    );

    expect(screen.getByText("My App")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /sign in/i }),
    ).toBeInTheDocument();
  });

  it("calls authenticate on button click", async () => {
    mockAuthenticate.mockResolvedValue(undefined);
    const user = userEvent.setup();

    render(
      <RuntimeConfigContext.Provider value={runtimeConfig}>
        <LoginPage title="My App" />
      </RuntimeConfigContext.Provider>,
    );

    await user.click(screen.getByRole("button", { name: /sign in/i }));
    expect(mockAuthenticate).toHaveBeenCalled();
  });
});
