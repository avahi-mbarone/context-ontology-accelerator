// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { useQuery } from "@tanstack/react-query";
import { ListPrincipalGrantsCommand } from "@coa/control-plane-client";
import type { ListPrincipalGrantsOutput } from "@coa/control-plane-client";
import { useControlPlaneClient } from "../components/ControlPlaneClientProvider";

const SELF_PRINCIPAL = "me";

export function useListPrincipalGrants() {
  const client = useControlPlaneClient();

  return useQuery<ListPrincipalGrantsOutput, Error>({
    queryKey: ["principals", SELF_PRINCIPAL, "grants"],
    queryFn: async () => {
      return client.send(
        new ListPrincipalGrantsCommand({ principalId: SELF_PRINCIPAL }),
      );
    },
  });
}
