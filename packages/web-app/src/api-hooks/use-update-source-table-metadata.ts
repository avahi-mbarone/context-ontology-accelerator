// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  UpdateSourceTableMetadataCommand,
  type UpdateSourceTableMetadataInput,
  type UpdateSourceTableMetadataOutput,
} from "@coa/control-plane-client";
import { useControlPlaneClient } from "@components/ControlPlaneClientProvider";

export function useUpdateSourceTableMetadata(
  namespaceId: string,
  sourceId: string,
  tableId: string,
) {
  const client = useControlPlaneClient();
  const queryClient = useQueryClient();

  return useMutation<
    UpdateSourceTableMetadataOutput,
    Error,
    Pick<UpdateSourceTableMetadataInput, "overrides">
  >({
    mutationFn: (input) =>
      client.send(
        new UpdateSourceTableMetadataCommand({
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
