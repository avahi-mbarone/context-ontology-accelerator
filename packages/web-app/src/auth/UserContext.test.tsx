// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { vi, describe, it, expect, beforeEach } from "vitest";
import { render, screen, waitFor, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";
import { UserProvider, useUser } from "./UserContext";
import { OIDCProvider } from "./OIDCProvider";

vi.mock("./OIDCProvider", () => ({
  OIDCProvider: {
    build: vi.fn(),
  },
}));

const mockProvider = {
  getUser: vi.fn(),
  getIdToken: vi.fn(),
  signOut: vi.fn(),
};

const oidcConfig = { authority: "https://mock", clientId: "mock-id" };

const TestComponent = () => {
  const { user, logout } = useUser();
  return (
    <div>
      <button onClick={logout}>Logout</button>
      {user && <span data-testid="user-id">{user.userid}</span>}
      {user && <span data-testid="user-groups">{user.groups.join(",")}</span>}
    </div>
  );
};

describe("UserContext", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(OIDCProvider.build).mockReturnValue(
      mockProvider as unknown as OIDCProvider,
    );
  });

  describe("useUser", () => {
    it("returns undefined user when outside provider", () => {
      const Comp = () => {
        const { user } = useUser();
        return <span data-testid="val">{user ? "yes" : "no"}</span>;
      };
      render(<Comp />);
      expect(screen.getByTestId("val")).toHaveTextContent("no");
    });
  });

  describe("UserProvider", () => {
    it("loads user from OIDC provider", async () => {
      mockProvider.getUser.mockResolvedValue({ profile: { sub: "user_sub" } });
      mockProvider.getIdToken.mockResolvedValue("mock-token");

      await act(async () => {
        render(
          <UserProvider oidcConfig={oidcConfig}>
            <TestComponent />
          </UserProvider>,
        );
      });

      await waitFor(() => {
        expect(screen.getByTestId("user-id")).toHaveTextContent("user_sub");
      });
    });

    it("extracts groups from cognito:groups claim", async () => {
      mockProvider.getUser.mockResolvedValue({
        profile: { sub: "u1", "cognito:groups": ["admin", "viewer"] },
      });
      mockProvider.getIdToken.mockResolvedValue("tok");

      await act(async () => {
        render(
          <UserProvider oidcConfig={oidcConfig}>
            <TestComponent />
          </UserProvider>,
        );
      });

      await waitFor(() => {
        expect(screen.getByTestId("user-groups")).toHaveTextContent(
          "admin,viewer",
        );
      });
    });

    it("extracts groups from groups claim", async () => {
      mockProvider.getUser.mockResolvedValue({
        profile: { sub: "u1", groups: ["editor"] },
      });
      mockProvider.getIdToken.mockResolvedValue("tok");

      await act(async () => {
        render(
          <UserProvider oidcConfig={oidcConfig}>
            <TestComponent />
          </UserProvider>,
        );
      });

      await waitFor(() => {
        expect(screen.getByTestId("user-groups")).toHaveTextContent("editor");
      });
    });

    it("returns empty groups when no group claims present", async () => {
      mockProvider.getUser.mockResolvedValue({
        profile: { sub: "u1" },
      });
      mockProvider.getIdToken.mockResolvedValue("tok");

      await act(async () => {
        render(
          <UserProvider oidcConfig={oidcConfig}>
            <TestComponent />
          </UserProvider>,
        );
      });

      await waitFor(() => {
        expect(screen.getByTestId("user-groups")).toHaveTextContent("");
      });
    });

    it("does not set user when getUser returns null", async () => {
      mockProvider.getUser.mockResolvedValue(null);

      await act(async () => {
        render(
          <UserProvider oidcConfig={oidcConfig}>
            <TestComponent />
          </UserProvider>,
        );
      });

      expect(screen.queryByTestId("user-id")).not.toBeInTheDocument();
      expect(mockProvider.getIdToken).not.toHaveBeenCalled();
    });

    it("does not set user when profile.sub is missing", async () => {
      mockProvider.getUser.mockResolvedValue({ profile: {} });
      mockProvider.getIdToken.mockResolvedValue("tok");

      await act(async () => {
        render(
          <UserProvider oidcConfig={oidcConfig}>
            <TestComponent />
          </UserProvider>,
        );
      });

      expect(screen.queryByTestId("user-id")).not.toBeInTheDocument();
    });

    it("handles errors gracefully", async () => {
      const consoleSpy = vi
        .spyOn(console, "error")
        .mockImplementation(() => {});
      mockProvider.getUser.mockRejectedValue(new Error("fail"));

      await act(async () => {
        render(
          <UserProvider oidcConfig={oidcConfig}>
            <TestComponent />
          </UserProvider>,
        );
      });

      expect(consoleSpy).toHaveBeenCalled();
      expect(screen.queryByTestId("user-id")).not.toBeInTheDocument();
      consoleSpy.mockRestore();
    });

    it("logout calls provider.signOut", async () => {
      mockProvider.getUser.mockResolvedValue({ profile: { sub: "u1" } });
      mockProvider.getIdToken.mockResolvedValue("tok");
      mockProvider.signOut.mockResolvedValue(undefined);

      const user = userEvent.setup();

      await act(async () => {
        render(
          <UserProvider oidcConfig={oidcConfig}>
            <TestComponent />
          </UserProvider>,
        );
      });

      await user.click(screen.getByText("Logout"));
      expect(mockProvider.signOut).toHaveBeenCalled();
    });
  });
});
