// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { useInfiniteQuery } from "@tanstack/react-query";
import { ListNamespacesCommand } from "@coa/control-plane-client";
import type { ListNamespacesOutput } from "@coa/control-plane-client";
import { useControlPlaneClient } from "@components/ControlPlaneClientProvider";

export function useListNamespaces() {
  const client = useControlPlaneClient();

  return useInfiniteQuery<ListNamespacesOutput, Error>({
    queryKey: ["namespaces"],
    queryFn: async ({ pageParam }) => {
      return client.send(
        new ListNamespacesCommand({
          nextToken: pageParam as string | undefined,
        }),
      );
    },
    getNextPageParam: (lastPage) => lastPage.nextToken,
    initialPageParam: undefined as string | undefined,
  });
}
