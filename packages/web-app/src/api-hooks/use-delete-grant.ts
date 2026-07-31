// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  DeleteGrantCommand,
  ControlPlaneServiceServiceException,
} from "@coa/control-plane-client";
import type {
  DeleteGrantInput,
  DeleteGrantOutput,
} from "@coa/control-plane-client";
import { useControlPlaneClient } from "@components/ControlPlaneClientProvider";

/**
 * Mutation hook to revoke a grant (remove a principal's role on a namespace).
 * Invalidates the namespace grants list on success.
 */
export function useDeleteGrant() {
  const client = useControlPlaneClient();
  const queryClient = useQueryClient();

  return useMutation<
    DeleteGrantOutput,
    ControlPlaneServiceServiceException,
    DeleteGrantInput
  >({
    mutationFn: async (input) => {
      return client.send(new DeleteGrantCommand(input));
    },
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({
        queryKey: ["namespace-grants", variables.namespaceId],
      });
    },
  });
}
