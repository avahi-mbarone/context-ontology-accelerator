// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { UpdateSourceMetadataCommand } from "@coa/control-plane-client";
import type {
  UpdateSourceMetadataInput,
  UpdateSourceMetadataOutput,
} from "@coa/control-plane-client";
import { useControlPlaneClient } from "@components/ControlPlaneClientProvider";

export function useUpdateSourceMetadata(namespaceId: string, sourceId: string) {
  const client = useControlPlaneClient();
  const queryClient = useQueryClient();

  return useMutation<
    UpdateSourceMetadataOutput,
    Error,
    Omit<UpdateSourceMetadataInput, "namespaceId" | "sourceId">
  >({
    mutationFn: (input) =>
      client.send(
        new UpdateSourceMetadataCommand({
          namespaceId,
          sourceId,
          ...input,
        }),
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ["source", namespaceId, sourceId],
      });
      // The source-list rows show name and configuration summary, so the
      // edit needs to refresh those too.
      queryClient.invalidateQueries({ queryKey: ["sources", namespaceId] });
    },
  });
}
