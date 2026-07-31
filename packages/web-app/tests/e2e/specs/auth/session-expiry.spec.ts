// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { test } from "../../fixtures/test";
import { LoginPage } from "../../pages/LoginPage";
import { readE2EEnv, MISSING_ENV_REASON } from "../../fixtures/env";

/**
 * Verifies a lost/expired session routes back to the login gate. Removing the
 * oidc-client-ts `oidc.user:*` storage entry simulates session loss; on reload
 * the Auth gate finds no user and redirects to /login.
 */
test.describe("auth: session expiry", () => {
  test("redirects to login when the session is gone", async ({ page }) => {
    const env = readE2EEnv();
    test.skip(!env, MISSING_ENV_REASON);

    const login = new LoginPage(page);
    await login.login(env!.username, env!.password);

    // Drop every oidc-client-ts entry from both storages.
    await page.evaluate(() => {
      for (const store of [window.localStorage, window.sessionStorage]) {
        for (const key of Object.keys(store)) {
          if (key.startsWith("oidc.")) store.removeItem(key);
        }
      }
    });

    await page.goto("/namespaces");
    await login.expectLoggedOut();
  });
});
