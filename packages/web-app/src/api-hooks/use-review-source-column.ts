// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  ReviewSourceColumnCommand,
  type ReviewSourceColumnInput,
  type ReviewSourceColumnOutput,
} from "@coa/control-plane-client";
import { useControlPlaneClient } from "@components/ControlPlaneClientProvider";

export function useReviewSourceColumn(
  namespaceId: string,
  sourceId: string,
  tableId: string,
) {
  const client = useControlPlaneClient();
  const queryClient = useQueryClient();

  return useMutation<
    ReviewSourceColumnOutput,
    Error,
    Pick<ReviewSourceColumnInput, "columnName" | "decision">
  >({
    mutationFn: (input) =>
      client.send(
        new ReviewSourceColumnCommand({
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
      queryClient.invalidateQueries({
        queryKey: ["sourceTable", namespaceId, sourceId, tableId],
      });
    },
  });
}
