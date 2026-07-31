// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import * as cdk from "aws-cdk-lib";
import * as lambda from "aws-cdk-lib/aws-lambda";
import { Template, Match } from "aws-cdk-lib/assertions";
import { SclMonitoring } from "../../lib/constructs/monitoring";

describe("SclMonitoring", () => {
  function synth(): Template {
    const app = new cdk.App();
    const stack = new cdk.Stack(app, "TestStack");
    const monitoring = new SclMonitoring(stack, "Monitoring", {
      alarmNamePrefix: "coa-test",
    });
    const fn = new lambda.Function(stack, "Fn", {
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: "index.handler",
      code: lambda.Code.fromInline("def handler(e, c): return None"),
    });
    monitoring.monitorLambda(fn);
    return Template.fromStack(stack);
  }

  it("emits a CloudWatch dashboard", () => {
    synth().resourceCountIs("AWS::CloudWatch::Dashboard", 1);
  });

  it("emits a Lambda fault-count alarm with the configured name prefix", () => {
    synth().hasResourceProperties("AWS::CloudWatch::Alarm", {
      AlarmName: Match.stringLikeRegexp("^coa-test"),
    });
  });

  it("methods are chainable (return this)", () => {
    const app = new cdk.App();
    const stack = new cdk.Stack(app, "ChainStack");
    const monitoring = new SclMonitoring(stack, "Monitoring", {
      alarmNamePrefix: "coa-test",
    });
    expect(monitoring.monitorClusterCpuMem("some-cluster", "vkg")).toBe(monitoring);
  });

  it("names the dashboard from the alarm prefix (not the literal 'Facade')", () => {
    synth().hasResourceProperties("AWS::CloudWatch::Dashboard", {
      DashboardName: "coa-test",
    });
  });
});
