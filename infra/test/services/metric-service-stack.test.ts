// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import * as cdk from "aws-cdk-lib";
import * as lambda from "aws-cdk-lib/aws-lambda";
import { Template, Match } from "aws-cdk-lib/assertions";
import { NetworkStack } from "../../lib/stacks/foundation/network-stack";
import { MetricServiceStack } from "../../lib/stacks/services/metric-service-stack";
import { DEFAULT_BEDROCK_MODEL_ID } from "../../lib/constants";

// Mock bundlePython to avoid fingerprinting the entire repo root during tests.
jest.mock("../../lib/utils/python-bundling", () => ({
  bundlePython: () =>
    lambda.Code.fromInline("def handler(event, context): pass"),
}));

const TEST_ENV = { account: "123456789012", region: "us-east-1" };
const TEST_CONTEXT = { "aws:cdk:bundling-stacks": [] };

describe("MetricServiceStack", () => {
  let template: Template;

  beforeAll(() => {
    const app = new cdk.App({ context: TEST_CONTEXT });
    const network = new NetworkStack(app, "TestNetwork", { env: TEST_ENV });

    template = Template.fromStack(
      new MetricServiceStack(app, "TestMetricService", {
        vpc: network.vpc,
        lambdaSecurityGroup: network.lambdaSecurityGroup,
        aossSecurityGroup: network.aossSecurityGroup,
        neptuneEndpoint:
          "test-neptune.cluster-abc.us-east-1.neptune.amazonaws.com",
        neptuneClusterArn:
          "arn:aws:neptune-db:us-east-1:123456789012:cluster-abc123/*",
        env: TEST_ENV,
      }),
    );
  });

  // ── Lambda Function ─────────────────────────────────────────────

  test("creates metric API Lambda function", () => {
    template.hasResourceProperties("AWS::Lambda::Function", {
      Runtime: "python3.12",
      Timeout: 30,
      MemorySize: 512,
    });
  });

  test("Lambda is placed in VPC with private subnets", () => {
    template.hasResourceProperties("AWS::Lambda::Function", {
      VpcConfig: Match.objectLike({
        SubnetIds: Match.anyValue(),
        SecurityGroupIds: Match.anyValue(),
      }),
    });
  });

  test("Lambda has required environment variables", () => {
    template.hasResourceProperties("AWS::Lambda::Function", {
      Environment: Match.objectLike({
        Variables: Match.objectLike({
          NEPTUNE_ENDPOINT: Match.stringLikeRegexp("https://.*:8182"),
          OPENSEARCH_ENDPOINT: Match.objectLike({
            Ref: Match.stringLikeRegexp(
              "SsmParameterValue.*opensearchendpoint.*",
            ),
          }),
          EVENTBRIDGE_BUS_NAME: "default",
          BEDROCK_MODEL_ID: DEFAULT_BEDROCK_MODEL_ID,
          BEDROCK_REGION: "us-east-1",
        }),
      }),
    });
  });

  test("import worker has SMUS catalog env vars for dataset resolution", () => {
    // Without these the worker's data source lookup can never initialize and
    // async imports would fail closed unconditionally.
    template.hasResourceProperties("AWS::Lambda::Function", {
      Handler: "coa_metrics.api.import_worker.handler",
      Environment: Match.objectLike({
        Variables: Match.objectLike({
          DATA_SOURCES_TABLE: Match.anyValue(),
          NAMESPACES_TABLE: Match.anyValue(),
          SMUS_DOMAIN_ID: Match.anyValue(),
          PROJECT_ACCESS_ROLE_ARN: Match.anyValue(),
        }),
      }),
    });
  });

  // ── IAM Permissions ─────────────────────────────────────────────

  test("Lambda has Neptune read/write/delete access", () => {
    template.hasResourceProperties("AWS::IAM::Policy", {
      PolicyDocument: Match.objectLike({
        Statement: Match.arrayWith([
          Match.objectLike({
            Action: [
              "neptune-db:ReadDataViaQuery",
              "neptune-db:WriteDataViaQuery",
              "neptune-db:DeleteDataViaQuery",
            ],
            Effect: "Allow",
          }),
        ]),
      }),
    });
  });

  test("Lambda has OpenSearch Serverless access", () => {
    template.hasResourceProperties("AWS::IAM::Policy", {
      PolicyDocument: Match.objectLike({
        Statement: Match.arrayWith([
          Match.objectLike({
            Action: "aoss:APIAccessAll",
            Effect: "Allow",
          }),
        ]),
      }),
    });
  });

  test("Lambda has Bedrock InvokeModel access", () => {
    template.hasResourceProperties("AWS::IAM::Policy", {
      PolicyDocument: Match.objectLike({
        Statement: Match.arrayWith([
          Match.objectLike({
            Action: "bedrock:InvokeModel",
            Effect: "Allow",
          }),
        ]),
      }),
    });
  });

  test("Lambda has EventBridge PutEvents access", () => {
    template.hasResourceProperties("AWS::IAM::Policy", {
      PolicyDocument: Match.objectLike({
        Statement: Match.arrayWith([
          Match.objectLike({
            Action: "events:PutEvents",
            Effect: "Allow",
          }),
        ]),
      }),
    });
  });

  // ── AOSS Data Access Policy ─────────────────────────────────────

  test("creates AOSS data access policy", () => {
    template.hasResourceProperties("AWS::OpenSearchServerless::AccessPolicy", {
      Type: "data",
    });
  });

  // ── S3 Bucket (OSI import/export) ───────────────────────────────

  test("creates OSI S3 bucket with encryption and block public access", () => {
    template.hasResourceProperties("AWS::S3::Bucket", {
      BucketEncryption: {
        ServerSideEncryptionConfiguration: [
          { ServerSideEncryptionByDefault: { SSEAlgorithm: "AES256" } },
        ],
      },
      PublicAccessBlockConfiguration: {
        BlockPublicAcls: true,
        BlockPublicPolicy: true,
        IgnorePublicAcls: true,
        RestrictPublicBuckets: true,
      },
    });
  });

  // ── SSM Parameter ───────────────────────────────────────────────

  test("publishes Lambda ARN to SSM", () => {
    template.hasResourceProperties("AWS::SSM::Parameter", {
      Type: "String",
    });
  });

  // ── Resource Count ──────────────────────────────────────────────

  test("creates expected Lambda functions", () => {
    // MetricApiFn + ImportWorkerFn (OSI import) + CDK auto-delete custom
    // resource for the OSI S3 bucket
    template.resourceCountIs("AWS::Lambda::Function", 3);
  });

  // ── OE Monitoring ────────────────────────────────────────────

  it("emits a metric-service OE dashboard and alarms", () => {
    template.resourceCountIs("AWS::CloudWatch::Dashboard", 1);
    const alarms = template.findResources("AWS::CloudWatch::Alarm");
    expect(Object.keys(alarms).length).toBeGreaterThanOrEqual(2);
  });
});
