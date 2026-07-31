// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { useQuery } from "@tanstack/react-query";
import { GetIngestStatusCommand } from "@coa/control-plane-client";
// IngestJob is the Smithy-generated type — single source of truth for the
// async ingest-job wire shape (camelCase: jobId, ontologyId, status, …),
// rather than a hand-written interface.
import type { IngestJob } from "@coa/control-plane-client";
import { useControlPlaneClient } from "@components/ControlPlaneClientProvider";

const TERMINAL = new Set(["completed", "failed"]);

/**
 * Poll an async ontology-ingest job until it reaches a terminal state.
 *
 * Step 3 of the async upload flow. The query is enabled only while a jobId is
 * set; ``refetchInterval`` polls every 3 s and returns ``false`` once the job
 * is ``completed`` or ``failed`` so polling stops automatically (no manual
 * setInterval / cleanup, unlike the legacy induction-job poller).
 */
export function useGetIngestStatus(
  namespaceId: string,
  ontologyId: string,
  jobId: string | null,
) {
  const client = useControlPlaneClient();

  return useQuery<IngestJob, Error>({
    queryKey: ["ontologyIngestStatus", namespaceId, ontologyId, jobId],
    queryFn: async () => {
      const out = await client.send(
        new GetIngestStatusCommand({
          namespaceId,
          ontologyId,
          jobId: jobId!,
        }),
      );
      return out.result as IngestJob;
    },
    enabled: !!namespaceId && !!ontologyId && !!jobId,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status && TERMINAL.has(status) ? false : 3000;
    },
  });
}
