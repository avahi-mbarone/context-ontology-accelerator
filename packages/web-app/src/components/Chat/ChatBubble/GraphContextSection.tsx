// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Graph context section showing entity relationships from the knowledge graph.
 */
import React from "react";
import { Box } from "@cloudscape-design/components";
import type { GraphContextItem } from "@app-types";

export interface GraphContextSectionProps {
  context: GraphContextItem;
}

export const GraphContextSection: React.FC<GraphContextSectionProps> = ({
  context,
}) => {
  if (!context.label && !context.relationships?.length) return null;

  return (
    <div style={{ borderTop: "1px solid #e9ebed", paddingTop: "8px" }}>
      <Box variant="span" fontSize="body-s" fontWeight="bold">
        Graph context
      </Box>
      {context.label && (
        <div style={{ marginTop: "4px" }}>
          <Box variant="span" fontSize="body-s">
            {context.label}
            {context.type && (
              <Box variant="span" color="text-body-secondary">
                {" "}
                ({context.type})
              </Box>
            )}
          </Box>
        </div>
      )}
      {context.relationships && context.relationships.length > 0 && (
        <div style={{ marginTop: "4px" }}>
          {context.relationships.map((rel, i) => (
            <Box key={i} variant="span" fontSize="body-s" display="block">
              → {rel.predicate}: {rel.targetLabel ?? rel.target}
            </Box>
          ))}
        </div>
      )}
    </div>
  );
};
