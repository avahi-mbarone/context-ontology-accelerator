// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { useQuery } from "@tanstack/react-query";
import { GetNamespaceCommand } from "@coa/control-plane-client";
import type { GetNamespaceOutput } from "@coa/control-plane-client";
import { useControlPlaneClient } from "@components/ControlPlaneClientProvider";

/**
 * Fetches a single namespace by ID.
 * Disabled when `namespaceId` is empty to prevent unnecessary requests.
 */
export function useGetNamespace(namespaceId: string) {
  const client = useControlPlaneClient();

  return useQuery<GetNamespaceOutput, Error>({
    queryKey: ["namespace", namespaceId],
    queryFn: async () => {
      return client.send(new GetNamespaceCommand({ namespaceId }));
    },
    enabled: !!namespaceId,
  });
}
