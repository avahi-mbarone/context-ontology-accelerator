// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { test } from "../../fixtures/test";
import { readE2EEnv, MISSING_ENV_REASON } from "../../fixtures/env";

/**
 * System Health smoke test: the page loads, the health API is reachable and
 * resolves, the per-backend cards render, and the system reports operational.
 * Read-only — mutates no state.
 */
test.describe("system-health: status", () => {
  test.skip(!readE2EEnv(), MISSING_ENV_REASON);
  test.setTimeout(60_000);

  test("page loads, API resolves, all systems operational", async ({
    systemHealthPage,
  }) => {
    await systemHealthPage.goto();
    await systemHealthPage.expectResolved();
    await systemHealthPage.expectComponentCards();
    await systemHealthPage.expectAllOperational();
  });
});
