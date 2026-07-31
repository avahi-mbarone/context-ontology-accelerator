// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import * as cdk from "aws-cdk-lib";
import * as ssm from "aws-cdk-lib/aws-ssm";
import { Construct } from "constructs";
import { SCLStack } from "../../constructs/scl-stack";
import { WafWebAcl } from "../../constructs/waf-web-acl";

export interface EdgeWafStackProps extends cdk.StackProps {
  /**
   * SSM parameter name (created in THIS us-east-1 stack) that the WebACL ARN
   * is published to. The WebStack — which may live in another region — reads
   * it cross-region via a custom resource.
   */
  readonly webAclArnParameterName: string;
}

/**
 * Edge (CloudFront) WAF stack — MUST be deployed to `us-east-1`.
 *
 * CloudFront requires a `CLOUDFRONT`-scope WAFv2 WebACL, and such WebACLs can
 * only be created in `us-east-1`. When the main deployment targets another
 * region, this dedicated stack provisions the WebACL in `us-east-1` and
 * publishes its ARN to an SSM parameter so the (possibly cross-region)
 * WebStack can consume it. Only instantiated on the auto-create path (i.e. when
 * the deployer does not bring their own CloudFront WebACL ARN).
 */
export class EdgeWafStack extends SCLStack {
  public readonly webAclArn: string;

  constructor(scope: Construct, id: string, props: EdgeWafStackProps) {
    super(scope, id, props);
    this.addComponentTag("foundation");

    const waf = new WafWebAcl(this, "CloudFrontWaf", {
      scope: "CLOUDFRONT",
      namePrefix: "cloudfront",
    });
    this.webAclArn = waf.webAclArn;

    new ssm.StringParameter(this, "WebAclArnParam", {
      parameterName: props.webAclArnParameterName,
      stringValue: waf.webAclArn,
      description:
        "CLOUDFRONT-scope WAF WebACL ARN for the SCL web distribution",
    });

    new cdk.CfnOutput(this, "CloudFrontWebAclArn", {
      value: waf.webAclArn,
      description: "CLOUDFRONT WAF WebACL ARN",
    });
  }
}
