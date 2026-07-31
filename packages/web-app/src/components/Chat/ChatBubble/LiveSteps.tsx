// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import React from "react";
import { StatusIndicator } from "@cloudscape-design/components";
import type { TraceStep } from "@app-types";
import { STEP_LABELS, humanizeStepId } from "@components/Chat/step-labels";

function formatStepLabel(stepName: string): string {
  return STEP_LABELS[stepName] ?? humanizeStepId(stepName);
}

export interface LiveStepsProps {
  steps: TraceStep[] | undefined;
}

export const LiveSteps: React.FC<LiveStepsProps> = ({ steps }) => {
  const traceSteps = steps ?? [];
  const currentStep = traceSteps[traceSteps.length - 1];
  const label = currentStep
    ? `Resolving query · ${formatStepLabel(currentStep.step)}`
    : "Resolving query";

  return <StatusIndicator type="loading">{label}</StatusIndicator>;
};
