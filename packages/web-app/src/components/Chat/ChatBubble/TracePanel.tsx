// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Processing trace panel — shows step-by-step pipeline trace with timing.
 */
import React, { useState } from "react";
import {
  Badge,
  Box,
  ExpandableSection,
  SpaceBetween,
  Spinner,
  StatusIndicator,
} from "@cloudscape-design/components";
import type { TraceStep } from "@app-types";
import { formatStepDetail } from "@components/Chat/RationalePanel/format-step-detail";
import {
  HIDDEN_UNLESS_DENIED,
  PARALLEL_RETRIEVE_GROUP,
  RETRIEVE_CHILD_STEPS,
  humanizeStepId,
  mapTraceStatus,
} from "@components/Chat/step-labels";
import "../chat.css";

export interface TracePanelProps {
  /** Trace steps to render. */
  steps: TraceStep[];
  /** Whether more steps may still arrive (live streaming mode). */
  isLive: boolean;
}

function shouldShowStep(step: TraceStep): boolean {
  if (RETRIEVE_CHILD_STEPS.has(step.step)) {
    return false;
  }
  if (HIDDEN_UNLESS_DENIED.has(step.step)) {
    return step.status === "denied" || step.status === "error";
  }
  return true;
}

/**
 * Expandable trace panel showing each pipeline step with status + timing.
 */
export const TracePanel: React.FC<TracePanelProps> = ({ steps, isLive }) => {
  if (steps.length === 0 && !isLive) return null;

  const visibleSteps = steps.filter(shouldShowStep);

  return (
    <ExpandableSection
      headerText={`Processing trace (${visibleSteps.length} step${visibleSteps.length !== 1 ? "s" : ""})`}
      variant="footer"
      defaultExpanded={false}
    >
      <SpaceBetween size="xs">
        {visibleSteps.map((step, index) => {
          const children =
            step.step === PARALLEL_RETRIEVE_GROUP
              ? steps.filter((s) => s.parallelGroup === PARALLEL_RETRIEVE_GROUP)
              : [];
          return (
            <TraceStepRow
              key={`${step.step}-${index}`}
              step={step}
              childSteps={children}
            />
          );
        })}
        {isLive && (
          <Box padding={{ top: "xs" }}>
            <Spinner size="normal" />
          </Box>
        )}
      </SpaceBetween>
    </ExpandableSection>
  );
};

function TraceStepRow({
  step,
  childSteps = [],
}: {
  step: TraceStep;
  childSteps?: TraceStep[];
}) {
  const [expanded, setExpanded] = useState(false);
  const hasDetail = Boolean(step.detail || step.toolUsed);
  const durationLabel =
    step.wallMs != null ? `${step.wallMs}ms wall` : `${step.durationMs}ms`;

  return (
    <div>
      <div
        className="trace-step-row"
        style={{ cursor: hasDetail ? "pointer" : "default" }}
        onClick={() => hasDetail && setExpanded(!expanded)}
        onKeyDown={(e) => {
          if (hasDetail && (e.key === "Enter" || e.key === " ")) {
            e.preventDefault();
            setExpanded(!expanded);
          }
        }}
        role={hasDetail ? "button" : undefined}
        tabIndex={hasDetail ? 0 : undefined}
        aria-expanded={hasDetail ? expanded : undefined}
        aria-label={`Trace step: ${humanizeStepId(step.step)}`}
      >
        <StatusIndicator type={mapTraceStatus(step.status)}>
          {humanizeStepId(step.step)}
        </StatusIndicator>
        <Badge color="blue">{durationLabel}</Badge>
        {hasDetail && (
          <Box variant="span" fontSize="body-s" color="text-body-secondary">
            {expanded ? "▾" : "▸"}
          </Box>
        )}
      </div>
      {expanded && hasDetail && (
        <div className="trace-step-detail">
          {step.toolUsed && (
            <Box variant="span" fontSize="body-s" color="text-body-secondary">
              Tool: {step.toolUsed}
            </Box>
          )}
          {step.detail && (
            <pre className="trace-step-code">
              {formatStepDetail(step.step, step.detail)}
            </pre>
          )}
        </div>
      )}
      {/* Render parallel children indented */}
      {childSteps.length > 0 && (
        <div className="trace-step-children">
          <SpaceBetween size="xxs">
            {childSteps.map((child, i) => (
              <div key={`${child.step}-${i}`} className="trace-step-row">
                <Box
                  variant="span"
                  fontSize="body-s"
                  color="text-body-secondary"
                >
                  ├
                </Box>
                <StatusIndicator type={mapTraceStatus(child.status)}>
                  {humanizeStepId(child.step)}
                </StatusIndicator>
                <Badge color="grey">{child.durationMs}ms</Badge>
                {child.toolUsed && (
                  <Box
                    variant="span"
                    fontSize="body-s"
                    color="text-body-secondary"
                  >
                    {child.toolUsed}
                  </Box>
                )}
              </div>
            ))}
          </SpaceBetween>
        </div>
      )}
    </div>
  );
}
