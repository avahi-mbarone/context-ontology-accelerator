// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  CreatePlatformGrantCommand,
  ControlPlaneServiceServiceException,
} from "@coa/control-plane-client";
import type {
  CreatePlatformGrantInput,
  CreatePlatformGrantOutput,
} from "@coa/control-plane-client";
import { useControlPlaneClient } from "@components/ControlPlaneClientProvider";

/**
 * Mutation hook to grant a principal a PLATFORM-scoped role
 * (e.g. platform-admin, platform-viewer). Invalidates the platform grants
 * list on success.
 */
export function useCreatePlatformGrant() {
  const client = useControlPlaneClient();
  const queryClient = useQueryClient();

  return useMutation<
    CreatePlatformGrantOutput,
    ControlPlaneServiceServiceException,
    CreatePlatformGrantInput
  >({
    mutationFn: async (input) => {
      return client.send(new CreatePlatformGrantCommand(input));
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["platform-grants"] });
    },
  });
}
