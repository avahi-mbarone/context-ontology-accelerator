// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Evidence panel — shows cited sources and graph context for Tier 3 responses.
 */
import React from "react";
import { ExpandableSection, SpaceBetween } from "@cloudscape-design/components";
import type { GraphContextItem, SupportingContentItem } from "@app-types";
import { EvidenceItem } from "./EvidenceItem";
import { GraphContextSection } from "./GraphContextSection";

export interface EvidencePanelProps {
  supportingContent?: SupportingContentItem[];
  graphContext?: GraphContextItem;
}

/**
 * Collapsible evidence panel showing source attribution with relevance scores.
 * Only renders when supportingContent is present and non-empty.
 */
export const EvidencePanel: React.FC<EvidencePanelProps> = ({
  supportingContent,
  graphContext,
}) => {
  if (!supportingContent || supportingContent.length === 0) return null;

  const sorted = [...supportingContent].sort(
    (a, b) => (b.relevanceScore ?? 0) - (a.relevanceScore ?? 0),
  );

  return (
    <ExpandableSection
      headerText={`${sorted.length} source${sorted.length !== 1 ? "s" : ""} cited`}
      variant="footer"
      defaultExpanded={false}
    >
      <SpaceBetween size="s">
        {sorted.map((item, index) => (
          <EvidenceItem key={item.chunkId ?? `evidence-${index}`} item={item} />
        ))}
        {graphContext && <GraphContextSection context={graphContext} />}
      </SpaceBetween>
    </ExpandableSection>
  );
};
