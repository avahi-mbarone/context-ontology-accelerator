// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import * as cdk from "aws-cdk-lib";
import * as dynamodb from "aws-cdk-lib/aws-dynamodb";
import { Template, Match } from "aws-cdk-lib/assertions";
import { DynamoDBTable } from "../../lib/constructs/dynamodb-table";

function buildTemplate(
  props?: Partial<{
    stream: dynamodb.StreamViewType;
    removalPolicy: cdk.RemovalPolicy;
  }>,
): Template {
  const app = new cdk.App();
  const stack = new cdk.Stack(app, "TestStack");
  new DynamoDBTable(stack, "TestTable", {
    tableName: "test-table",
    partitionKey: { name: "PK", type: dynamodb.AttributeType.STRING },
    sortKey: { name: "SK", type: dynamodb.AttributeType.STRING },
    ...props,
  });
  return Template.fromStack(stack);
}

describe("DynamoDBTable construct", () => {
  it("uses PAY_PER_REQUEST billing", () => {
    const template = buildTemplate();
    template.hasResourceProperties("AWS::DynamoDB::Table", {
      BillingMode: "PAY_PER_REQUEST",
    });
  });

  it("enables point-in-time recovery", () => {
    const template = buildTemplate();
    template.hasResourceProperties("AWS::DynamoDB::Table", {
      PointInTimeRecoverySpecification: {
        PointInTimeRecoveryEnabled: true,
      },
    });
  });

  it("defaults to DELETE removal policy in non-prod (env-aware)", () => {
    const template = buildTemplate();
    const tables = template.findResources("AWS::DynamoDB::Table");
    const table = Object.values(tables)[0] as any;
    expect(table.DeletionPolicy).toBe("Delete");
  });

  it("allows overriding removal policy", () => {
    const template = buildTemplate({
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });
    const tables = template.findResources("AWS::DynamoDB::Table");
    const table = Object.values(tables)[0] as any;
    expect(table.DeletionPolicy).toBe("Delete");
  });

  it("has no stream by default", () => {
    const template = buildTemplate();
    template.hasResourceProperties("AWS::DynamoDB::Table", {
      StreamSpecification: Match.absent(),
    });
  });

  it("enables stream when specified", () => {
    const template = buildTemplate({
      stream: dynamodb.StreamViewType.NEW_AND_OLD_IMAGES,
    });
    template.hasResourceProperties("AWS::DynamoDB::Table", {
      StreamSpecification: { StreamViewType: "NEW_AND_OLD_IMAGES" },
    });
  });

  it("supports addGlobalSecondaryIndex", () => {
    const app = new cdk.App();
    const stack = new cdk.Stack(app, "TestStack");
    const ddbTable = new DynamoDBTable(stack, "TestTable", {
      tableName: "test-table",
      partitionKey: { name: "PK", type: dynamodb.AttributeType.STRING },
    });
    ddbTable.addGlobalSecondaryIndex({
      indexName: "TestIndex",
      partitionKey: { name: "GSI_PK", type: dynamodb.AttributeType.STRING },
      projectionType: dynamodb.ProjectionType.ALL,
    });
    const template = Template.fromStack(stack);
    template.hasResourceProperties("AWS::DynamoDB::Table", {
      GlobalSecondaryIndexes: Match.arrayWith([
        Match.objectLike({ IndexName: "TestIndex" }),
      ]),
    });
  });
});
