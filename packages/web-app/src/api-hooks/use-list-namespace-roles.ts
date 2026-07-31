// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { useQuery } from "@tanstack/react-query";
import { ListNamespaceRolesCommand } from "@coa/control-plane-client";
import type { ListNamespaceRolesOutput } from "@coa/control-plane-client";
import { useControlPlaneClient } from "@components/ControlPlaneClientProvider";

/**
 * Fetches the available roles for a namespace (e.g. owner, editor, viewer).
 * Disabled when `namespaceId` is empty.
 */
export function useListNamespaceRoles(namespaceId: string) {
  const client = useControlPlaneClient();

  return useQuery<ListNamespaceRolesOutput, Error>({
    queryKey: ["namespace-roles", namespaceId],
    queryFn: async () => {
      return client.send(new ListNamespaceRolesCommand({ namespaceId }));
    },
    enabled: !!namespaceId,
  });
}
