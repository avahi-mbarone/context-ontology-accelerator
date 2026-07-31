// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { useQuery } from "@tanstack/react-query";
import {
  GetOntologyOverviewCommand,
  type OntologyOverview,
} from "@coa/control-plane-client";
import { useControlPlaneClient } from "@components/ControlPlaneClientProvider";

export type { OntologyOverview };
export type {
  OntologyClassSummary,
  OntologyPropertySummary,
} from "@coa/control-plane-client";

export function useOntologyOverview(
  namespaceId: string | undefined,
  ontologyId: string | undefined,
) {
  const client = useControlPlaneClient();
  return useQuery<OntologyOverview, Error>({
    queryKey: ["ontology-overview", namespaceId, ontologyId],
    queryFn: () =>
      client.send(
        new GetOntologyOverviewCommand({
          namespaceId: namespaceId!,
          ontologyId: ontologyId!,
        }),
      ),
    enabled: !!namespaceId && !!ontologyId,
  });
}
