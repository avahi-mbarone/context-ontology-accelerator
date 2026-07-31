// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  CreateGrantCommand,
  ControlPlaneServiceServiceException,
} from "@coa/control-plane-client";
import type {
  CreateGrantInput,
  CreateGrantOutput,
} from "@coa/control-plane-client";
import { useControlPlaneClient } from "@components/ControlPlaneClientProvider";

/**
 * Mutation hook to grant a principal (user/group) a role on a namespace.
 * Invalidates the namespace grants list on success.
 */
export function useCreateGrant() {
  const client = useControlPlaneClient();
  const queryClient = useQueryClient();

  return useMutation<
    CreateGrantOutput,
    ControlPlaneServiceServiceException,
    CreateGrantInput
  >({
    mutationFn: async (input) => {
      return client.send(new CreateGrantCommand(input));
    },
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({
        queryKey: ["namespace-grants", variables.namespaceId],
      });
    },
  });
}
