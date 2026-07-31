// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  UpdateSourceTableKeysCommand,
  type UpdateSourceTableKeysInput,
  type UpdateSourceTableKeysOutput,
} from "@coa/control-plane-client";
import { useControlPlaneClient } from "@components/ControlPlaneClientProvider";

export function useUpdateSourceTableKeys(
  namespaceId: string,
  sourceId: string,
  tableId: string,
) {
  const client = useControlPlaneClient();
  const queryClient = useQueryClient();

  return useMutation<
    UpdateSourceTableKeysOutput,
    Error,
    Pick<UpdateSourceTableKeysInput, "primaryKey" | "foreignKeys">
  >({
    mutationFn: (input) =>
      client.send(
        new UpdateSourceTableKeysCommand({
          namespaceId,
          sourceId,
          tableId,
          ...input,
        }),
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ["sourceTable", namespaceId, sourceId, tableId],
      });
    },
  });
}
