// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  ReviewSourceTableCommand,
  type ReviewSourceTableInput,
  type ReviewSourceTableOutput,
} from "@coa/control-plane-client";
import { useControlPlaneClient } from "@components/ControlPlaneClientProvider";

export function useReviewSourceTable(
  namespaceId: string,
  sourceId: string,
  tableId: string,
) {
  const client = useControlPlaneClient();
  const queryClient = useQueryClient();

  return useMutation<
    ReviewSourceTableOutput,
    Error,
    Pick<ReviewSourceTableInput, "decision">
  >({
    mutationFn: (input) =>
      client.send(
        new ReviewSourceTableCommand({
          namespaceId,
          sourceId,
          tableId,
          ...input,
        }),
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ["sourceTables", namespaceId, sourceId],
      });
      queryClient.invalidateQueries({
        queryKey: ["source", namespaceId, sourceId],
      });
      // Single-table detail page caches under ``sourceTable`` (canonical
      // unified key — see ``use-get-source-table.ts``).
      queryClient.invalidateQueries({
        queryKey: ["sourceTable", namespaceId, sourceId, tableId],
      });
    },
  });
}
