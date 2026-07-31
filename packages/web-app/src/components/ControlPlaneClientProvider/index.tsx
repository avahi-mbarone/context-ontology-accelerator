// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import React, {
  createContext,
  PropsWithChildren,
  useContext,
  useMemo,
} from "react";
import { ControlPlaneServiceClient } from "@coa/control-plane-client";
import { RuntimeConfigContext } from "../RuntimeContext";
import { OIDCProvider } from "@auth";

const ControlPlaneClientContext = createContext<
  ControlPlaneServiceClient | undefined
>(undefined);

export const useControlPlaneClient = (): ControlPlaneServiceClient => {
  const ctx = useContext(ControlPlaneClientContext);
  if (!ctx)
    throw new Error(
      "useControlPlaneClient must be used within ControlPlaneClientProvider",
    );
  return ctx;
};

export const ControlPlaneClientProvider: React.FC<PropsWithChildren> = ({
  children,
}) => {
  const runtimeContext = useContext(RuntimeConfigContext);
  const apiEndpoint = runtimeContext?.apiEndpoint;
  const oidcConfig = runtimeContext?.oidcConfig;

  const client = useMemo(() => {
    if (!apiEndpoint || !oidcConfig) return undefined;
    const provider = OIDCProvider.build(oidcConfig);

    return new ControlPlaneServiceClient({
      endpoint: apiEndpoint.replace(/\/$/, ""),
      token: async () => {
        const token = await provider.getIdToken();
        if (!token) throw new Error("Failed to retrieve authentication token");
        return { token };
      },
    });
  }, [apiEndpoint, oidcConfig]);

  return (
    <ControlPlaneClientContext.Provider value={client}>
      {children}
    </ControlPlaneClientContext.Provider>
  );
};
