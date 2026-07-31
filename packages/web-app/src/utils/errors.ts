// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { ControlPlaneServiceServiceException } from "@coa/control-plane-client";

/**
 * Extract a human-readable message from a thrown API error.
 *
 * The Smithy REST-JSON client sets `message === "UnknownError"` for unmodeled
 * errors and copies unknown response-body fields onto the exception. Our API
 * returns `{ "error": "..." }`, so prefer that field before falling back to
 * the raw `$response.body`.
 */
export function extractErrorMessage(
  err: unknown,
  fallback = "An unexpected error occurred.",
): string {
  if (err instanceof ControlPlaneServiceServiceException) {
    if (err.message && err.message !== "UnknownError") return err.message;

    const anyErr = err as unknown as Record<string, unknown>;
    if (typeof anyErr["error"] === "string") return anyErr["error"];

    const body = (err as unknown as { $response?: { body?: unknown } })
      .$response?.body;
    if (typeof body === "string") {
      try {
        const parsed = JSON.parse(body) as Record<string, unknown>;
        if (typeof parsed.error === "string") return parsed.error;
        if (typeof parsed.message === "string") return parsed.message;
      } catch {
        // body wasn't JSON — ignore
      }
    }
    return fallback;
  }
  if (err instanceof Error && err.message) return err.message;
  return fallback;
}
