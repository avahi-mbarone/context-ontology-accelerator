// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import {
  useMutation,
  useQueryClient,
  UseMutationOptions,
} from "@tanstack/react-query";
import {
  RescanSourceCommand,
  ControlPlaneServiceServiceException,
} from "@coa/control-plane-client";
import type { RescanSourceCommandOutput } from "@coa/control-plane-client";
import { useControlPlaneClient } from "@components/ControlPlaneClientProvider";

export function useRescanSource(
  namespaceId: string,
  sourceId: string,
  options?: Omit<
    UseMutationOptions<
      RescanSourceCommandOutput,
      ControlPlaneServiceServiceException,
      void
    >,
    "mutationFn"
  >,
) {
  const client = useControlPlaneClient();
  const queryClient = useQueryClient();

  return useMutation<
    RescanSourceCommandOutput,
    ControlPlaneServiceServiceException,
    void
  >({
    mutationFn: () =>
      client.send(new RescanSourceCommand({ namespaceId, sourceId })),
    onSuccess: (...args) => {
      queryClient.invalidateQueries({
        queryKey: ["source", namespaceId, sourceId],
      });
      options?.onSuccess?.(...args);
    },
    ...options,
  });
}
