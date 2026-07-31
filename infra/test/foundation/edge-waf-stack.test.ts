// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import * as cdk from "aws-cdk-lib";
import { Template, Match } from "aws-cdk-lib/assertions";
import { EdgeWafStack } from "../../lib/stacks/foundation";
import { DEFAULT_RESOURCE_PREFIX, DEFAULT_ENV } from "../../lib/constants";

/**
 * EdgeWafStack provisions the CLOUDFRONT-scope WebACL (which can only exist in
 * us-east-1) and publishes its ARN to SSM so the (possibly cross-region)
 * WebStack can consume it.
 */
describe("EdgeWafStack", () => {
  const PARAM_NAME = "/coa/edge/cloudfront-web-acl-arn";
  const template = Template.fromStack(
    new EdgeWafStack(
      new cdk.App({
        context: { resource_prefix: DEFAULT_RESOURCE_PREFIX, env: DEFAULT_ENV },
      }),
      "TestEdgeWaf",
      {
        env: { account: "123456789012", region: "us-east-1" },
        webAclArnParameterName: PARAM_NAME,
      },
    ),
  );

  it("creates a CLOUDFRONT-scope WebACL with the AWS Common Rule Set", () => {
    template.hasResourceProperties("AWS::WAFv2::WebACL", {
      Scope: "CLOUDFRONT",
      Rules: Match.arrayWith([
        Match.objectLike({
          Statement: {
            ManagedRuleGroupStatement: {
              VendorName: "AWS",
              Name: "AWSManagedRulesCommonRuleSet",
            },
          },
        }),
      ]),
    });
  });

  it("publishes the WebACL ARN to the provided SSM parameter", () => {
    template.hasResourceProperties("AWS::SSM::Parameter", {
      Name: PARAM_NAME,
      Value: Match.objectLike({ "Fn::GetAtt": Match.anyValue() }),
    });
  });

  it("adds a per-IP rate-based rule to the edge WebACL", () => {
    // The CloudFront edge WAF is the first per-entity throttle
    // an anonymous request hits, before it reaches the API or auth layer.
    template.hasResourceProperties("AWS::WAFv2::WebACL", {
      Scope: "CLOUDFRONT",
      Rules: Match.arrayWith([
        Match.objectLike({
          Name: "RateLimitPerIp",
          Action: { Block: {} },
          Statement: {
            RateBasedStatement: {
              AggregateKeyType: "IP",
              Limit: 2000,
            },
          },
        }),
      ]),
    });
  });
});
