// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  DeletePlatformGrantCommand,
  ControlPlaneServiceServiceException,
} from "@coa/control-plane-client";
import type {
  DeletePlatformGrantInput,
  DeletePlatformGrantOutput,
} from "@coa/control-plane-client";
import { useControlPlaneClient } from "@components/ControlPlaneClientProvider";

/**
 * Mutation hook to revoke a PLATFORM-scoped grant. Invalidates the platform
 * grants list on success.
 */
export function useDeletePlatformGrant() {
  const client = useControlPlaneClient();
  const queryClient = useQueryClient();

  return useMutation<
    DeletePlatformGrantOutput,
    ControlPlaneServiceServiceException,
    DeletePlatformGrantInput
  >({
    mutationFn: async (input) => {
      return client.send(new DeletePlatformGrantCommand(input));
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["platform-grants"] });
    },
  });
}
