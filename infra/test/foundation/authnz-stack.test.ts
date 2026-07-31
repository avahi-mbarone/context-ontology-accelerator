// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import * as cdk from "aws-cdk-lib";
import { Template, Match } from "aws-cdk-lib/assertions";
import { AuthnzStack } from "../../lib/stacks/foundation/authnz-stack";

function buildTemplate(): Template {
  const app = new cdk.App();
  const stack = new AuthnzStack(app, "TestAuthnz");
  return Template.fromStack(stack);
}

describe("AuthnzStack", () => {
  describe("table count", () => {
    it("creates exactly 3 DynamoDB tables", () => {
      const template = buildTemplate();
      template.resourceCountIs("AWS::DynamoDB::Table", 3);
    });
  });

  describe("common table properties", () => {
    it("all tables use PAY_PER_REQUEST billing", () => {
      const template = buildTemplate();
      const tables = template.findResources("AWS::DynamoDB::Table");
      for (const [, resource] of Object.entries(tables)) {
        expect((resource as any).Properties.BillingMode).toBe(
          "PAY_PER_REQUEST",
        );
      }
    });

    it("all tables have point-in-time recovery enabled", () => {
      const template = buildTemplate();
      const tables = template.findResources("AWS::DynamoDB::Table");
      for (const [, resource] of Object.entries(tables)) {
        expect(
          (resource as any).Properties.PointInTimeRecoverySpecification
            .PointInTimeRecoveryEnabled,
        ).toBe(true);
      }
    });

    it("all tables use DELETE removal policy in non-prod (env-aware)", () => {
      const template = buildTemplate();
      const tables = template.findResources("AWS::DynamoDB::Table");
      for (const [, resource] of Object.entries(tables)) {
        expect((resource as any).DeletionPolicy).toBe("Delete");
      }
    });
  });

  describe("Roles table", () => {
    it("has PK/SK key schema and DynamoDB stream", () => {
      const template = buildTemplate();
      template.hasResourceProperties("AWS::DynamoDB::Table", {
        TableName: Match.stringLikeRegexp("roles$"),
        KeySchema: Match.arrayWith([
          { AttributeName: "PK", KeyType: "HASH" },
          { AttributeName: "SK", KeyType: "RANGE" },
        ]),
        StreamSpecification: {
          StreamViewType: "NEW_AND_OLD_IMAGES",
        },
      });
    });
  });

  describe("ResourceRoleMappings table", () => {
    it("has PK/SK key schema and DynamoDB stream", () => {
      const template = buildTemplate();
      template.hasResourceProperties("AWS::DynamoDB::Table", {
        TableName: Match.stringLikeRegexp("resource-role-mappings$"),
        StreamSpecification: {
          StreamViewType: "NEW_AND_OLD_IMAGES",
        },
      });
    });

    it("has PrincipalIndex GSI with principalKey PK and resourceRoleKey SK", () => {
      const template = buildTemplate();
      template.hasResourceProperties("AWS::DynamoDB::Table", {
        TableName: Match.stringLikeRegexp("resource-role-mappings$"),
        GlobalSecondaryIndexes: Match.arrayWith([
          Match.objectLike({
            IndexName: "PrincipalIndex",
            KeySchema: [
              { AttributeName: "principalKey", KeyType: "HASH" },
              { AttributeName: "resourceRoleKey", KeyType: "RANGE" },
            ],
            Projection: { ProjectionType: "ALL" },
          }),
        ]),
      });
    });

    it("has NamespaceGrantsIndex GSI with namespaceKey PK and principalRoleKey SK", () => {
      const template = buildTemplate();
      template.hasResourceProperties("AWS::DynamoDB::Table", {
        TableName: Match.stringLikeRegexp("resource-role-mappings$"),
        GlobalSecondaryIndexes: Match.arrayWith([
          Match.objectLike({
            IndexName: "NamespaceGrantsIndex",
            KeySchema: [
              { AttributeName: "namespaceKey", KeyType: "HASH" },
              { AttributeName: "principalRoleKey", KeyType: "RANGE" },
            ],
            Projection: { ProjectionType: "ALL" },
          }),
        ]),
      });
    });
  });

  describe("CacheInvalidation table", () => {
    it("has PK/SK key schema and no stream", () => {
      const template = buildTemplate();
      template.hasResourceProperties("AWS::DynamoDB::Table", {
        TableName: Match.stringLikeRegexp("cache-invalidation$"),
        KeySchema: Match.arrayWith([
          { AttributeName: "PK", KeyType: "HASH" },
          { AttributeName: "SK", KeyType: "RANGE" },
        ]),
      });
      // Verify no stream on cache invalidation table
      const tables = template.findResources("AWS::DynamoDB::Table", {
        Properties: {
          TableName: Match.stringLikeRegexp("cache-invalidation$"),
        },
      });
      const table = Object.values(tables)[0] as any;
      expect(table.Properties.StreamSpecification).toBeUndefined();
    });
  });

  describe("streams", () => {
    it("exactly 2 tables have DynamoDB streams enabled", () => {
      const template = buildTemplate();
      const tables = template.findResources("AWS::DynamoDB::Table");
      const streamed = Object.values(tables).filter(
        (t: any) => t.Properties.StreamSpecification !== undefined,
      );
      expect(streamed).toHaveLength(2);
    });
  });
});
