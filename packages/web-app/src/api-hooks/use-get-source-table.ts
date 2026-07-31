// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { useQuery } from "@tanstack/react-query";
import { GetSourceTableCommand } from "@coa/control-plane-client";
import type { GetSourceTableOutput } from "@coa/control-plane-client";
import { useControlPlaneClient } from "@components/ControlPlaneClientProvider";

/**
 * Fetch full table metadata (columns, business metadata, primary/foreign
 * keys) for a single table in a unified DATABASE source.
 *
 * Replaces the legacy `useGetDataSourceTable` hook so the entire web-app
 * shares one canonical query key for single-table reads. Mutations that
 * change a table's review status or metadata invalidate this key by name.
 */
export function useGetSourceTable(
  namespaceId: string,
  sourceId: string,
  tableId: string,
) {
  const client = useControlPlaneClient();

  return useQuery<GetSourceTableOutput, Error>({
    queryKey: ["sourceTable", namespaceId, sourceId, tableId],
    queryFn: () =>
      client.send(
        new GetSourceTableCommand({ namespaceId, sourceId, tableId }),
      ),
    enabled: !!namespaceId && !!sourceId && !!tableId,
  });
}
