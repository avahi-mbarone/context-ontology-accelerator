// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { test } from "../../fixtures/test";
import { readE2EEnv, MISSING_ENV_REASON } from "../../fixtures/env";

/**
 * Namespace lifecycle: create, view, archive, reactivate, then delete as
 * teardown. Unique name per worker so parallel runs never collide.
 */
test.describe("namespaces: lifecycle", () => {
  test.skip(!readE2EEnv(), MISSING_ENV_REASON);

  // Create/status changes provision/teardown backend resources — allow time.
  test.setTimeout(180_000);

  test("create, view, archive, reactivate, delete", async ({
    namespacesPage,
    uniqueName,
  }) => {
    const name = uniqueName("namespace");

    await namespacesPage.gotoList();
    await namespacesPage.create(name);

    await namespacesPage.openDetails(name);

    await namespacesPage.gotoList();
    await namespacesPage.archive(name);
    await namespacesPage.reactivate(name);

    // Delete is part of the lifecycle (must archive first); the fixture's
    // teardown is a safety net if a step above fails early.
    await namespacesPage.archive(name);
    await namespacesPage.delete(name);
  });
});
