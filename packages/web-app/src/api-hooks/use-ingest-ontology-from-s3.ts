// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { useMutation, UseMutationOptions } from "@tanstack/react-query";
import {
  IngestOntologyFromS3Command,
  ControlPlaneServiceServiceException,
} from "@coa/control-plane-client";
import type {
  IngestOntologyFromS3Input,
  IngestOntologyFromS3Output,
} from "@coa/control-plane-client";
import { useControlPlaneClient } from "@components/ControlPlaneClientProvider";

/**
 * Start async ingestion of an ontology file already uploaded to S3.
 *
 * Step 2 of the async upload flow. Returns 202 immediately with a job id in
 * the {@link IngestOntologyFromS3Output} document; poll completion via
 * {@link useGetIngestStatus}. Format is auto-detected from the filename when
 * not supplied.
 */
export function useIngestOntologyFromS3(
  namespaceId: string,
  options?: Omit<
    UseMutationOptions<
      IngestOntologyFromS3Output,
      ControlPlaneServiceServiceException,
      Omit<IngestOntologyFromS3Input, "namespaceId">
    >,
    "mutationFn"
  >,
) {
  const client = useControlPlaneClient();

  return useMutation<
    IngestOntologyFromS3Output,
    ControlPlaneServiceServiceException,
    Omit<IngestOntologyFromS3Input, "namespaceId">
  >({
    mutationFn: async (input) => {
      return client.send(
        new IngestOntologyFromS3Command({ ...input, namespaceId }),
      );
    },
    ...options,
  });
}
