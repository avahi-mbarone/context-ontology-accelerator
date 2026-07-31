// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { test } from "../../fixtures/test";
import { readE2EEnv, MISSING_ENV_REASON } from "../../fixtures/env";

/**
 * Playground: SSE streaming, submit query, view streamed response, history,
 * switch namespace, new chat. Model responses can be slow, so timeouts are generous.
 */
test.describe("playground: chat", () => {
  test.skip(!readE2EEnv(), MISSING_ENV_REASON);
  test.setTimeout(120_000);

  test("connect, submit query, view response, history persists, new chat", async ({
    playgroundPage,
  }) => {
    const query = "What data is available?";

    await playgroundPage.goto();
    await playgroundPage.waitForConnected();

    await playgroundPage.submitQuery(query);
    await playgroundPage.expectResponse();

    await playgroundPage.expectInHistory(query);

    // A second turn keeps the first turn visible.
    await playgroundPage.submitQuery("And how many namespaces are there?");
    await playgroundPage.expectInHistory(query);

    // New chat clears history.
    await playgroundPage.newChat();
    await playgroundPage.expectHistoryCleared(query);
  });

  test("switch namespace from the playground", async ({
    playgroundPage,
    namespacesPage,
    uniqueName,
  }) => {
    // Namespace to switch to (cleaned up by the fixture).
    const nsName = uniqueName("pg-ns");
    await namespacesPage.gotoList();
    await namespacesPage.create(nsName);

    await playgroundPage.goto();
    await playgroundPage.waitForConnected();
    await playgroundPage.switchNamespace(nsName);
  });
});
