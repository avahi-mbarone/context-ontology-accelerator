// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  UpdateNamespaceCommand,
  ControlPlaneServiceServiceException,
} from "@coa/control-plane-client";
import type {
  UpdateNamespaceInput,
  UpdateNamespaceOutput,
} from "@coa/control-plane-client";
import { useControlPlaneClient } from "@components/ControlPlaneClientProvider";

/**
 * Mutation hook to update namespace metadata (displayName, description).
 * Invalidates both the individual namespace cache and the list cache on success.
 */
export function useUpdateNamespace() {
  const client = useControlPlaneClient();
  const queryClient = useQueryClient();

  return useMutation<
    UpdateNamespaceOutput,
    ControlPlaneServiceServiceException,
    UpdateNamespaceInput
  >({
    mutationFn: async (input) => {
      return client.send(new UpdateNamespaceCommand(input));
    },
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({
        queryKey: ["namespace", variables.namespaceId],
      });
      queryClient.invalidateQueries({ queryKey: ["namespaces"] });
    },
  });
}
