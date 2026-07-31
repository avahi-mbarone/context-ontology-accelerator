// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import React, {
  createContext,
  PropsWithChildren,
  useContext,
  useEffect,
  useState,
} from "react";
import { OIDCProvider, OidcConfig } from "./OIDCProvider";

export interface UserInfo {
  userid: string;
  name: string;
  email: string;
  groups: string[];
}

interface UserContextValue {
  user?: UserInfo;
  error?: string;
  logout: () => Promise<void>;
}

const UserContext = createContext<UserContextValue>({
  user: undefined,
  logout: async () => {},
});

/**
 * Returns the current authenticated user, an optional error, and a `logout` function.
 * Must be used within a {@link UserProvider} tree.
 */
export const useUser = () => useContext(UserContext);

interface UserProviderProps extends PropsWithChildren {
  oidcConfig: OidcConfig;
}

function extractString(
  profile: Record<string, unknown>,
  ...keys: string[]
): string {
  for (const key of keys) {
    const val = profile[key];
    if (Array.isArray(val) && val.length) return val.join(", ");
    if (typeof val === "string" && val) return val;
  }
  return "";
}

function extractList(
  profile: Record<string, unknown>,
  ...keys: string[]
): string[] {
  for (const key of keys) {
    const val = profile[key];
    if (Array.isArray(val) && val.length) return val.map(String);
    if (typeof val === "string" && val)
      return val.split(",").map((s) => s.trim());
  }
  return [];
}

export const UserProvider: React.FC<UserProviderProps> = ({
  oidcConfig,
  children,
}) => {
  const [user, setUser] = useState<UserInfo | undefined>(undefined);
  const [error, setError] = useState<string | undefined>(undefined);

  useEffect(() => {
    const load = async () => {
      try {
        const provider = OIDCProvider.build(oidcConfig);
        const oidcUser = await provider.getUser();
        if (oidcUser && oidcUser.profile.sub) {
          const token = await provider.getIdToken();
          if (token) {
            const profile = oidcUser.profile as unknown as Record<
              string,
              unknown
            >;
            setUser({
              userid: oidcUser.profile.sub,
              name: extractString(
                profile,
                "name",
                "given_name",
                "preferred_username",
              ),
              email: oidcUser.profile.email ?? "",
              groups: extractList(
                profile,
                "cognito:groups",
                "groups",
                "custom:groups",
                "custom:team",
                "team",
                "department",
              ),
            });
          }
        }
      } catch (e) {
        const msg =
          e instanceof Error
            ? e.message
            : "Authentication failed. Please sign in again.";
        console.error("UserContext: failed to load user", e);
        setError(msg);
      }
    };
    void load();
  }, [oidcConfig]);

  const logout = async () => {
    const provider = OIDCProvider.build(oidcConfig);
    await provider.signOut();
  };

  return (
    <UserContext.Provider value={{ user, error, logout }}>
      {children}
    </UserContext.Provider>
  );
};
