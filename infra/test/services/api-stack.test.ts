// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import * as cdk from "aws-cdk-lib";
import * as dynamodb from "aws-cdk-lib/aws-dynamodb";
import * as ec2 from "aws-cdk-lib/aws-ec2";
import * as lambda from "aws-cdk-lib/aws-lambda";
import { Template, Match } from "aws-cdk-lib/assertions";
import { ApiStack } from "../../lib/stacks/services/api-stack";
import { DEFAULT_RESOURCE_PREFIX, DEFAULT_ENV } from "../../lib/constants";

// Avoid running pip install / hashing the monorepo root during synth.
jest.mock("../../lib/utils/python-bundling", () => ({
  bundlePython: () =>
    lambda.Code.fromInline("def handler(event, context): pass"),
}));

const TEST_CONTEXT = {
  resource_prefix: DEFAULT_RESOURCE_PREFIX,
  env: DEFAULT_ENV,
  "aws:cdk:bundling-stacks": [],
};

describe("ApiStack authorizer — ARCHIVED guard wiring", () => {
  let template: Template;

  beforeAll(() => {
    const app = new cdk.App({ context: TEST_CONTEXT });

    const depStack = new cdk.Stack(app, "DepStack", {
      env: { account: "123456789012", region: "us-east-1" },
    });
    const vpc = new ec2.Vpc(depStack, "Vpc");
    const mkTable = (id: string) =>
      new dynamodb.Table(depStack, id, {
        partitionKey: { name: "PK", type: dynamodb.AttributeType.STRING },
      });

    template = Template.fromStack(
      new ApiStack(app, "TestApi", {
        env: { account: "123456789012", region: "us-east-1" },
        allowedOrigin: "*",
        vpc,
        issuerUrl: "https://login.example.com",
        clientId: "test-client",
        rolesTable: mkTable("Roles"),
        resourceRoleMappingsTable: mkTable("RRM"),
        cacheInvalidationTable: mkTable("Cache"),
      }),
    );
  });

  it("sets NAMESPACES_TABLE_NAME on the authorizer Lambda", () => {
    // The authorizer reads namespace status to enforce the ARCHIVED guard.
    template.hasResourceProperties("AWS::Lambda::Function", {
      FunctionName: Match.stringLikeRegexp(".*authorizer$"),
      Environment: {
        Variables: Match.objectLike({
          NAMESPACES_TABLE_NAME: Match.anyValue(),
        }),
      },
    });
  });

  it("grants the authorizer dynamodb:GetItem on the Namespaces table", () => {
    // Without this grant the status lookup fails and (fail-closed) every
    // mutating request is denied across all namespaces — so pin the permission.
    template.hasResourceProperties("AWS::IAM::Policy", {
      PolicyDocument: {
        Statement: Match.arrayWith([
          Match.objectLike({
            Effect: "Allow",
            Action: "dynamodb:GetItem",
          }),
        ]),
      },
    });
  });
});

describe("ApiStack OE monitoring", () => {
  let template: Template;

  beforeAll(() => {
    const app = new cdk.App({ context: TEST_CONTEXT });
    const depStack = new cdk.Stack(app, "DepStack", {
      env: { account: "123456789012", region: "us-east-1" },
    });
    const vpc = new ec2.Vpc(depStack, "Vpc");
    const mkTable = (id: string) =>
      new dynamodb.Table(depStack, id, {
        partitionKey: { name: "PK", type: dynamodb.AttributeType.STRING },
      });

    template = Template.fromStack(
      new ApiStack(app, "TestApiOE", {
        env: { account: "123456789012", region: "us-east-1" },
        allowedOrigin: "*",
        vpc,
        issuerUrl: "https://login.example.com",
        clientId: "test-client",
        rolesTable: mkTable("Roles"),
        resourceRoleMappingsTable: mkTable("RRM"),
        cacheInvalidationTable: mkTable("Cache"),
      }),
    );
  });

  it("emits API Gateway OE alarms (p99 latency + 5XX) and a dashboard", () => {
    template.resourceCountIs("AWS::CloudWatch::Dashboard", 1);
    const alarms = template.findResources("AWS::CloudWatch::Alarm");
    expect(Object.keys(alarms).length).toBeGreaterThanOrEqual(2);
  });
});

describe("ApiStack WAF WebACL", () => {
  const mkApi = (webAclId?: string) => {
    const app = new cdk.App({ context: TEST_CONTEXT });
    const depStack = new cdk.Stack(app, "DepStack", {
      env: { account: "123456789012", region: "us-east-1" },
    });
    const vpc = new ec2.Vpc(depStack, "Vpc");
    const mkTable = (id: string) =>
      new dynamodb.Table(depStack, id, {
        partitionKey: { name: "PK", type: dynamodb.AttributeType.STRING },
      });
    return Template.fromStack(
      new ApiStack(app, "TestApiWaf", {
        env: { account: "123456789012", region: "us-east-1" },
        allowedOrigin: "*",
        vpc,
        issuerUrl: "https://login.example.com",
        clientId: "test-client",
        rolesTable: mkTable("Roles"),
        resourceRoleMappingsTable: mkTable("RRM"),
        cacheInvalidationTable: mkTable("Cache"),
        ...(webAclId ? { webAclId } : {}),
      }),
    );
  };

  it("auto-creates a REGIONAL WebACL with the Common Rule Set when no ARN is given", () => {
    const template = mkApi();
    template.hasResourceProperties("AWS::WAFv2::WebACL", {
      Scope: "REGIONAL",
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
    // Auto-created ACL is associated with the API stage.
    template.resourceCountIs("AWS::WAFv2::WebACLAssociation", 1);
  });

  it("associates a provided WebACL ARN and creates no WebACL", () => {
    const arn =
      "arn:aws:wafv2:us-east-1:123456789012:regional/webacl/byo-api/abc";
    const template = mkApi(arn);
    template.resourceCountIs("AWS::WAFv2::WebACL", 0);
    template.hasResourceProperties("AWS::WAFv2::WebACLAssociation", {
      WebACLArn: arn,
    });
  });

  it("adds a per-IP rate-based rule to the auto-created API WebACL", () => {
    // The API WAF must carry a per-entity (per-IP) rate limit,
    // not only the signature-based Common Rule Set.
    const template = mkApi();
    template.hasResourceProperties("AWS::WAFv2::WebACL", {
      Scope: "REGIONAL",
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

describe("ApiStack request throttling", () => {
  const mkApi = (
    overrides: {
      throttleRateLimit?: number;
      throttleBurstLimit?: number;
      expensiveThrottleRateLimit?: number;
      expensiveThrottleBurstLimit?: number;
    } = {},
  ) => {
    const app = new cdk.App({ context: TEST_CONTEXT });
    const depStack = new cdk.Stack(app, "DepStack", {
      env: { account: "123456789012", region: "us-east-1" },
    });
    const vpc = new ec2.Vpc(depStack, "Vpc");
    const mkTable = (id: string) =>
      new dynamodb.Table(depStack, id, {
        partitionKey: { name: "PK", type: dynamodb.AttributeType.STRING },
      });
    return Template.fromStack(
      new ApiStack(app, "TestApiThrottle", {
        env: { account: "123456789012", region: "us-east-1" },
        allowedOrigin: "*",
        vpc,
        issuerUrl: "https://login.example.com",
        clientId: "test-client",
        rolesTable: mkTable("Roles"),
        resourceRoleMappingsTable: mkTable("RRM"),
        cacheInvalidationTable: mkTable("Cache"),
        ...overrides,
      }),
    );
  };

  it("sets the stage-wide default throttle as the wildcard MethodSetting", () => {
    const template = mkApi();
    template.hasResourceProperties("AWS::ApiGateway::Stage", {
      MethodSettings: Match.arrayWith([
        Match.objectLike({
          HttpMethod: "*",
          ResourcePath: "/*",
          ThrottlingRateLimit: 50,
          ThrottlingBurstLimit: 100,
        }),
      ]),
    });
  });

  it("applies a tighter per-method throttle to POST /induce (expensive op)", () => {
    // A single caller hammering the multi-minute induction job must not be able
    // to consume the whole stage budget — it gets its own low ceiling.
    const template = mkApi();
    template.hasResourceProperties("AWS::ApiGateway::Stage", {
      MethodSettings: Match.arrayWith([
        Match.objectLike({
          HttpMethod: "POST",
          ResourcePath: "/~1namespaces~1{namespaceId}~1induce",
          ThrottlingRateLimit: 5,
          ThrottlingBurstLimit: 10,
        }),
      ]),
    });
  });

  it("honors per-operation throttle overrides", () => {
    const template = mkApi({
      expensiveThrottleRateLimit: 2,
      expensiveThrottleBurstLimit: 3,
    });
    template.hasResourceProperties("AWS::ApiGateway::Stage", {
      MethodSettings: Match.arrayWith([
        Match.objectLike({
          HttpMethod: "POST",
          ResourcePath: "/~1namespaces~1{namespaceId}~1induce",
          ThrottlingRateLimit: 2,
          ThrottlingBurstLimit: 3,
        }),
      ]),
    });
  });
});
