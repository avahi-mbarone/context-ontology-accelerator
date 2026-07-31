// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import * as cdk from "aws-cdk-lib";
import * as dynamodb from "aws-cdk-lib/aws-dynamodb";
import * as ec2 from "aws-cdk-lib/aws-ec2";
import * as lambda from "aws-cdk-lib/aws-lambda";
import { Template, Match } from "aws-cdk-lib/assertions";
import { ServeStack } from "../../lib/stacks/services/serve-stack";
import { DEFAULT_RESOURCE_PREFIX, DEFAULT_ENV } from "../../lib/constants";

jest.mock("../../lib/utils/python-bundling", () => ({
  bundlePython: () =>
    lambda.Code.fromInline("def handler(event, context): pass"),
}));

const BASE_CONTEXT = {
  resource_prefix: DEFAULT_RESOURCE_PREFIX,
  env: DEFAULT_ENV,
  context_manager_image_uri:
    "123456789012.dkr.ecr.us-east-1.amazonaws.com/coa-dev:latest",
  "aws:cdk:bundling-stacks": [],
};

function createStack(contextOverrides: Record<string, string> = {}): Template {
  const app = new cdk.App({
    context: { ...BASE_CONTEXT, ...contextOverrides },
  });

  const depStack = new cdk.Stack(app, "DepStack", {
    env: { account: "123456789012", region: "us-east-1" },
  });
  const vpc = new ec2.Vpc(depStack, "Vpc", { maxAzs: 2 });
  const aossSg = new ec2.SecurityGroup(depStack, "AossSG", { vpc });
  const neptuneSg = new ec2.SecurityGroup(depStack, "NeptuneSG", { vpc });
  const lambdaSg = new ec2.SecurityGroup(depStack, "LambdaSG", { vpc });
  const mkTable = (id: string) =>
    new dynamodb.Table(depStack, id, {
      partitionKey: { name: "PK", type: dynamodb.AttributeType.STRING },
    });

  const stack = new ServeStack(app, "TestServe", {
    env: { account: "123456789012", region: "us-east-1" },
    vpc,
    aossSecurityGroup: aossSg,
    neptuneSecurityGroup: neptuneSg,
    lambdaSecurityGroup: lambdaSg,
    issuerUrl: "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_test",
    clientId: "test-client-id",
    neptuneClusterArn:
      "arn:aws:neptune-db:us-east-1:123456789012:cluster:test-cluster/*",
    neptuneEndpoint: "test-cluster.cluster-abc.us-east-1.neptune.amazonaws.com",
    ontologyBucketArn: "arn:aws:s3:::coa-dev-ontology-artifacts",
    vkgEndpoint: "http://vkg.coa-dev-services.local:8080",
    rolesTable: mkTable("Roles"),
    resourceRoleMappingsTable: mkTable("RRM"),
  });

  return Template.fromStack(stack);
}

describe("ServeStack - Security Group egress", () => {
  describe("without JDBC peer CIDRs", () => {
    let template: Template;
    beforeAll(() => {
      template = createStack();
    });

    it("has local-VPC PostgreSQL egress on port 5432", () => {
      template.hasResourceProperties("AWS::EC2::SecurityGroup", {
        SecurityGroupEgress: Match.arrayWith([
          Match.objectLike({
            IpProtocol: "tcp",
            FromPort: 5432,
            ToPort: 5432,
            Description: Match.stringLikeRegexp("PostgreSQL.*within VPC"),
          }),
        ]),
      });
    });

    it("has local-VPC MySQL egress on port 3306", () => {
      template.hasResourceProperties("AWS::EC2::SecurityGroup", {
        SecurityGroupEgress: Match.arrayWith([
          Match.objectLike({
            IpProtocol: "tcp",
            FromPort: 3306,
            ToPort: 3306,
            Description: Match.stringLikeRegexp("MySQL.*within VPC"),
          }),
        ]),
      });
    });

    it("has local-VPC MSSQL egress on port 1433", () => {
      template.hasResourceProperties("AWS::EC2::SecurityGroup", {
        SecurityGroupEgress: Match.arrayWith([
          Match.objectLike({
            IpProtocol: "tcp",
            FromPort: 1433,
            ToPort: 1433,
            Description: Match.stringLikeRegexp("MSSQL.*within VPC"),
          }),
        ]),
      });
    });

    it("has local-VPC Redshift egress on port 5439", () => {
      template.hasResourceProperties("AWS::EC2::SecurityGroup", {
        SecurityGroupEgress: Match.arrayWith([
          Match.objectLike({
            IpProtocol: "tcp",
            FromPort: 5439,
            ToPort: 5439,
            Description: Match.stringLikeRegexp("Redshift.*within VPC"),
          }),
        ]),
      });
    });

    it("does NOT have peer-CIDR egress rules when no peering configured", () => {
      // No rule should reference a CIDR outside the VPC
      template.hasResourceProperties("AWS::EC2::SecurityGroup", {
        SecurityGroupEgress: Match.not(
          Match.arrayWith([
            Match.objectLike({
              Description: Match.stringLikeRegexp("peer network"),
            }),
          ]),
        ),
      });
    });
  });

  describe("with JDBC peer CIDRs configured", () => {
    let template: Template;
    beforeAll(() => {
      template = createStack({
        jdbc_peer_vpc_id: "vpc-peer123",
        jdbc_peer_cidrs: "10.20.0.0/16,10.30.0.0/16",
      });
    });

    it("adds PostgreSQL egress to each peer CIDR", () => {
      template.hasResourceProperties("AWS::EC2::SecurityGroup", {
        SecurityGroupEgress: Match.arrayWith([
          Match.objectLike({
            IpProtocol: "tcp",
            FromPort: 5432,
            ToPort: 5432,
            CidrIp: "10.20.0.0/16",
          }),
          Match.objectLike({
            IpProtocol: "tcp",
            FromPort: 5432,
            ToPort: 5432,
            CidrIp: "10.30.0.0/16",
          }),
        ]),
      });
    });

    it("adds MySQL egress to each peer CIDR", () => {
      template.hasResourceProperties("AWS::EC2::SecurityGroup", {
        SecurityGroupEgress: Match.arrayWith([
          Match.objectLike({
            IpProtocol: "tcp",
            FromPort: 3306,
            ToPort: 3306,
            CidrIp: "10.20.0.0/16",
          }),
          Match.objectLike({
            IpProtocol: "tcp",
            FromPort: 3306,
            ToPort: 3306,
            CidrIp: "10.30.0.0/16",
          }),
        ]),
      });
    });

    it("adds MSSQL egress to each peer CIDR", () => {
      template.hasResourceProperties("AWS::EC2::SecurityGroup", {
        SecurityGroupEgress: Match.arrayWith([
          Match.objectLike({
            IpProtocol: "tcp",
            FromPort: 1433,
            ToPort: 1433,
            CidrIp: "10.20.0.0/16",
          }),
          Match.objectLike({
            IpProtocol: "tcp",
            FromPort: 1433,
            ToPort: 1433,
            CidrIp: "10.30.0.0/16",
          }),
        ]),
      });
    });

    it("adds Redshift egress to each peer CIDR", () => {
      template.hasResourceProperties("AWS::EC2::SecurityGroup", {
        SecurityGroupEgress: Match.arrayWith([
          Match.objectLike({
            IpProtocol: "tcp",
            FromPort: 5439,
            ToPort: 5439,
            CidrIp: "10.20.0.0/16",
          }),
          Match.objectLike({
            IpProtocol: "tcp",
            FromPort: 5439,
            ToPort: 5439,
            CidrIp: "10.30.0.0/16",
          }),
        ]),
      });
    });
  });

  describe("with JDBC TGW CIDRs configured", () => {
    let template: Template;
    beforeAll(() => {
      template = createStack({
        jdbc_tgw_id: "tgw-abc123",
        jdbc_tgw_cidrs: "172.16.0.0/12",
      });
    });

    it("adds DB port egress to TGW CIDRs", () => {
      template.hasResourceProperties("AWS::EC2::SecurityGroup", {
        SecurityGroupEgress: Match.arrayWith([
          Match.objectLike({
            IpProtocol: "tcp",
            FromPort: 5432,
            ToPort: 5432,
            CidrIp: "172.16.0.0/12",
          }),
          Match.objectLike({
            IpProtocol: "tcp",
            FromPort: 3306,
            ToPort: 3306,
            CidrIp: "172.16.0.0/12",
          }),
        ]),
      });
    });
  });
});

describe("ServeStack - OE Monitoring", () => {
  let template: Template;
  beforeAll(() => {
    template = createStack();
  });

  it("emits a serve OE dashboard and Lambda alarms", () => {
    template.resourceCountIs("AWS::CloudWatch::Dashboard", 1);
    const alarms = template.findResources("AWS::CloudWatch::Alarm");
    expect(Object.keys(alarms).length).toBeGreaterThanOrEqual(1);
  });
});
