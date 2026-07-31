// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { RejectSourceCommand } from "@coa/control-plane-client";
import type {
  RejectSourceInput,
  RejectSourceOutput,
} from "@coa/control-plane-client";
import { useControlPlaneClient } from "@components/ControlPlaneClientProvider";

/**
 * Trigger an asynchronous bulk reject for a DATABASE source.
 *
 * Returns 202 immediately and transitions the source's status to REJECTING.
 * On success the worker returns the source to PENDING_REVIEW (rejection
 * does not approve the source overall — the steward can re-review).
 * On failure the source's status becomes REJECTION_FAILED; clients may retry.
 */
export function useRejectSource(namespaceId: string, sourceId: string) {
  const client = useControlPlaneClient();
  const queryClient = useQueryClient();

  return useMutation<
    RejectSourceOutput,
    Error,
    Omit<RejectSourceInput, "namespaceId" | "sourceId">
  >({
    mutationFn: () =>
      client.send(new RejectSourceCommand({ namespaceId, sourceId })),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ["source", namespaceId, sourceId],
      });
      queryClient.invalidateQueries({
        queryKey: ["sourceTables", namespaceId, sourceId],
      });
      queryClient.invalidateQueries({ queryKey: ["sources", namespaceId] });
    },
  });
}
