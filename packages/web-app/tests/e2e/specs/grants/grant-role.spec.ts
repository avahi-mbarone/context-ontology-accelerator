// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { test } from "../../fixtures/test";
import { readE2EEnv, MISSING_ENV_REASON } from "../../fixtures/env";

/**
 * Grants/Roles (Identity page). Read-only check that the Members and Roles tabs
 * render — deterministic and mutates no shared state.
 */
test.describe("grants: identity", () => {
  test.skip(!readE2EEnv(), MISSING_ENV_REASON);
  test.setTimeout(60_000);

  test("members and roles tabs render", async ({ grantsPage }) => {
    await grantsPage.goto();
    await grantsPage.expectMembersTable();
    await grantsPage.openRolesTab();
  });

  /**
   * Deferred: grant a role, verify, then revoke. Against shared dev this is
   * non-deterministic and risks a leftover grant — the members list is an
   * eventually-consistent GSI query and the TextFilter only searches loaded
   * pages (size 25), so a new grant on an unfetched page is invisible to both
   * the verify and the revoke teardown. Re-enable once members search hits the
   * backend or an isolated test account exists.
   */
  test.fixme("grant a role and verify it appears, then revoke", async ({
    grantsPage,
    uniqueName,
  }) => {
    const email = `${uniqueName("grant").replace(/[^a-z0-9-]/g, "")}@example.com`;

    await grantsPage.goto();
    await grantsPage.grantRoleToUser(email);
    await grantsPage.expectGranted(email);
    await grantsPage.openRolesTab();

    // Teardown: back to Members and revoke.
    await grantsPage.goto();
    await grantsPage.revoke(email);
  });
});
