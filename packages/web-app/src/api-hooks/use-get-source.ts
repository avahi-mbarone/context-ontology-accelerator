// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { useQuery } from "@tanstack/react-query";
import { GetSourceCommand } from "@coa/control-plane-client";
import type { GetSourceCommandOutput } from "@coa/control-plane-client";
import { useControlPlaneClient } from "@components/ControlPlaneClientProvider";

const ACTIVE_STATUSES = new Set([
  "REGISTERED",
  "SCANNING",
  "ENRICHING",
  "APPROVING",
  "REJECTING",
  "DELETING",
]);
const POLL_INTERVAL_MS = 10_000;

export function useGetSource(namespaceId: string, sourceId: string) {
  const client = useControlPlaneClient();

  return useQuery<GetSourceCommandOutput, Error>({
    queryKey: ["source", namespaceId, sourceId],
    queryFn: () => client.send(new GetSourceCommand({ namespaceId, sourceId })),
    refetchInterval: (query) => {
      const status = query.state.data?.body?.status ?? "";
      return ACTIVE_STATUSES.has(status) ? POLL_INTERVAL_MS : false;
    },
    enabled: !!namespaceId && !!sourceId,
  });
}
