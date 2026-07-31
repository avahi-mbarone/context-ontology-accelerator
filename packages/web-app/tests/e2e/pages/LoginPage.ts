// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { expect, type Page } from "@playwright/test";

/**
 * Page Object for the auth flow. Drives both the app's "Sign in" gate and the
 * external Cognito Hosted UI. Hosted-UI selectors favor `name`-based inputs,
 * which are stable across the classic Hosted UI and the newer Managed Login.
 */
export class LoginPage {
  constructor(private readonly page: Page) {}

  async goto(): Promise<void> {
    await this.page.goto("/");
  }

  get signInButton() {
    return this.page.getByRole("button", { name: "Sign in" });
  }

  /** Full interactive login: app gate → Cognito form → authenticated landing. */
  async login(username: string, password: string): Promise<void> {
    await this.goto();
    await this.signInButton.click();
    await this.completeCognitoHostedUi(username, password);
    await this.expectAuthenticated();
  }

  /**
   * Fill and submit the Cognito Hosted UI form. The classic Hosted UI renders
   * duplicate hidden forms, so selectors are scoped to the *visible* fields.
   */
  async completeCognitoHostedUi(
    username: string,
    password: string,
  ): Promise<void> {
    const usernameField = this.page
      .locator(
        'input[name="username"]:visible, input[type="email"]:visible, input[name="email"]:visible',
      )
      .first();
    await usernameField.waitFor({ state: "visible", timeout: 20_000 });
    await usernameField.fill(username);

    const passwordField = this.page
      .locator('input[name="password"]:visible, input[type="password"]:visible')
      .first();
    await passwordField.fill(password);

    const submit = this.page
      .locator(
        'input[name="signInSubmitButton"]:visible, button[type="submit"]:visible, input[type="submit"]:visible',
      )
      .first();
    await submit.click();
  }

  /**
   * Assert the authenticated landing. The top-nav "User menu" only renders once
   * authenticated, so it's a reliable signal (unlike the product title).
   */
  async expectAuthenticated(): Promise<void> {
    await expect(
      this.page.getByRole("button", { name: "User menu" }),
    ).toBeVisible({ timeout: 30_000 });
  }

  async logout(): Promise<void> {
    await this.page.getByRole("button", { name: "User menu" }).click();
    await this.page.getByText("Sign out", { exact: true }).click();
  }

  async expectLoggedOut(): Promise<void> {
    await expect(this.signInButton).toBeVisible({ timeout: 20_000 });
  }
}
