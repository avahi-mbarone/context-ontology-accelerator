// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { vi, describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import React from "react";
import {
  ControlPlaneClientProvider,
  useControlPlaneClient,
} from "../../../src/components/ControlPlaneClientProvider";
import { RuntimeConfigContext } from "../../../src/components/RuntimeContext";

vi.mock("../../../src/auth", () => ({
  OIDCProvider: {
    build: () => ({ getIdToken: vi.fn().mockResolvedValue("mock-token") }),
  },
}));

describe("ControlPlaneClientProvider", () => {
  it("throws when useControlPlaneClient is used outside provider", () => {
    const Comp = () => {
      try {
        useControlPlaneClient();
        return <span>no error</span>;
      } catch (e: any) {
        return <span>{e.message}</span>;
      }
    };
    render(<Comp />);
    expect(
      screen.getByText(
        "useControlPlaneClient must be used within ControlPlaneClientProvider",
      ),
    ).toBeInTheDocument();
  });

  it("provides a client when runtime config is available", () => {
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

    const Comp = () => {
      const client = useControlPlaneClient();
      return <span>{client ? "has-client" : "no-client"}</span>;
    };

    render(
      <RuntimeConfigContext.Provider value={runtimeConfig}>
        <ControlPlaneClientProvider>
          <Comp />
        </ControlPlaneClientProvider>
      </RuntimeConfigContext.Provider>,
    );

    expect(screen.getByText("has-client")).toBeInTheDocument();
  });
});
