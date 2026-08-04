// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { test } from "../../fixtures/test";
import {
  readE2EEnv,
  readGlueSourceEnv,
  requireGlueSourceEnv,
  MISSING_ENV_REASON,
  MISSING_GLUE_ENV_REASON,
} from "../../fixtures/env";

/**
 * Full Glue source + namespace lifecycle in the required teardown order:
 * onboard → delete source → archive namespace → delete namespace.
 *
 * Slow (real Glue scan + enrichment, several minutes), so it's gated behind
 * E2E_SLOW and carries a generous timeout — not for the fast per-MR lane.
 */
test.describe("data-sources: glue source lifecycle", () => {
  test.skip(!readE2EEnv(), MISSING_ENV_REASON);
  test.skip(!readGlueSourceEnv(), MISSING_GLUE_ENV_REASON);
  test.skip(
    !process.env.E2E_SLOW,
    "slow lifecycle test — set E2E_SLOW=1 to run",
  );
  test.setTimeout(900_000);

  test("onboard, delete source, archive namespace, delete namespace", async ({
    namespacesPage,
    sourcesPage,
    uniqueName,
  }) => {
    const ns = uniqueName("ns-glue");
    const srcName = uniqueName("src-glue");
    const glue = requireGlueSourceEnv();

    await namespacesPage.gotoList();
    await namespacesPage.create(ns);
    await namespacesPage.openDetails(ns);
    const nsId = namespacesPage.currentNamespaceId();

    // Onboard the Glue source (scans to PENDING_REVIEW in the background).
    await sourcesPage.onboardGlue(nsId, srcName, {
      catalogId: glue.catalogId,
      databaseName: glue.databaseName,
    });

    // Delete the source while the namespace is still ACTIVE.
    await sourcesPage.deleteSource(nsId, srcName);

    // Archive, then delete the now source-free namespace.
    await namespacesPage.gotoList();
    await namespacesPage.archive(ns);
    await namespacesPage.delete(ns);
  });
});
