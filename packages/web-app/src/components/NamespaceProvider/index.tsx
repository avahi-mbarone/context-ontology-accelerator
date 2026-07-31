// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useListNamespaces } from "@api-hooks";
import type { NamespaceSummary } from "@api-hooks";

interface NamespaceContextValue {
  current: NamespaceSummary | undefined;
  namespaceId: string;
  namespaces: NamespaceSummary[];
  setNamespace: (namespaceId: string) => void;
  isLoading: boolean;
}

const NamespaceContext = createContext<NamespaceContextValue | undefined>(
  undefined,
);

/** Extract the namespaceId segment from paths like /namespaces/:id/... */
function namespaceIdFromPath(pathname: string): string | undefined {
  const match = pathname.match(/^\/namespaces\/([^/]+)/);
  return match?.[1];
}

export const NamespaceProvider: React.FC<React.PropsWithChildren> = ({
  children,
}) => {
  const navigate = useNavigate();
  const location = useLocation();
  const { data, isLoading } = useListNamespaces();
  const [selectedId, setSelectedId] = useState<string | undefined>();

  const namespaces = useMemo(() => {
    return data?.pages.flatMap((p) => p.namespaces ?? []) ?? [];
  }, [data]);

  // Sync selectedId from the URL so direct navigation keeps the switcher in sync
  useEffect(() => {
    const idFromUrl = namespaceIdFromPath(location.pathname);
    if (idFromUrl && idFromUrl !== selectedId) {
      // Only update if the URL id matches a known namespace (or namespaces not loaded yet)
      const known = namespaces.find((n) => n.namespaceId === idFromUrl);
      if (known || namespaces.length === 0) {
        setSelectedId(idFromUrl);
      }
    }
  }, [location.pathname, namespaces, selectedId]);

  const current = useMemo(
    () => namespaces.find((n) => n.namespaceId === selectedId) ?? namespaces[0],
    [namespaces, selectedId],
  );

  const namespaceId = current?.namespaceId ?? "";

  const setNamespace = useCallback(
    (id: string) => {
      setSelectedId(id);
      // Don't navigate away from the Playground page
      if (!location.pathname.includes("/playground")) {
        navigate(`/namespaces/${id}/sources`);
      }
    },
    [navigate, location.pathname],
  );

  const value = useMemo<NamespaceContextValue>(
    () => ({ current, namespaceId, namespaces, setNamespace, isLoading }),
    [current, namespaceId, namespaces, setNamespace, isLoading],
  );

  return (
    <NamespaceContext.Provider value={value}>
      {children}
    </NamespaceContext.Provider>
  );
};

export function useCurrentNamespace(): NamespaceContextValue {
  const ctx = useContext(NamespaceContext);
  if (!ctx)
    throw new Error(
      "useCurrentNamespace must be used inside NamespaceProvider",
    );
  return ctx;
}
