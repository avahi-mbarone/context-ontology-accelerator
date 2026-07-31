// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import {
  useMutation,
  useQueryClient,
  UseMutationOptions,
} from "@tanstack/react-query";
import {
  CreateSourceCommand,
  ControlPlaneServiceServiceException,
} from "@coa/control-plane-client";
import type {
  CreateSourceCommandInput,
  CreateSourceCommandOutput,
} from "@coa/control-plane-client";
import { useControlPlaneClient } from "@components/ControlPlaneClientProvider";

export function useCreateSource(
  options?: Omit<
    UseMutationOptions<
      CreateSourceCommandOutput,
      ControlPlaneServiceServiceException,
      CreateSourceCommandInput
    >,
    "mutationFn"
  >,
) {
  const client = useControlPlaneClient();
  const queryClient = useQueryClient();

  return useMutation<
    CreateSourceCommandOutput,
    ControlPlaneServiceServiceException,
    CreateSourceCommandInput
  >({
    mutationFn: (input) => client.send(new CreateSourceCommand(input)),
    onSuccess: (data, input, ctx) => {
      queryClient.invalidateQueries({ queryKey: ["sources"] });
      // The source counter lives on the namespace record (sourceCount), so
      // the namespace list and detail pages need to re-fetch after a
      // successful create.
      queryClient.invalidateQueries({ queryKey: ["namespaces"] });
      if (input.namespaceId) {
        queryClient.invalidateQueries({
          queryKey: ["namespace", input.namespaceId],
        });
      }
      options?.onSuccess?.(data, input, ctx);
    },
    ...options,
  });
}
