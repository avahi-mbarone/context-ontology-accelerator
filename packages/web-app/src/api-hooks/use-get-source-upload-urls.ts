// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { useMutation, UseMutationOptions } from "@tanstack/react-query";
import {
  GetSourceUploadUrlsCommand,
  ControlPlaneServiceServiceException,
} from "@coa/control-plane-client";
import type {
  GetSourceUploadUrlsInput,
  GetSourceUploadUrlsOutput,
} from "@coa/control-plane-client";
import { useControlPlaneClient } from "@components/ControlPlaneClientProvider";

export function useGetSourceUploadUrls(
  namespaceId: string,
  options?: Omit<
    UseMutationOptions<
      GetSourceUploadUrlsOutput,
      ControlPlaneServiceServiceException,
      Omit<GetSourceUploadUrlsInput, "namespaceId">
    >,
    "mutationFn"
  >,
) {
  const client = useControlPlaneClient();

  return useMutation<
    GetSourceUploadUrlsOutput,
    ControlPlaneServiceServiceException,
    Omit<GetSourceUploadUrlsInput, "namespaceId">
  >({
    mutationFn: async (input) => {
      return client.send(
        new GetSourceUploadUrlsCommand({ ...input, namespaceId }),
      );
    },
    ...options,
  });
}
