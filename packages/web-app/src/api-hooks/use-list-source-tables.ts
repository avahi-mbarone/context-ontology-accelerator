// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { useQuery } from "@tanstack/react-query";
import {
  ListSourceTablesCommand,
  ReviewStatus,
} from "@coa/control-plane-client";
import type { TableSummary } from "@coa/control-plane-client";
import { useControlPlaneClient } from "@components/ControlPlaneClientProvider";

export interface ListSourceTablesResult {
  items: TableSummary[];
  /** Total number of assets skipped across all pages due to retrieval/parse failures. */
  skippedAssets: number;
}

/**
 * Fetches all tables for a DATABASE source, auto-paginating through nextToken.
 * Uses maxResults=50 per page (DataZone Search API hard limit).
 */
export function useListSourceTables(
  namespaceId: string,
  sourceId: string,
  reviewStatus?: ReviewStatus,
) {
  const client = useControlPlaneClient();

  return useQuery<ListSourceTablesResult, Error>({
    queryKey: ["sourceTables", namespaceId, sourceId, reviewStatus],
    queryFn: async () => {
      const allItems: TableSummary[] = [];
      let nextToken: string | undefined;
      let totalSkipped = 0;

      do {
        const result = await client.send(
          new ListSourceTablesCommand({
            namespaceId,
            sourceId,
            maxResults: 50,
            ...(reviewStatus && { reviewStatus }),
            ...(nextToken && { nextToken }),
          }),
        );
        allItems.push(...(result.items ?? []));
        totalSkipped += result.skippedAssets ?? 0;
        nextToken = result.nextToken ?? undefined;
      } while (nextToken);

      return { items: allItems, skippedAssets: totalSkipped };
    },
    enabled: !!namespaceId && !!sourceId,
  });
}
