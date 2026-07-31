// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * E2E environment resolution. Reads the target URL and test-user credentials
 * from env vars (never hardcoded): E2E_BASE_URL, E2E_USERNAME, E2E_PASSWORD.
 */

export interface E2EEnv {
  baseURL: string;
  username: string;
  password: string;
}

/** Resolved env, or null when any required var is missing (callers test.skip). */
export function readE2EEnv(): E2EEnv | null {
  const baseURL = process.env.E2E_BASE_URL;
  const username = process.env.E2E_USERNAME;
  const password = process.env.E2E_PASSWORD;

  if (!baseURL || !username || !password) {
    return null;
  }
  return { baseURL, username, password };
}

/** Like readE2EEnv but throws — used by auth setup, which must fail fast. */
export function requireE2EEnv(): E2EEnv {
  const env = readE2EEnv();
  if (!env) {
    throw new Error(
      "E2E environment is not configured. Set E2E_BASE_URL, E2E_USERNAME and E2E_PASSWORD.",
    );
  }
  return env;
}

/** Reason used in test.skip(...) when the env is absent. */
export const MISSING_ENV_REASON =
  "E2E env not configured (E2E_BASE_URL / E2E_USERNAME / E2E_PASSWORD) — skipping";

/** Glue connection config for the source lifecycle test. */
export interface GlueSourceEnv {
  catalogId: string;
  databaseName: string;
}

// Known-good "hcp360" Glue database on the dev environment (catalog = account).
const DEFAULT_GLUE_CATALOG_ID = "839001574554";
const DEFAULT_GLUE_DATABASE_NAME = "hcp360";

/** Resolve the Glue source config (env override or dev defaults). */
export function readGlueSourceEnv(): GlueSourceEnv {
  return {
    catalogId: process.env.E2E_GLUE_CATALOG_ID ?? DEFAULT_GLUE_CATALOG_ID,
    databaseName:
      process.env.E2E_GLUE_DATABASE_NAME ?? DEFAULT_GLUE_DATABASE_NAME,
  };
}
