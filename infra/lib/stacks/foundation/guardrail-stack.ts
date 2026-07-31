// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import * as cdk from "aws-cdk-lib";
import * as bedrock from "aws-cdk-lib/aws-bedrock";
import * as ssm from "aws-cdk-lib/aws-ssm";
import { Construct } from "constructs";
import { SCLStack } from "../../constructs/scl-stack";
import { resolveContext } from "../../context";

/**
 * PII entity configuration for the PRIMARY guardrail only.
 *
 * PII is anonymized (not blocked) at the LLM input/output boundary so that
 * personal data is masked in model responses to agents. It is intentionally
 * NOT applied to the retrieval (content-screening) guardrail: that guardrail
 * screens ingested documents and retrieved chunks, where named entities are
 * the primary payload of the knowledge graph / ontology. Anonymizing there
 * would both destroy KG fidelity and cause every document mentioning a person
 * to be quarantined.
 */
const PII_ENTITIES_CONFIG = [
  {
    type: "EMAIL",
    action: "ANONYMIZE",
    inputAction: "ANONYMIZE",
    outputAction: "ANONYMIZE",
    inputEnabled: true,
    outputEnabled: true,
  },
  {
    type: "PHONE",
    action: "ANONYMIZE",
    inputAction: "ANONYMIZE",
    outputAction: "ANONYMIZE",
    inputEnabled: true,
    outputEnabled: true,
  },
  {
    type: "NAME",
    action: "ANONYMIZE",
    inputAction: "ANONYMIZE",
    outputAction: "ANONYMIZE",
    inputEnabled: true,
    outputEnabled: true,
  },
  {
    type: "US_SOCIAL_SECURITY_NUMBER",
    action: "ANONYMIZE",
    inputAction: "ANONYMIZE",
    outputAction: "ANONYMIZE",
    inputEnabled: true,
    outputEnabled: true,
  },
  {
    type: "CREDIT_DEBIT_CARD_NUMBER",
    action: "ANONYMIZE",
    inputAction: "ANONYMIZE",
    outputAction: "ANONYMIZE",
    inputEnabled: true,
    outputEnabled: true,
  },
];

/**
 * Foundation stack: Amazon Bedrock Guardrails for content safety filtering
 * across all LLM-facing paths (LLD §2.2.4).
 *
 * Two guardrails are provisioned:
 * - Primary: HIGH PROMPT_ATTACK sensitivity for user query evaluation, plus PII
 *   anonymization applied at the LLM input/output boundary (mask PII in responses).
 * - Retrieval: MEDIUM PROMPT_ATTACK sensitivity for retrieved/ingested content
 *   screening (ingestion-time and query-time). Content-safety only — no PII
 *   policy — so document screening never quarantines or masks named entities,
 *   which are the primary payload of the knowledge graph / ontology.
 *
 * Both use standard safeguard tier for better accuracy and cross-region availability.
 */
export class GuardrailStack extends SCLStack {
  public readonly guardrailId: string;
  public readonly retrievalGuardrailId: string;

  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);
    this.addComponentTag("foundation");

    const { ssmPrefix } = resolveContext(this.node);

    // ── Primary guardrail: HIGH sensitivity for user queries ─────────────
    const guardrail = new bedrock.CfnGuardrail(this, "BedrockGuardrail", {
      name: this.prefixed("guardrail"),
      blockedInputMessaging: "Request blocked by content filter.",
      blockedOutputsMessaging: "Response blocked by content filter.",
      contentPolicyConfig: {
        filtersConfig: [
          { type: "SEXUAL", inputStrength: "HIGH", outputStrength: "HIGH" },
          { type: "VIOLENCE", inputStrength: "HIGH", outputStrength: "HIGH" },
          { type: "HATE", inputStrength: "HIGH", outputStrength: "HIGH" },
          { type: "INSULTS", inputStrength: "HIGH", outputStrength: "HIGH" },
          { type: "MISCONDUCT", inputStrength: "HIGH", outputStrength: "HIGH" },
          {
            type: "PROMPT_ATTACK",
            inputStrength: "HIGH",
            outputStrength: "NONE",
          },
        ],
      },
      sensitiveInformationPolicyConfig: {
        piiEntitiesConfig: PII_ENTITIES_CONFIG,
      },
    });

    this.guardrailId = guardrail.attrGuardrailId;

    new ssm.StringParameter(this, "SsmGuardrailId", {
      parameterName: `${ssmPrefix}/bedrock/guardrail-id`,
      stringValue: guardrail.attrGuardrailId,
    });
    new ssm.StringParameter(this, "SsmGuardrailVersion", {
      parameterName: `${ssmPrefix}/bedrock/guardrail-version`,
      stringValue: guardrail.attrVersion,
    });

    new cdk.CfnOutput(this, "GuardrailId", {
      value: guardrail.attrGuardrailId,
    });

    // ── Retrieval guardrail: tuned for business document screening ─────────
    // Used by both ingestion-time (ApplyGuardrail in KG Build) and
    // query-time (ApplyGuardrail before synthesis) content screening.
    // Sensitivity tuned per AWS best practice: "Start HIGH, lower if false
    // positives on representative traffic." Insurance/finance/legal docs
    // trigger MISCONDUCT and VIOLENCE at HIGH confidence on benign content
    // (e.g., "theft", "liability", "damage"). Per-filter tuning:
    //   PROMPT_ATTACK: MEDIUM (core defense; HIGH false-positives on instruction-like business language)
    //   HATE/SEXUAL: HIGH (no legitimate business reason for this content)
    //   VIOLENCE/INSULTS: MEDIUM (legal/insurance docs reference harm/adversarial language)
    //   MISCONDUCT: LOW (insurance docs discuss fraud/theft routinely; only block HIGH-confidence)
    const retrievalGuardrail = new bedrock.CfnGuardrail(
      this,
      "RetrievalGuardrail",
      {
        name: this.prefixed("retrieval-guardrail"),
        blockedInputMessaging: "Retrieved content blocked by filter.",
        blockedOutputsMessaging: "Retrieved content blocked by filter.",
        contentPolicyConfig: {
          filtersConfig: [
            {
              type: "SEXUAL",
              inputStrength: "HIGH",
              outputStrength: "HIGH",
            },
            {
              type: "VIOLENCE",
              inputStrength: "MEDIUM",
              outputStrength: "MEDIUM",
            },
            { type: "HATE", inputStrength: "HIGH", outputStrength: "HIGH" },
            {
              type: "INSULTS",
              inputStrength: "MEDIUM",
              outputStrength: "MEDIUM",
            },
            {
              type: "MISCONDUCT",
              inputStrength: "LOW",
              outputStrength: "LOW",
            },
            {
              type: "PROMPT_ATTACK",
              inputStrength: "MEDIUM",
              outputStrength: "NONE",
            },
          ],
        },
        // NOTE: no sensitiveInformationPolicyConfig here. The retrieval guardrail
        // screens ingested documents + retrieved chunks purely for poisoned /
        // malicious content (prompt injection, harmful categories). PII masking
        // belongs on the PRIMARY guardrail (LLM output boundary); anonymizing PII
        // during content screening would drop every document containing a name
        // and gut KG/ontology construction.
      },
    );

    this.retrievalGuardrailId = retrievalGuardrail.attrGuardrailId;

    new ssm.StringParameter(this, "SsmRetrievalGuardrailId", {
      parameterName: `${ssmPrefix}/bedrock/retrieval-guardrail-id`,
      stringValue: retrievalGuardrail.attrGuardrailId,
    });
    new ssm.StringParameter(this, "SsmRetrievalGuardrailVersion", {
      parameterName: `${ssmPrefix}/bedrock/retrieval-guardrail-version`,
      stringValue: retrievalGuardrail.attrVersion,
    });

    new cdk.CfnOutput(this, "RetrievalGuardrailId", {
      value: retrievalGuardrail.attrGuardrailId,
    });
  }
}
