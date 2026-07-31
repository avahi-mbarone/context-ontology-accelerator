// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { test } from "../../fixtures/test";
import { LoginPage } from "../../pages/LoginPage";
import { readE2EEnv, MISSING_ENV_REASON } from "../../fixtures/env";

/**
 * Verifies sign-out returns the user to the login gate.
 *
 * Deferred (fixme): on dev, sign-out redirects to Cognito `/logout` with a
 * `post_logout_redirect_uri` (the CloudFront origin) that isn't in the app
 * client's allowed sign-out URLs, so Cognito returns `redirect_mismatch`. This
 * is an infra/config bug (auth stack `logoutUrls` must include the deployed
 * CloudFront URL). Re-enable once fixed.
 */
test.describe("auth: logout", () => {
  test.fixme("signs out and returns to the login gate", async ({ page }) => {
    const env = readE2EEnv();
    test.skip(!env, MISSING_ENV_REASON);

    const login = new LoginPage(page);
    await login.login(env!.username, env!.password);
    await login.logout();
    await login.expectLoggedOut();
  });
});
