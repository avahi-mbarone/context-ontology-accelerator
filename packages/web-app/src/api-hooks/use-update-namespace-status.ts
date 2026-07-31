// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  UpdateNamespaceStatusCommand,
  ControlPlaneServiceServiceException,
} from "@coa/control-plane-client";
import type {
  UpdateNamespaceStatusInput,
  UpdateNamespaceStatusOutput,
} from "@coa/control-plane-client";
import { useControlPlaneClient } from "@components/ControlPlaneClientProvider";

/**
 * Mutation hook to transition a namespace between lifecycle states
 * (e.g. ACTIVE → ARCHIVED → DELETED). Invalidates the namespace list on success.
 */
export function useUpdateNamespaceStatus() {
  const client = useControlPlaneClient();
  const queryClient = useQueryClient();

  return useMutation<
    UpdateNamespaceStatusOutput,
    ControlPlaneServiceServiceException,
    UpdateNamespaceStatusInput
  >({
    mutationFn: async (input) => {
      return client.send(new UpdateNamespaceStatusCommand(input));
    },
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({
        queryKey: ["namespace", variables.namespaceId],
      });
      queryClient.invalidateQueries({ queryKey: ["namespaces"] });
    },
  });
}
