// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  UpdateSourceColumnMetadataCommand,
  type UpdateSourceColumnMetadataInput,
  type UpdateSourceColumnMetadataOutput,
} from "@coa/control-plane-client";
import { useControlPlaneClient } from "@components/ControlPlaneClientProvider";

export function useUpdateSourceColumnMetadata(
  namespaceId: string,
  sourceId: string,
  tableId: string,
) {
  const client = useControlPlaneClient();
  const queryClient = useQueryClient();

  return useMutation<
    UpdateSourceColumnMetadataOutput,
    Error,
    Pick<UpdateSourceColumnMetadataInput, "columnName" | "overrides">
  >({
    mutationFn: (input) =>
      client.send(
        new UpdateSourceColumnMetadataCommand({
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
        queryKey: ["sourceTable", namespaceId, sourceId, tableId],
      });
    },
  });
}
