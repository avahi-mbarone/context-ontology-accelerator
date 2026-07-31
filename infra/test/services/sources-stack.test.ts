// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import * as cdk from "aws-cdk-lib";
import * as lambda from "aws-cdk-lib/aws-lambda";
import { Template, Match } from "aws-cdk-lib/assertions";
import { NetworkStack } from "../../lib/stacks/foundation/network-stack";
import { StorageStack } from "../../lib/stacks/foundation/storage-stack";
import { SourcesStack } from "../../lib/stacks/services/sources-stack";

// Mock bundlePython to avoid fingerprinting the entire repo root during tests.
jest.mock("../../lib/utils/python-bundling", () => ({
  bundlePython: () =>
    lambda.Code.fromInline("def handler(event, context): pass"),
}));

const TEST_ENV = { account: "123456789012", region: "us-east-1" };

// Provide fake ECR context so CDK uses fromEcr() instead of fromImageAsset()
// (which would trigger a real Docker build and hang the test).
// Mirrors the approach used in unstructured-stack.test.ts.
const TEST_CONTEXT = {
  ecr_repository_arn: "arn:aws:ecr:us-east-1:123456789012:repository/coa-test",
  ecr_repository_name: "coa-test",
  sources_db_enrichment_image_uri:
    "123456789012.dkr.ecr.us-east-1.amazonaws.com/coa-test:db-enrichment-test",
  sources_preprocessing_image_uri:
    "123456789012.dkr.ecr.us-east-1.amazonaws.com/coa-test:preprocessing-test",
  sources_kg_build_image_uri:
    "123456789012.dkr.ecr.us-east-1.amazonaws.com/coa-test:kg-build-test",
  "aws:cdk:bundling-stacks": [],
};

describe("SourcesStack", () => {
  let template: Template;

  beforeAll(() => {
    const app = new cdk.App({ context: TEST_CONTEXT });
    const network = new NetworkStack(app, "TestNetwork", { env: TEST_ENV });
    const storage = new StorageStack(app, "TestStorage", {
      network,
      env: TEST_ENV,
    });
    template = Template.fromStack(
      new SourcesStack(app, "TestSources", {
        network,
        storage,
        allowedOrigin: "https://test.example.com",
        env: TEST_ENV,
      }),
    );
  });

  describe("DynamoDB Tables", () => {
    it("creates sources-table with PK and SK string keys", () => {
      template.hasResourceProperties("AWS::DynamoDB::Table", {
        KeySchema: Match.arrayWith([
          { AttributeName: "PK", KeyType: "HASH" },
          { AttributeName: "SK", KeyType: "RANGE" },
        ]),
        BillingMode: "PAY_PER_REQUEST",
      });
    });

    it("sources-table has ByNamespace GSI on namespaceId + createdAt", () => {
      template.hasResourceProperties("AWS::DynamoDB::Table", {
        GlobalSecondaryIndexes: Match.arrayWith([
          Match.objectLike({
            IndexName: "ByNamespace",
            KeySchema: Match.arrayWith([
              { AttributeName: "namespaceId", KeyType: "HASH" },
              { AttributeName: "createdAt", KeyType: "RANGE" },
            ]),
          }),
        ]),
      });
    });

    it("sources-table has BySourceType GSI on namespaceId + sourceTypeCreatedAt", () => {
      template.hasResourceProperties("AWS::DynamoDB::Table", {
        GlobalSecondaryIndexes: Match.arrayWith([
          Match.objectLike({
            IndexName: "BySourceType",
            KeySchema: Match.arrayWith([
              { AttributeName: "namespaceId", KeyType: "HASH" },
              { AttributeName: "sourceTypeCreatedAt", KeyType: "RANGE" },
            ]),
          }),
        ]),
      });
    });

    it("sources-table has ByName GSI on namespaceId + name for O(1) uniqueness checks", () => {
      template.hasResourceProperties("AWS::DynamoDB::Table", {
        GlobalSecondaryIndexes: Match.arrayWith([
          Match.objectLike({
            IndexName: "ByName",
            KeySchema: Match.arrayWith([
              { AttributeName: "namespaceId", KeyType: "HASH" },
              { AttributeName: "name", KeyType: "RANGE" },
            ]),
          }),
        ]),
      });
    });
  });

  describe("Sources API Lambda", () => {
    it("creates a Python 3.12 ARM64 Lambda function", () => {
      template.hasResourceProperties("AWS::Lambda::Function", {
        Runtime: "python3.12",
        Architectures: ["arm64"],
        Timeout: 30,
        MemorySize: 256,
      });
    });

    it("Lambda has SOURCES_TABLE environment variable", () => {
      template.hasResourceProperties("AWS::Lambda::Function", {
        Environment: {
          Variables: Match.objectLike({
            SOURCES_TABLE: Match.anyValue(),
          }),
        },
      });
    });

    it("Lambda has SOURCE_SCAN_JOBS_TABLE environment variable", () => {
      template.hasResourceProperties("AWS::Lambda::Function", {
        Environment: {
          Variables: Match.objectLike({
            SOURCE_SCAN_JOBS_TABLE: Match.anyValue(),
          }),
        },
      });
    });

    it("Lambda has ALLOWED_ORIGIN environment variable", () => {
      template.hasResourceProperties("AWS::Lambda::Function", {
        Environment: {
          Variables: Match.objectLike({
            ALLOWED_ORIGIN: "https://test.example.com",
          }),
        },
      });
    });

    it("Lambda has REVIEW_QUEUE_URL environment variable for bulk approve/reject dispatch", () => {
      template.hasResourceProperties("AWS::Lambda::Function", {
        Environment: {
          Variables: Match.objectLike({
            REVIEW_QUEUE_URL: Match.anyValue(),
          }),
        },
      });
    });
  });

  describe("Federation Provisioner (Option B isolation)", () => {
    it("creates a dedicated JDBC federation provisioner Lambda in VPC", () => {
      template.hasResourceProperties("AWS::Lambda::Function", {
        FunctionName: Match.stringLikeRegexp(
          ".*sources-federation-provisioner$",
        ),
        Handler:
          "coa_sources.database.pipeline.federation_handler.handler",
        VpcConfig: Match.objectLike({ SubnetIds: Match.anyValue() }),
        Environment: {
          Variables: Match.objectLike({
            FEDERATED_CATALOG_ROLE_ARN: Match.anyValue(),
            ATHENA_SPILL_BUCKET: Match.anyValue(),
          }),
        },
      });
    });

    it("publishes the federation provisioner role ARN for central LF-admin registration", () => {
      template.hasResourceProperties("AWS::SSM::Parameter", {
        Type: "String",
        Description: Match.stringLikeRegexp(
          ".*Lake Formation data-lake admin.*",
        ),
      });
    });

    it("passes the consumer query role SSM param to the federation provisioner", () => {
      template.hasResourceProperties("AWS::Lambda::Function", {
        FunctionName: Match.stringLikeRegexp(
          ".*sources-federation-provisioner$",
        ),
        Environment: {
          Variables: Match.objectLike({
            CONSUMER_QUERY_ROLE_SSM_PARAM: Match.stringLikeRegexp(
              ".*/serve/runtime-role-arn$",
            ),
          }),
        },
      });
    });

    it("grants the federation provisioner Glue read on federated databases/tables (for GrantPermissions)", () => {
      template.hasResourceProperties("AWS::IAM::Policy", {
        PolicyDocument: {
          Statement: Match.arrayWith([
            Match.objectLike({
              Sid: "GlueFederatedCatalogRead",
              Action: [
                "glue:GetDatabase",
                "glue:GetDatabases",
                "glue:GetTable",
                "glue:GetTables",
              ],
              Resource: Match.arrayWith([
                Match.stringLikeRegexp(".*:database/.*"),
                Match.stringLikeRegexp(".*:table/.*"),
              ]),
            }),
          ]),
        },
      });
    });

    it("grants the federation provisioner Glue read on ALL native databases (for native LF grant)", () => {
      // Required so lakeformation:GrantPermissions can validate the grantor has
      // access to the target native Glue database (GLUE_DATABASE sources, strict-LF accounts).
      template.hasResourceProperties("AWS::IAM::Policy", {
        PolicyDocument: {
          Statement: Match.arrayWith([
            Match.objectLike({
              Sid: "GlueNativeDatabaseRead",
              Action: [
                "glue:GetDatabase",
                "glue:GetDatabases",
                "glue:GetTable",
                "glue:GetTables",
              ],
              // Wildcard suffixes cover ALL native databases, not just scldevds_* federated ones.
              Resource: Match.arrayWith([
                Match.stringLikeRegexp(":catalog$"),
                Match.stringLikeRegexp(":database/\\*$"),
                Match.stringLikeRegexp(":table/\\*/\\*$"),
              ]),
            }),
          ]),
        },
      });
    });

    it("grants the federation provisioner lakeformation:GrantPermissions", () => {
      template.hasResourceProperties("AWS::IAM::Policy", {
        PolicyDocument: {
          Statement: Match.arrayWith([
            Match.objectLike({
              Sid: "LakeFormationFederation",
              Action: Match.arrayWith(["lakeformation:GrantPermissions"]),
            }),
          ]),
        },
      });
    });

    it("registers the provisioner role as an LF admin via a custom resource (non-destructive)", () => {
      // onEvent Lambda role can read/write LF settings + read the role-ARN SSM param.
      template.hasResourceProperties("AWS::IAM::Policy", {
        PolicyDocument: {
          Statement: Match.arrayWith([
            Match.objectLike({
              Action: Match.arrayWith([
                "lakeformation:GetDataLakeSettings",
                "lakeformation:PutDataLakeSettings",
              ]),
            }),
          ]),
        },
      });
    });

    it("lets the federated-catalog role decrypt CMK-encrypted secrets via Secrets Manager only", () => {
      template.hasResourceProperties("AWS::IAM::Policy", {
        PolicyDocument: {
          Statement: Match.arrayWith([
            Match.objectLike({
              Sid: "DecryptCredentialSecret",
              Action: "kms:Decrypt",
              Condition: {
                StringLike: {
                  "kms:ViaService": "secretsmanager.*.amazonaws.com",
                },
              },
            }),
          ]),
        },
      });
    });

    it("lets the provisioner assume the federated-catalog role for the secret precheck", () => {
      template.hasResourceProperties("AWS::IAM::Policy", {
        PolicyDocument: {
          Statement: Match.arrayWith([
            Match.objectLike({
              Action: "sts:AssumeRole",
              Resource: Match.anyValue(),
            }),
          ]),
        },
      });
    });
  });

  describe("Bulk Review Pipeline", () => {
    it("creates a SQS queue with SQS-managed encryption and 6-minute visibility timeout", () => {
      template.hasResourceProperties("AWS::SQS::Queue", {
        QueueName: Match.stringLikeRegexp(".*sources-bulk-review-queue$"),
        VisibilityTimeout: 360,
        SqsManagedSseEnabled: true,
      });
    });

    it("creates a DLQ with SQS-managed encryption and 14-day retention", () => {
      template.hasResourceProperties("AWS::SQS::Queue", {
        QueueName: Match.stringLikeRegexp(".*sources-bulk-review-dlq$"),
        MessageRetentionPeriod: 14 * 24 * 60 * 60,
        SqsManagedSseEnabled: true,
      });
    });

    it("queue has a redrive policy pointing to the DLQ with maxReceiveCount=3", () => {
      template.hasResourceProperties("AWS::SQS::Queue", {
        QueueName: Match.stringLikeRegexp(".*sources-bulk-review-queue$"),
        RedrivePolicy: Match.objectLike({
          maxReceiveCount: 3,
        }),
      });
    });

    it("creates a worker Lambda with 5-minute timeout, ARM64, in VPC", () => {
      template.hasResourceProperties("AWS::Lambda::Function", {
        FunctionName: Match.stringLikeRegexp(".*sources-bulk-review-worker$"),
        Runtime: "python3.12",
        Architectures: ["arm64"],
        Timeout: 300,
        VpcConfig: Match.objectLike({
          SubnetIds: Match.anyValue(),
          SecurityGroupIds: Match.anyValue(),
        }),
      });
    });

    it("worker has a SQS event source mapping to the bulk review queue", () => {
      // batchSize=1 means SQS feeds one message per worker invocation,
      // matching the worker's per-message idempotency check.
      template.hasResourceProperties("AWS::Lambda::EventSourceMapping", {
        BatchSize: 1,
        EventSourceArn: Match.anyValue(),
        FunctionName: Match.anyValue(),
      });
    });

    it("worker can re-enqueue to its own queue: REVIEW_QUEUE_URL env + sqs:SendMessage grant", () => {
      // Self-continuation (#853): a source too large for one invocation pages
      // itself by re-enqueuing with a nextToken, so the worker needs both the
      // queue URL and SendMessage on it. The grant is checked against the
      // worker's own role — the API Lambda also holds SendMessage on this
      // queue, so an unscoped assertion would still pass with the worker's
      // grant removed.
      const queue = Object.entries(
        template.findResources("AWS::SQS::Queue"),
      ).find(([, q]) =>
        /sources-bulk-review-queue$/.test(q.Properties.QueueName),
      );
      const worker = Object.entries(
        template.findResources("AWS::Lambda::Function"),
      ).find(([, f]) =>
        /sources-bulk-review-worker$/.test(f.Properties.FunctionName),
      );
      expect(queue).toBeDefined();
      expect(worker).toBeDefined();
      const [queueId] = queue!;
      const [, workerFn] = worker!;

      // Ref on an AWS::SQS::Queue resolves to the queue URL.
      expect(
        workerFn.Properties.Environment.Variables.REVIEW_QUEUE_URL,
      ).toEqual({ Ref: queueId });

      const workerRoleId = workerFn.Properties.Role["Fn::GetAtt"][0];
      const workerCanSend = Object.values(
        template.findResources("AWS::IAM::Policy"),
      ).some(
        (p: any) =>
          p.Properties.Roles?.some((r: any) => r.Ref === workerRoleId) &&
          p.Properties.PolicyDocument.Statement.some(
            (s: any) =>
              [s.Action].flat().includes("sqs:SendMessage") &&
              JSON.stringify(s.Resource).includes(queueId),
          ),
      );
      expect(workerCanSend).toBe(true);
    });
  });

  describe("Federated Catalog Role — Glue VPC connection", () => {
    // Regression guard: Glue managed/VPC federated connections require
    // ec2:CreateNetworkInterfacePermission (in addition to CreateNetworkInterface)
    // to attach the ENI to the managed service account. Without it MySQL/SQLServer
    // (Athena-federation) sources FAILED at query time with Athena
    // HIVE_METASTORE_ERROR / Glue "Unable to access VPC ... check the policies on
    // the IAM role" — confirmed live 2026-07-29 with valid networking + SG.
    it("grants the federated catalog role ec2:CreateNetworkInterfacePermission scoped to Glue", () => {
      // The grant lives in its own statement, scoped to network-interface/* AND
      // conditioned on ec2:AuthorizedService=glue.amazonaws.com so the role cannot
      // hand ENI-attach permission to an arbitrary service/account (least-privilege).
      template.hasResourceProperties("AWS::IAM::Policy", {
        PolicyDocument: {
          Statement: Match.arrayWith([
            Match.objectLike({
              Sid: "Ec2CreateNetworkInterfacePermissionForGlue",
              Action: "ec2:CreateNetworkInterfacePermission",
              Condition: {
                StringEquals: { "ec2:AuthorizedService": "glue.amazonaws.com" },
              },
            }),
          ]),
        },
      });
    });
  });

  describe("SSM Parameters", () => {
    it("publishes Lambda ARN to SSM", () => {
      template.hasResourceProperties("AWS::SSM::Parameter", {
        Type: "String",
        Description: "Sources API Lambda ARN",
      });
    });

    it("publishes sources table name to SSM", () => {
      template.hasResourceProperties("AWS::SSM::Parameter", {
        Type: "String",
        Description: "Sources DynamoDB table name",
      });
    });

    it("publishes source scan jobs table name to SSM", () => {
      template.hasResourceProperties("AWS::SSM::Parameter", {
        Type: "String",
        Description: "Source scan jobs DynamoDB table name",
      });
    });
  });

  describe("CfnOutputs", () => {
    it("exports SourcesTableName", () => {
      expect(Object.keys(template.findOutputs("SourcesTableName")).length).toBe(
        1,
      );
    });

    it("exports SourceScanJobsTableName", () => {
      expect(
        Object.keys(template.findOutputs("SourceScanJobsTableName")).length,
      ).toBe(1);
    });

    it("exports SourcesApiFnArn", () => {
      expect(Object.keys(template.findOutputs("SourcesApiFnArn")).length).toBe(
        1,
      );
    });
  });

  describe("Telemetry — CloudWatch Dashboard and Alarms", () => {
    it("emits a facade OE dashboard and no legacy SourcesScanDashboard", () => {
      // The facade creates exactly one env-prefixed dashboard for this stack.
      template.resourceCountIs("AWS::CloudWatch::Dashboard", 1);
      // Legacy dashboard name must be gone.
      const dashboards = template.findResources("AWS::CloudWatch::Dashboard", {
        Properties: { DashboardName: Match.stringLikeRegexp("sources-scan$") },
      });
      expect(Object.keys(dashboards)).toHaveLength(0);
    });

    it("still emits alarms for the sources pipeline (migrated to facade)", () => {
      // At least the pre-migration alarm count (8) survives the migration.
      const alarms = template.findResources("AWS::CloudWatch::Alarm");
      expect(Object.keys(alarms).length).toBeGreaterThanOrEqual(8);
    });
  });

  describe("Database Connector Lambda (DbConnectorFn)", () => {
    it("has CONSUMER_QUERY_ROLE_ARN environment variable (from SSM)", () => {
      template.hasResourceProperties("AWS::Lambda::Function", {
        FunctionName: Match.stringLikeRegexp(".*sources-db-connector$"),
        Environment: {
          Variables: Match.objectLike({
            CONSUMER_QUERY_ROLE_ARN: Match.anyValue(),
          }),
        },
      });
    });

    it("has LF_GRANTOR_ROLE_ARN environment variable", () => {
      template.hasResourceProperties("AWS::Lambda::Function", {
        FunctionName: Match.stringLikeRegexp(".*sources-db-connector$"),
        Environment: {
          Variables: Match.objectLike({
            LF_GRANTOR_ROLE_ARN: Match.anyValue(),
          }),
        },
      });
    });
  });

  describe("Database Scan State Machine — SCAN_FAILED source update", () => {
    // The scan-failed branch writes three fields (status, updatedAt,
    // lastScanJobId) to the sources table instead of two. These assertions
    // pin the UpdateItem expression and the scanJobSK → lastScanJobId mapping
    // so a regression in the state machine definition fails the build.
    const stateMachineDefinition = (): string => {
      const machines = template.findResources(
        "AWS::StepFunctions::StateMachine",
      );
      // Serialize every state machine definition (incl. Fn::Join fragments)
      // so we can assert on the rendered Amazon States Language.
      return JSON.stringify(Object.values(machines));
    };

    it("writes lastScanJobId in the SCAN_FAILED source UpdateItem expression", () => {
      const definition = stateMachineDefinition();
      // The update expression sets status (#s), updatedAt (#u) and the new
      // lastScanJobId (#l) attribute.
      expect(definition).toContain("SET #s = :s, #u = :u, #l = :l");
      expect(definition).toContain("lastScanJobId");
      expect(definition).toContain("SCAN_FAILED");
    });

    it("maps scanJobSK from the state input into lastScanJobId", () => {
      const definition = stateMachineDefinition();
      // The lastScanJobId value (:l) is sourced from $.scanJobSK in the
      // execution input, not a literal.
      expect(definition).toContain("$.scanJobSK");
    });
  });

  describe("VPC Configuration — All Lambdas in VPC (security baseline)", () => {
    it("DbScanTriggerFn is deployed in VPC", () => {
      template.hasResourceProperties("AWS::Lambda::Function", {
        FunctionName: Match.stringLikeRegexp(".*sources-db-scan-trigger$"),
        VpcConfig: Match.objectLike({
          SubnetIds: Match.anyValue(),
          SecurityGroupIds: Match.anyValue(),
        }),
      });
    });

    it("SourcesDocDeletionCleanupFn is deployed in VPC", () => {
      template.hasResourceProperties("AWS::Lambda::Function", {
        FunctionName: Match.stringLikeRegexp(
          ".*sources-doc-deletion-cleanup$",
        ),
        VpcConfig: Match.objectLike({
          SubnetIds: Match.anyValue(),
          SecurityGroupIds: Match.anyValue(),
        }),
      });
    });

    it("SourcesDocIngestionTriggerFn is deployed in VPC", () => {
      template.hasResourceProperties("AWS::Lambda::Function", {
        FunctionName: Match.stringLikeRegexp(
          ".*sources-doc-ingestion-trigger$",
        ),
        VpcConfig: Match.objectLike({
          SubnetIds: Match.anyValue(),
          SecurityGroupIds: Match.anyValue(),
        }),
      });
    });
  });

  describe("KG Build Task Role IAM Permissions", () => {
    it("Bedrock batch job actions are scoped to specific model ARNs, not wildcard", () => {
      const policies = template.findResources("AWS::IAM::Policy");
      const kgBuildPolicy = Object.values(policies).find((p: any) =>
        p.Properties?.PolicyDocument?.Statement?.some(
          (stmt: any) =>
            Array.isArray(stmt.Action) &&
            stmt.Action.includes("bedrock:CreateModelInvocationJob"),
        ),
      ) as any;

      expect(kgBuildPolicy).toBeDefined();
      const batchJobStatement =
        kgBuildPolicy.Properties.PolicyDocument.Statement.find(
          (stmt: any) =>
            Array.isArray(stmt.Action) &&
            stmt.Action.includes("bedrock:CreateModelInvocationJob"),
        );

      expect(batchJobStatement).toBeDefined();
      expect(batchJobStatement.Resource).not.toEqual(["*"]);
      const resourceStr = JSON.stringify(batchJobStatement.Resource);
      expect(resourceStr).toContain("foundation-model/*");
      expect(resourceStr).toContain("inference-profile/*");
    });

    it("Bedrock InvokeModel is scoped to specific model ARNs", () => {
      template.hasResourceProperties("AWS::IAM::Policy", {
        PolicyDocument: {
          Statement: Match.arrayWith([
            Match.objectLike({
              Action: "bedrock:InvokeModel",
              Resource: Match.arrayWith([
                Match.stringLikeRegexp("arn:aws:bedrock:.*:foundation-model/"),
              ]),
            }),
          ]),
        },
      });
    });

    it("Bedrock batch job actions include all required management operations", () => {
      const policies = template.findResources("AWS::IAM::Policy");
      const kgBuildPolicy = Object.values(policies).find((p: any) =>
        p.Properties?.PolicyDocument?.Statement?.some(
          (stmt: any) =>
            Array.isArray(stmt.Action) &&
            stmt.Action.includes("bedrock:CreateModelInvocationJob"),
        ),
      ) as any;

      expect(kgBuildPolicy).toBeDefined();
      const batchJobStatement =
        kgBuildPolicy.Properties.PolicyDocument.Statement.find(
          (stmt: any) =>
            Array.isArray(stmt.Action) &&
            stmt.Action.includes("bedrock:CreateModelInvocationJob"),
        );

      expect(batchJobStatement.Action).toEqual(
        expect.arrayContaining([
          "bedrock:CreateModelInvocationJob",
          "bedrock:GetModelInvocationJob",
          "bedrock:ListModelInvocationJobs",
          "bedrock:StopModelInvocationJob",
        ]),
      );
    });
  });
});
