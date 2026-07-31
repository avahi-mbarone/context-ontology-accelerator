// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { expect, type Page } from "@playwright/test";

/**
 * Page Object for platform Grants/Roles on the Identity page (/identity).
 * The Members tab lists grants and has a "Grant access" modal (Type / Email|
 * Name / Platform role); the Roles tab lists platform roles.
 */
export class GrantsPage {
  constructor(private readonly page: Page) {}

  async goto(): Promise<void> {
    await this.page.goto("/identity");
    await expect(
      this.page.getByRole("heading", { name: "Identity", level: 1 }),
    ).toBeVisible();
  }

  async expectMembersTable(): Promise<void> {
    await expect(
      this.page.getByRole("table", { name: "Platform members" }),
    ).toBeVisible();
    await expect(
      this.page.getByRole("button", { name: "Grant access" }),
    ).toBeVisible();
  }

  rowByPrincipal(principalId: string) {
    return this.page.getByRole("row").filter({ hasText: principalId });
  }

  /** Filter the members table to a principal (the list is paginated). */
  async filterMembers(text: string): Promise<void> {
    await this.page.getByPlaceholder("Find members").fill(text);
    await this.page.waitForTimeout(500); // let the client-side filter settle
  }

  /**
   * Grant a platform role to a user (email), selecting the first role.
   * Cloudscape Select triggers are buttons whose text is the placeholder, so
   * they're opened via getByText rather than getByPlaceholder.
   */
  async grantRoleToUser(email: string): Promise<void> {
    await this.page.getByRole("button", { name: "Grant access" }).click();
    const modal = this.page.getByRole("dialog");
    await expect(modal).toBeVisible();

    await modal.getByPlaceholder("user@example.com").fill(email);
    await modal.getByText("Select a platform role").click();
    await this.page.getByRole("option").first().click();

    await modal.getByRole("button", { name: "Grant" }).click();
    await expect(modal).toBeHidden();
  }

  async expectGranted(email: string): Promise<void> {
    await this.filterMembers(email);
    await expect(this.rowByPrincipal(email)).toBeVisible({ timeout: 15_000 });
  }

  /** Revoke a principal's grant via the confirmation modal (teardown). */
  async revoke(email: string): Promise<void> {
    await this.filterMembers(email);
    await this.rowByPrincipal(email).getByRole("checkbox").check();
    await this.page.getByRole("button", { name: "Revoke" }).first().click();
    const modal = this.page.getByRole("dialog");
    await expect(modal).toBeVisible();
    await modal.getByRole("button", { name: "Revoke" }).click();
    await expect(modal).toBeHidden();
  }

  async openRolesTab(): Promise<void> {
    await this.page.getByRole("tab", { name: "Roles" }).click();
    await expect(
      this.page.getByRole("heading", { name: "Platform roles" }),
    ).toBeVisible();
  }
}
