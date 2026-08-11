// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Shared utility for invoking AgentCore /invocations endpoint.
 *
 * Consolidates the OIDC token fetch, header construction, POST request,
 * and SSE frame parsing that was duplicated across use-sessions.ts,
 * use-session-history.ts, and use-playground-stream.ts.
 */
import { OIDCProvider } from "@auth";
import { deriveRuntimeSessionId } from "./runtime-session-id";

export interface AgentCoreRequestOptions {
  /** AgentCore Runtime endpoint URL. */
  queryEndpoint: string;
  /** OIDC config for token retrieval. */
  oidcConfig: { authority: string; clientId: string };
  /** JSON payload to send in the request body. */
  payload: Record<string, unknown>;
  /** Optional AbortSignal for cancellation. */
  signal?: AbortSignal;
  /** Timeout in milliseconds (default: 30000). */
  timeoutMs?: number;
}

export interface AgentCoreResponse {
  /** Parsed JSON from the first SSE data frame (or raw JSON fallback). */
  data: unknown;
}

/** Error thrown when the server returns 401, indicating token expiry. */
export class AuthExpiredError extends Error {
  constructor() {
    super("AuthExpired");
    this.name = "AuthExpiredError";
  }
}

/**
 * Invoke AgentCore /invocations endpoint with OIDC auth and SSE parsing.
 *
 * - Fetches an ID token from the OIDC provider
 * - Sends the payload as POST with Authorization header
 * - Parses the first SSE `data: {json}` frame from the response
 * - Throws AuthExpiredError on 401
 * - Returns null on network errors or empty responses
 */
export async function invokeAgentCore(
  options: AgentCoreRequestOptions,
): Promise<unknown> {
  const {
    queryEndpoint,
    oidcConfig,
    payload,
    signal,
    timeoutMs = 30000,
  } = options;

  // Build an internal AbortController that respects both caller signal and timeout
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

  // Link caller's signal to our controller
  if (signal) {
    if (signal.aborted) {
      clearTimeout(timeoutId);
      return null;
    }
    signal.addEventListener("abort", () => controller.abort(), { once: true });
  }

  try {
    const provider = OIDCProvider.build(oidcConfig);
    const token = await provider.getIdToken();
    if (!token) return null;
    const user = await provider.getUser();
    const runtimeSessionId = deriveRuntimeSessionId(user?.profile?.sub);

    let response: Response;
    try {
      response = await fetch(queryEndpoint, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
          ...(runtimeSessionId && {
            "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id": runtimeSessionId,
          }),
        },
        body: JSON.stringify(payload),
        signal: controller.signal,
      });
    } catch {
      return null;
    }

    if (!response.ok) {
      if (response.status === 401) {
        throw new AuthExpiredError();
      }
      return null;
    }

    return await parseFirstSseFrame(response);
  } finally {
    clearTimeout(timeoutId);
  }
}

/**
 * Parse the first SSE `data: {json}` frame from a Response body.
 * Falls back to parsing the entire body as raw JSON if no SSE frame is found.
 */
export async function parseFirstSseFrame(response: Response): Promise<unknown> {
  const reader = response.body?.getReader();
  if (!reader) return null;

  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
  }

  const lines = buffer.split("\n");
  for (const line of lines) {
    if (line.startsWith("data: ")) {
      try {
        return JSON.parse(line.slice(6));
      } catch {
        // continue to next line
      }
    }
  }
  // Fallback: try raw JSON
  try {
    return JSON.parse(buffer.trim());
  } catch {
    return null;
  }
}
