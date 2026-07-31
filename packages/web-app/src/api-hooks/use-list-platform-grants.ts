// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { useInfiniteQuery } from "@tanstack/react-query";
import { ListPlatformGrantsCommand } from "@coa/control-plane-client";
import type {
  ListPlatformGrantsOutput,
  PlatformGrantSummary,
} from "@coa/control-plane-client";
import { useControlPlaneClient } from "@components/ControlPlaneClientProvider";

export type { PlatformGrantSummary };

/**
 * Fetches all PLATFORM-scoped grants (principal→platform-role bindings),
 * paginated. These apply across every namespace (e.g. platform-admin,
 * platform-viewer).
 */
export function useListPlatformGrants() {
  const client = useControlPlaneClient();

  return useInfiniteQuery<ListPlatformGrantsOutput, Error>({
    queryKey: ["platform-grants"],
    queryFn: async ({ pageParam }) => {
      return client.send(
        new ListPlatformGrantsCommand({
          nextToken: pageParam as string | undefined,
        }),
      );
    },
    getNextPageParam: (lastPage) => lastPage.nextToken,
    initialPageParam: undefined as string | undefined,
  });
}
