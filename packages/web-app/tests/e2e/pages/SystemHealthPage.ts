// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { expect, type Page } from "@playwright/test";

/**
 * Page Object for the System Health page (/system-health).
 * Renders GET /system-health: an "Overall Status" indicator plus a card per
 * backend component. Read-only — asserts the UI + health API wiring.
 */
export class SystemHealthPage {
  constructor(private readonly page: Page) {}

  async goto(): Promise<void> {
    await this.page.goto("/system-health");
    await expect(
      this.page.getByRole("heading", { name: "System Health", level: 1 }),
    ).toBeVisible();
  }

  /**
   * Wait for the overall status to resolve off the initial "Checking…" state,
   * and assert the health API was reachable (not the "Unreachable" error).
   */
  async expectResolved(): Promise<void> {
    await expect(this.page.getByText("Checking backend health...")).toHaveCount(
      0,
      { timeout: 30_000 },
    );
    await expect(this.page.getByText(/^Unreachable:/)).toHaveCount(0);
  }

  /** Assert the overall status reports all systems operational (healthy). */
  async expectAllOperational(): Promise<void> {
    await expect(this.page.getByText("All systems operational")).toBeVisible({
      timeout: 30_000,
    });
  }

  /** Assert the per-backend cards render. */
  async expectComponentCards(): Promise<void> {
    for (const title of [
      "DynamoDB",
      "Neptune KG",
      "OpenSearch Serverless",
      "Ontology Graph Store",
      "Ontology Vector Store",
      "Bedrock Embeddings",
      "Description LLM",
    ]) {
      await expect(
        this.page.getByRole("heading", { name: title, level: 3 }),
      ).toBeVisible();
    }
  }
}
