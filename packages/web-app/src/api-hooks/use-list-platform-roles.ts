// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { useQuery } from "@tanstack/react-query";
import { ListPlatformRolesCommand } from "@coa/control-plane-client";
import type { ListPlatformRolesOutput } from "@coa/control-plane-client";
import { useControlPlaneClient } from "../components/ControlPlaneClientProvider";

export function useListPlatformRoles() {
  const client = useControlPlaneClient();

  return useQuery<ListPlatformRolesOutput, Error>({
    queryKey: ["roles"],
    queryFn: async () => {
      return client.send(new ListPlatformRolesCommand({}));
    },
  });
}
