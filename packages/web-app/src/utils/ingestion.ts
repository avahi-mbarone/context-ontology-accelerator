// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import type { StatusIndicatorProps } from "@cloudscape-design/components/status-indicator";

export function ingestionStatusType(
  status: string | undefined,
): StatusIndicatorProps["type"] {
  switch (status) {
    case "completed":
      return "success";
    case "failed":
    case "delete_failed":
      return "error";
    case "ingesting":
    case "deleting":
      return "in-progress";
    case "pending":
      return "pending";
    default:
      return "stopped";
  }
}

export function isActiveStatus(status: string | undefined): boolean {
  return (
    status === "pending" || status === "ingesting" || status === "deleting"
  );
}
