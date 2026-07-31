// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { useInfiniteQuery } from "@tanstack/react-query";
import { ListNamespaceGrantsCommand } from "@coa/control-plane-client";
import type {
  ListNamespaceGrantsOutput,
  GrantSummary,
} from "@coa/control-plane-client";
import { useControlPlaneClient } from "@components/ControlPlaneClientProvider";

export type { GrantSummary };

/**
 * Fetches all grants (principal→role mappings) for a namespace, paginated.
 * Disabled when `namespaceId` is empty.
 */
export function useListNamespaceGrants(namespaceId: string) {
  const client = useControlPlaneClient();

  return useInfiniteQuery<ListNamespaceGrantsOutput, Error>({
    queryKey: ["namespace-grants", namespaceId],
    queryFn: async ({ pageParam }) => {
      return client.send(
        new ListNamespaceGrantsCommand({
          namespaceId,
          nextToken: pageParam as string | undefined,
        }),
      );
    },
    getNextPageParam: (lastPage) => lastPage.nextToken,
    initialPageParam: undefined as string | undefined,
    enabled: !!namespaceId,
  });
}
