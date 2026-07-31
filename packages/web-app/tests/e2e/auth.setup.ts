// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { test as setup } from "@playwright/test";
import { LoginPage } from "./pages/LoginPage";
import { readE2EEnv, MISSING_ENV_REASON } from "./fixtures/env";

/**
 * Auth setup project: performs the interactive Cognito OIDC login once and
 * persists the session as storageState so feature specs start authenticated.
 * Skips (no stored state) when the env is unconfigured, so dependent projects
 * skip too and the suite stays green.
 */

const STORAGE_STATE = "tests/e2e/.auth/user.json";

setup("authenticate", async ({ page }) => {
  const env = readE2EEnv();
  setup.skip(!env, MISSING_ENV_REASON);

  // Allow extra time for IdP redirects and token exchange.
  setup.setTimeout(90_000);

  const login = new LoginPage(page);
  await login.login(env!.username, env!.password);

  // oidc-client-ts stores tokens in origin-scoped storage; snapshot the full
  // state (cookies + localStorage) for reuse.
  await page.context().storageState({ path: STORAGE_STATE });
});
