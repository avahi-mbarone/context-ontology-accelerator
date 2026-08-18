// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import * as cdk from "aws-cdk-lib";
import { Construct } from "constructs";
import { SCLStack } from "../../constructs/scl-stack";

/**
 * Service stack: Metrics collection, dashboards, and observability
 * resources for the SemanticContext platform.
 */
export class MetricStack extends SCLStack {
  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    // TODO: Define CloudWatch dashboards, custom metrics, alarms
  }
}
