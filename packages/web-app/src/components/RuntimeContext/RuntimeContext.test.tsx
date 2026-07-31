// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { vi, describe, it, expect, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import React, { useContext } from "react";
import { RuntimeContextProvider, RuntimeConfigContext } from "./index";

const validConfig = {
  region: "us-east-1",
  authority: "https://mock-authority",
  clientId: "mock-client-id",
};

const Consumer = () => {
  const ctx = useContext(RuntimeConfigContext);
  if (!ctx) return <span>no context</span>;
  return <span data-testid="region">{ctx.region}</span>;
};

describe("RuntimeContextProvider", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("loads config and provides context", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(validConfig),
    } as Response);

    render(
      <RuntimeContextProvider>
        <Consumer />
      </RuntimeContextProvider>,
    );

    await waitFor(() => {
      expect(screen.getByTestId("region")).toHaveTextContent("us-east-1");
    });
  });

  it("shows error when required fields are missing", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ region: "us-east-1" }),
    } as Response);

    render(
      <RuntimeContextProvider>
        <Consumer />
      </RuntimeContextProvider>,
    );

    await waitFor(() => {
      expect(
        screen.getByText(/must have region, authority, and clientId/i),
      ).toBeInTheDocument();
    });
  });

  it("shows error on HTTP failure", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: false,
      status: 404,
    } as Response);

    render(
      <RuntimeContextProvider>
        <Consumer />
      </RuntimeContextProvider>,
    );

    await waitFor(() => {
      expect(
        screen.getByText(/No runtime-config.json detected/i),
      ).toBeInTheDocument();
    });
  });

  it("shows error on network failure", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("network"));

    render(
      <RuntimeContextProvider>
        <Consumer />
      </RuntimeContextProvider>,
    );

    await waitFor(() => {
      expect(
        screen.getByText(/No runtime-config.json detected/i),
      ).toBeInTheDocument();
    });
  });
});
