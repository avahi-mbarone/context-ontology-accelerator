// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { useMutation, UseMutationOptions } from "@tanstack/react-query";
import {
  GetOntologyUploadUrlCommand,
  ControlPlaneServiceServiceException,
} from "@coa/control-plane-client";
import type {
  GetOntologyUploadUrlInput,
  GetOntologyUploadUrlOutput,
} from "@coa/control-plane-client";
import { useControlPlaneClient } from "@components/ControlPlaneClientProvider";

/**
 * Request a presigned S3 PUT URL for a custom ontology file upload.
 *
 * Step 1 of the async upload flow: presigned URL → client PUTs the file to
 * S3 → {@link useIngestOntologyFromS3} kicks off async ingestion. Bypasses the
 * API Gateway 10 MB / 29 s limits that the legacy inline upload hit.
 */
export function useGetOntologyUploadUrl(
  namespaceId: string,
  options?: Omit<
    UseMutationOptions<
      GetOntologyUploadUrlOutput,
      ControlPlaneServiceServiceException,
      Omit<GetOntologyUploadUrlInput, "namespaceId">
    >,
    "mutationFn"
  >,
) {
  const client = useControlPlaneClient();

  return useMutation<
    GetOntologyUploadUrlOutput,
    ControlPlaneServiceServiceException,
    Omit<GetOntologyUploadUrlInput, "namespaceId">
  >({
    mutationFn: async (input) => {
      return client.send(
        new GetOntologyUploadUrlCommand({ ...input, namespaceId }),
      );
    },
    ...options,
  });
}
