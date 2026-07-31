// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import * as cdk from "aws-cdk-lib";
import { Template, Match } from "aws-cdk-lib/assertions";
import { PublicUIConstruct } from "../../lib/constructs/public-ui-construct";
import type { RuntimeConfig } from "@coa/shared";

const TEST_ENV = { account: "123456789012", region: "us-west-2" };

const runtimeConfig: RuntimeConfig = {
  region: "us-west-2",
  stage: "dev",
  authority: "https://cognito-idp.us-west-2.amazonaws.com/us-west-2_abc",
  clientId: "client-abc",
};

const UI_CERT =
  "arn:aws:acm:us-east-1:123456789012:certificate/11111111-2222-3333-4444-555555555555";

function synth(withDomain: boolean): Template {
  const app = new cdk.App();
  const stack = new cdk.Stack(app, "TestUiStack", { env: TEST_ENV });
  new PublicUIConstruct(stack, "UI", {
    runtimeConfig,
    ...(withDomain && {
      uiDomainName: "coa.amazon.com",
      uiCertificateArn: UI_CERT,
    }),
  });
  return Template.fromStack(stack);
}

describe("PublicUIConstruct custom domain", () => {
  it("attaches the alias + ACM cert and enforces TLS 1.2 when configured", () => {
    synth(true).hasResourceProperties("AWS::CloudFront::Distribution", {
      DistributionConfig: Match.objectLike({
        Aliases: ["coa.amazon.com"],
        ViewerCertificate: Match.objectLike({
          AcmCertificateArn: UI_CERT,
          MinimumProtocolVersion: "TLSv1.2_2021",
          SslSupportMethod: "sni-only",
        }),
      }),
    });
  });

  it("uses the default CloudFront certificate (no aliases) when no domain is configured", () => {
    synth(false).hasResourceProperties("AWS::CloudFront::Distribution", {
      DistributionConfig: Match.objectLike({
        Aliases: Match.absent(),
        ViewerCertificate: Match.absent(),
      }),
    });
  });
});
