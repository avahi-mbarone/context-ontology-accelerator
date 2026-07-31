# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""Thin wrapper around Amazon Bedrock for LLM invocations."""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass

import boto3
from botocore.config import Config

logger = logging.getLogger(__name__)

DEFAULT_MODEL_ID = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
_DEFAULT_READ_TIMEOUT = 90
_DEFAULT_GUARDRAIL_VERSION = "DRAFT"

_DEFAULT_MAX_INPUT_CHARS = 200_000

_GUARDRAIL_POLICY_PATHS = [
    ("topicPolicy", "topics"),
    ("contentPolicy", "filters"),
    ("wordPolicy", "customWords"),
    ("wordPolicy", "managedWordLists"),
    ("sensitiveInformationPolicy", "piiEntities"),
    ("sensitiveInformationPolicy", "regexes"),
]


def _assessment_has_block(assessment: dict) -> bool:
    """Check if a guardrail assessment contains any BLOCKED action."""
    try:
        return any(
            item.get("action") == "BLOCKED"
            for policy_key, items_key in _GUARDRAIL_POLICY_PATHS
            for item in assessment.get(policy_key, {}).get(items_key, [])
        )
    except (TypeError, AttributeError):
        return False


class GuardrailBlockedError(Exception):
    """Raised when a Bedrock Guardrail blocks the LLM response."""


class InputTooLargeError(ValueError):
    """Raised when the combined prompt exceeds the configured input-size cap."""


@dataclass(frozen=True)
class BedrockInvocationResult:
    """Result of a Bedrock invocation including parsed content and usage."""

    result: dict | list
    input_tokens: int
    output_tokens: int
    latency_ms: float


class BedrockClient:
    """Invokes Bedrock models for metadata enrichment via the Converse API.

    Args:
        region: AWS region for Bedrock client (defaults to AWS_REGION env var or us-east-1).
        model_id: Bedrock model identifier (defaults to Claude Haiku 4.5).
        read_timeout: HTTP read timeout in seconds (default 90).
        guardrail_id: Optional Bedrock Guardrail identifier.
        guardrail_version: Guardrail version (default DRAFT).
        max_input_chars: Maximum combined prompt length in characters (default 200,000).
            Requests exceeding this raise InputTooLargeError.
    """

    def __init__(
        self,
        region: str | None = None,
        model_id: str = DEFAULT_MODEL_ID,
        read_timeout: int = _DEFAULT_READ_TIMEOUT,
        guardrail_id: str | None = None,
        guardrail_version: str | None = None,
        max_input_chars: int = _DEFAULT_MAX_INPUT_CHARS,
    ) -> None:
        """Build the Bedrock runtime client with adaptive retries (see class Args)."""
        self._region = region or os.getenv("AWS_REGION", "us-east-1")
        self._model_id = model_id
        self._guardrail_id = guardrail_id
        self._guardrail_version = guardrail_version or _DEFAULT_GUARDRAIL_VERSION
        self._max_input_chars = max_input_chars
        self._client = boto3.client(
            "bedrock-runtime",
            region_name=self._region,
            config=Config(
                retries={"mode": "adaptive", "max_attempts": 3},
                read_timeout=read_timeout,
            ),
        )

    @staticmethod
    def _check_guardrail_blocked(guardrail_trace: dict) -> bool:
        """Determine if a guardrail trace indicates BLOCK (not just ANONYMIZE)."""
        if not guardrail_trace:
            return True

        for assessment in guardrail_trace.get("inputAssessment", {}).values():
            if _assessment_has_block(assessment):
                return True

        for assessments in guardrail_trace.get("outputAssessments", {}).values():
            for assessment in assessments:
                if _assessment_has_block(assessment):
                    return True

        return False

    def invoke(self, system_prompt: str, user_prompt: str, max_tokens: int = 4096) -> BedrockInvocationResult:
        """Call Bedrock via Converse API, parse JSON response, and return result with token usage + latency."""
        input_chars = len(system_prompt) + len(user_prompt)
        if input_chars > self._max_input_chars:
            logger.warning("Bedrock input too large: %d chars (limit %d)", input_chars, self._max_input_chars)
            raise InputTooLargeError(
                f"Combined prompt is {input_chars} chars, exceeds limit of {self._max_input_chars}"
            )
        start = time.monotonic()
        kwargs = {
            "modelId": self._model_id,
            "messages": [{"role": "user", "content": [{"text": user_prompt}]}],
            "system": [{"text": system_prompt}],
            "inferenceConfig": {"maxTokens": max_tokens},
        }
        if self._guardrail_id:
            kwargs["guardrailConfig"] = {
                "guardrailIdentifier": self._guardrail_id,
                "guardrailVersion": self._guardrail_version,
                "trace": "enabled",
            }

        try:
            response = self._client.converse(**kwargs)
        except self._client.exceptions.ClientError as e:
            logger.error("Bedrock API call failed: %s", e)
            raise
        except Exception as e:
            logger.error("Unexpected error invoking Bedrock: %s", e)
            raise

        latency_ms = (time.monotonic() - start) * 1000

        try:
            stop_reason = response.get("stopReason")
            usage = response.get("usage", {})
            input_tokens = usage.get("inputTokens", 0)
            output_tokens = usage.get("outputTokens", 0)
            output_message = response["output"]["message"]
            content_blocks = output_message.get("content", [])
            logger.info(
                "Bedrock response: model=%s stop_reason=%s usage=%s content_blocks=%d",
                self._model_id,
                stop_reason,
                usage,
                len(content_blocks),
            )

            if stop_reason in ("guardrail_intervened", "guardrail"):
                guardrail_trace = response.get("trace", {}).get("guardrail", {})
                blocked = self._check_guardrail_blocked(guardrail_trace)

                if blocked:
                    logger.warning(
                        "Guardrail blocked response: model=%s guardrail=%s",
                        self._model_id,
                        self._guardrail_id,
                    )
                    raise GuardrailBlockedError(f"Guardrail {self._guardrail_id} blocked the response")

                # Intervened without blocking — the response is still usable but
                # matched values were substituted with placeholders (e.g.
                # "{NAME}"). Note this masks values, it does not drop fields, so
                # it cannot by itself explain a wholly missing output field.
                logger.warning(
                    "Guardrail intervened without blocking (values masked): model=%s guardrail=%s",
                    self._model_id,
                    self._guardrail_id,
                )

            if not content_blocks:
                logger.error("Bedrock returned no content blocks")
                raise ValueError("Bedrock returned no content blocks")
            content = content_blocks[0]["text"]
            if not content.strip():
                logger.error("Bedrock returned empty content")
                raise ValueError("Bedrock returned empty response")
            text = content.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1] if "\n" in text else text[3:]
                if text.endswith("```"):
                    text = text[:-3]
                text = text.strip()
            result = json.loads(text)
            return BedrockInvocationResult(
                result=result,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                latency_ms=latency_ms,
            )
        except GuardrailBlockedError:
            raise
        except (KeyError, IndexError, json.JSONDecodeError) as e:
            logger.error("Failed to parse Bedrock response: %s", e)
            raise ValueError(f"Invalid Bedrock response format: {e}") from e
