// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { useQuery } from "@tanstack/react-query";
import {
  ListOntologiesCommand,
  type OntologyRecord,
} from "@coa/control-plane-client";
import { useControlPlaneClient } from "@components/ControlPlaneClientProvider";

export type { OntologyRecord };

export function useListOntologies(namespaceId: string | undefined) {
  const client = useControlPlaneClient();
  return useQuery<OntologyRecord[], Error>({
    queryKey: ["ontologies", namespaceId],
    queryFn: async () => {
      const out = await client.send(
        new ListOntologiesCommand({ namespaceId: namespaceId! }),
      );
      return (out.ontologies ?? []) as OntologyRecord[];
    },
    enabled: !!namespaceId,
  });
}
