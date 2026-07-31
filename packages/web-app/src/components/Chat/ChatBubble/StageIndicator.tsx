// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import React from "react";
import { Box, Spinner } from "@cloudscape-design/components";

export interface StageIndicatorProps {
  /** Current stage description from stage_start event. */
  stage: string | undefined;
}

/**
 * Dynamic loading indicator that shows the current resolution stage.
 * Displays "Thinking..." by default, replaced with actual stage text
 * when a stage_start event arrives.
 */
export const StageIndicator: React.FC<StageIndicatorProps> = ({ stage }) => {
  const displayText = stage ?? "Thinking...";

  return (
    <Box>
      <span
        style={{ display: "inline-flex", alignItems: "center", gap: "8px" }}
      >
        <Spinner size="normal" />
        <Box variant="span" color="text-body-secondary" fontSize="body-s">
          {displayText}
        </Box>
      </span>
    </Box>
  );
};
