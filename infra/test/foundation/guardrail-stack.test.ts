// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import * as cdk from "aws-cdk-lib";
import { Template } from "aws-cdk-lib/assertions";
import { GuardrailStack } from "../../lib/stacks/foundation";
import { DEFAULT_RESOURCE_PREFIX, DEFAULT_ENV } from "../../lib/constants";

const TEST_CONTEXT = {
  resource_prefix: DEFAULT_RESOURCE_PREFIX,
  env: DEFAULT_ENV,
};

describe("GuardrailStack", () => {
  let template: Template;

  beforeAll(() => {
    const app = new cdk.App({ context: TEST_CONTEXT });
    template = Template.fromStack(new GuardrailStack(app, "TestGuardrail"));
  });

  test("creates Bedrock Guardrail with content filters", () => {
    template.hasResourceProperties("AWS::Bedrock::Guardrail", {
      Name: `${DEFAULT_RESOURCE_PREFIX}-${DEFAULT_ENV}-guardrail`,
      ContentPolicyConfig: {
        FiltersConfig: [
          { Type: "SEXUAL", InputStrength: "HIGH", OutputStrength: "HIGH" },
          { Type: "VIOLENCE", InputStrength: "HIGH", OutputStrength: "HIGH" },
          { Type: "HATE", InputStrength: "HIGH", OutputStrength: "HIGH" },
          { Type: "INSULTS", InputStrength: "HIGH", OutputStrength: "HIGH" },
          { Type: "MISCONDUCT", InputStrength: "HIGH", OutputStrength: "HIGH" },
          {
            Type: "PROMPT_ATTACK",
            InputStrength: "HIGH",
            OutputStrength: "NONE",
          },
        ],
      },
    });
  });

  test("creates PII anonymization config on the primary guardrail", () => {
    template.hasResourceProperties("AWS::Bedrock::Guardrail", {
      Name: `${DEFAULT_RESOURCE_PREFIX}-${DEFAULT_ENV}-guardrail`,
      SensitiveInformationPolicyConfig: {
        PiiEntitiesConfig: [
          { Type: "EMAIL", Action: "ANONYMIZE" },
          { Type: "PHONE", Action: "ANONYMIZE" },
          { Type: "NAME", Action: "ANONYMIZE" },
          { Type: "US_SOCIAL_SECURITY_NUMBER", Action: "ANONYMIZE" },
          { Type: "CREDIT_DEBIT_CARD_NUMBER", Action: "ANONYMIZE" },
        ],
      },
    });
  });

  test("provisions exactly two guardrails", () => {
    template.resourceCountIs("AWS::Bedrock::Guardrail", 2);
  });

  test("retrieval guardrail has NO PII policy (content screening only)", () => {
    const guardrails = template.findResources("AWS::Bedrock::Guardrail");
    const retrieval = Object.values(guardrails).find(
      (r) =>
        r.Properties?.Name ===
        `${DEFAULT_RESOURCE_PREFIX}-${DEFAULT_ENV}-retrieval-guardrail`,
    );
    expect(retrieval).toBeDefined();
    // Anonymizing PII during document/chunk screening would quarantine any
    // document containing a name and strip named entities from the KG.
    expect(
      retrieval?.Properties?.SensitiveInformationPolicyConfig,
    ).toBeUndefined();
    // It must still screen for prompt injection.
    const filters =
      retrieval?.Properties?.ContentPolicyConfig?.FiltersConfig ?? [];
    expect(
      filters.some((f: { Type: string }) => f.Type === "PROMPT_ATTACK"),
    ).toBe(true);
  });

  test("creates SSM params for guardrail", () => {
    template.hasResourceProperties("AWS::SSM::Parameter", {
      Name: `/${DEFAULT_RESOURCE_PREFIX}/bedrock/guardrail-id`,
    });
    template.hasResourceProperties("AWS::SSM::Parameter", {
      Name: `/${DEFAULT_RESOURCE_PREFIX}/bedrock/guardrail-version`,
    });
  });

  test("has no Cognito resources", () => {
    template.resourceCountIs("AWS::Cognito::UserPool", 0);
  });
});
