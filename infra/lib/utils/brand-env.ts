// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { IAspect } from "aws-cdk-lib";
import * as ecs from "aws-cdk-lib/aws-ecs";
import * as lambda from "aws-cdk-lib/aws-lambda";
import { IConstruct } from "constructs";

import { resolveContext } from "../context";

/**
 * Data-plane brand tokens for the runtime.
 *
 * These are static by design (see the BRAND block in
 * libs/ts-shared/src/constants.ts) and the Python defaults in
 * libs/common/constants.py already match them, so injection is not what makes
 * them agree. What it buys is:
 *
 *  1. The documented CDK context overrides `graph_base_uri` and
 *     `event_source_prefix` actually reach the runtime. They were resolved in
 *     `resolveContext` but never passed to any compute, so setting either had no
 *     effect on the services that consume them.
 *  2. The runtime stops inferring graph IRIs from RESOURCE_PREFIX, which CDK
 *     injects as `{prefix}-{env}-`. That inference produced
 *     `http://scl-dev.amazon.com/vocab/scl-dev#` under `resource_prefix=scl`,
 *     matching nothing ontology-engine had written.
 */
export function brandEnv(node: IConstruct["node"]): Record<string, string> {
  const { graphBaseUri, eventSourcePrefix } = resolveContext(node);
  return {
    GRAPH_BASE_URI: graphBaseUri,
    EVENT_SOURCE_PREFIX: eventSourcePrefix,
  };
}

/**
 * Applies {@link brandEnv} to every Lambda function and ECS container.
 *
 * Done as an aspect rather than by editing each of the ~32 `environment:` blocks
 * so a newly added function cannot miss it. Adding env vars changes only
 * resource properties, never construct paths, so no CloudFormation logical ID
 * moves.
 */
export class BrandEnvAspect implements IAspect {
  public visit(construct: IConstruct): void {
    const target =
      construct instanceof lambda.Function ||
      construct instanceof ecs.ContainerDefinition
        ? construct
        : undefined;
    if (!target) return;
    for (const [k, v] of Object.entries(brandEnv(target.node))) {
      target.addEnvironment(k, v);
    }
  }
}
