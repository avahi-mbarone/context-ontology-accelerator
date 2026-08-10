// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * AgentCore Runtime requires `X-Amzn-Bedrock-AgentCore-Runtime-Session-Id` to
 * be at least 33 characters (enforced server-side — a short value 400s with
 * "Member must have length greater than or equal to 33").
 *
 * The OIDC `sub` claim is NOT guaranteed to satisfy this: Cognito issues UUIDs
 * (36 chars, always safe), but other IdPs — e.g. Midway/federate — issue short
 * human-readable usernames (e.g. "noahpaig", 8 chars), which fail the AgentCore
 * constraint outright.
 */
const MIN_RUNTIME_SESSION_ID_LENGTH = 33;

/**
 * Derive a stable, ≥33-char AgentCore runtime session id from an OIDC `sub`.
 * Deterministic per `sub` (same user always maps to the same session id, so
 * AgentCore's sticky routing still groups a user's requests together).
 *
 * Returns undefined if `sub` is falsy (caller omits the header entirely).
 */
export function deriveRuntimeSessionId(
  sub: string | undefined,
): string | undefined {
  if (!sub) return undefined;
  return sub.padEnd(MIN_RUNTIME_SESSION_ID_LENGTH, "0");
}
