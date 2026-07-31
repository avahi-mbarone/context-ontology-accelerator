// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { vi, describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import React from "react";
import {
  ApiClientProvider,
  useApiClient,
  ApiError,
} from "../../../src/components/ApiClientProvider";
import { RuntimeConfigContext } from "../../../src/components/RuntimeContext";

vi.mock("../../../src/auth", () => ({
  OIDCProvider: {
    build: () => ({ getIdToken: vi.fn().mockResolvedValue("mock-token") }),
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

describe("ApiClientProvider", () => {
  it("throws when useApiClient is used outside provider", () => {
    const Comp = () => {
      try {
        useApiClient();
        return <span>no error</span>;
      } catch (e: any) {
        return <span>{e.message}</span>;
      }
    };
    render(<Comp />);
    expect(
      screen.getByText("useApiClient must be used within ApiClientProvider"),
    ).toBeInTheDocument();
  });

  it("provides a client when runtime config is available", () => {
    const Comp = () => {
      const client = useApiClient();
      return <span>{client ? "has-client" : "no-client"}</span>;
    };

    render(
      <RuntimeConfigContext.Provider value={runtimeConfig}>
        <ApiClientProvider>
          <Comp />
        </ApiClientProvider>
      </RuntimeConfigContext.Provider>,
    );

    expect(screen.getByText("has-client")).toBeInTheDocument();
  });

  it("ApiError has correct properties", () => {
    const err = new ApiError(403, "FORBIDDEN", "Access denied");
    expect(err.status).toBe(403);
    expect(err.code).toBe("FORBIDDEN");
    expect(err.message).toBe("Access denied");
    expect(err.name).toBe("ApiError");
  });
});
