// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { UserManager, WebStorageStateStore, User } from "oidc-client-ts";

/** OIDC provider configuration for the Authorization Code flow with PKCE. */
export interface OidcConfig {
  /** OIDC provider URL (e.g. `https://cognito-idp.us-east-1.amazonaws.com/us-east-1_XXXXX`). */
  authority: string;
  /** OAuth client ID from the OIDC provider. */
  clientId: string;
  /** Path to redirect after login. @default "/authenticate/" */
  onLoginRedirectPath?: string;
  /** Path to redirect after logout. @default "/" */
  onLogoutRedirectPath?: string;
}

let instance: OIDCProvider | undefined;

/**
 * Singleton OIDC client wrapper using `oidc-client-ts`.
 * Use {@link OIDCProvider.build} to obtain the instance.
 */
export class OIDCProvider {
  readonly userManager: UserManager;
  private readonly logoutRedirectUri: string;
  private readonly clientId: string;

  /** In-memory cache of the latest User, updated via the UserLoaded event. */
  private cachedUser: User | null = null;

  private constructor(config: OidcConfig) {
    const loginRedirect = `${window.location.origin}${config.onLoginRedirectPath ?? "/authenticate/"}`;
    const logoutRedirect = `${window.location.origin}${config.onLogoutRedirectPath ?? "/"}`;
    this.logoutRedirectUri = logoutRedirect;
    this.clientId = config.clientId;

    this.userManager = new UserManager({
      authority: config.authority,
      client_id: config.clientId,
      redirect_uri: loginRedirect,
      post_logout_redirect_uri: logoutRedirect,
      response_type: "code",
      scope: "email openid profile",
      // Proactively renew the token before it expires so an expired/invalid
      // session is detected promptly. When renewal fails, oidc-client-ts emits
      // `silentRenewError` (and ultimately `accessTokenExpired`), which the
      // Auth gate listens for to route the user back to the login page.
      automaticSilentRenew: true,
      userStore: new WebStorageStateStore(),
      stateStore: new WebStorageStateStore(),
    });

    // Keep in-memory cache in sync with background silent renew.
    // When automaticSilentRenew refreshes the token, this fires immediately
    // with the fresh User, so subsequent getIdToken/getAccessToken calls
    // always return the latest tokens without hitting storage.
    this.userManager.events.addUserLoaded((user) => {
      this.cachedUser = user;
    });

    this.userManager.events.addUserUnloaded(() => {
      this.cachedUser = null;
    });
  }

  /** Returns the singleton OIDCProvider, creating it on first call. */
  static build(config: OidcConfig): OIDCProvider {
    if (!instance) {
      instance = new OIDCProvider(config);
    }
    return instance;
  }

  /** Initiates the OIDC login redirect to the identity provider. */
  async authenticate(): Promise<void> {
    await this.userManager.signinRedirect();
  }

  async authenticationCallback(url?: string): Promise<User | undefined> {
    return (await this.userManager.signinCallback(url)) ?? undefined;
  }

  async getUser(): Promise<User | null> {
    return this.userManager.getUser();
  }

  /** Returns the current ID token, silently refreshing if it expires within 120 s. */
  async getIdToken(): Promise<string> {
    // Prefer in-memory cache (kept fresh by UserLoaded event) over storage.
    let user = this.cachedUser ?? (await this.userManager.getUser());

    // Refresh if expired or expiring within 120s
    if (user && user.expires_at && user.expires_at < Date.now() / 1000 + 120) {
      try {
        user = await this.userManager.signinSilent();
        this.cachedUser = user;
      } catch {
        throw new Error("Token refresh failed. Please sign in again.");
      }
    }

    const token = user?.id_token;
    if (!token) throw new Error("Auth token is empty.");
    return token;
  }

  /** Returns the current access token, silently refreshing if it expires within 120 s. */
  async getAccessToken(): Promise<string> {
    let user = this.cachedUser ?? (await this.userManager.getUser());

    // Refresh if expired or expiring within 120s
    if (user && user.expires_at && user.expires_at < Date.now() / 1000 + 120) {
      try {
        user = await this.userManager.signinSilent();
        this.cachedUser = user;
      } catch {
        throw new Error("Token refresh failed. Please sign in again.");
      }
    }

    const token = user?.access_token;
    if (!token) throw new Error("Access token is empty.");
    return token;
  }

  /**
   * Revokes the current refresh token at the identity provider so it can no
   * longer be used to mint new access/ID tokens after logout. This closes the
   * gap where a stolen refresh token (via XSS, storage compromise, or device
   * access) stays usable until natural expiry despite the user logging out.
   *
   * Best-effort: revocation failures are logged (without token material) and
   * do not block the logout redirect, so the user is always signed out locally.
   *
   * Cognito does not advertise a `revocation_endpoint` in its OIDC discovery
   * document; the revoke endpoint lives on the same Hosted-UI domain as the
   * token endpoint (`/oauth2/revoke`), so we derive it as a fallback. Revoking
   * a refresh token also invalidates the access tokens issued from it.
   */
  private async revokeRefreshToken(): Promise<void> {
    const user = this.cachedUser ?? (await this.userManager.getUser());
    const refreshToken = user?.refresh_token;
    if (!refreshToken) return;

    let revocationUrl = await this.userManager.metadataService
      .getRevocationEndpoint(true)
      .catch(() => undefined);

    if (!revocationUrl) {
      const tokenEndpoint = await this.userManager.metadataService
        .getTokenEndpoint(true)
        .catch(() => undefined);
      if (tokenEndpoint) {
        revocationUrl = tokenEndpoint.replace(
          /\/oauth2\/token\/?$/,
          "/oauth2/revoke",
        );
      }
    }
    if (!revocationUrl) {
      console.error("Token revocation skipped: no revocation endpoint found.");
      return;
    }

    const body = new URLSearchParams({
      token: refreshToken,
      client_id: this.clientId,
    });
    const response = await fetch(revocationUrl, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: body.toString(),
    });
    // Never log token material — status only.
    if (!response.ok) {
      console.error(`Token revocation failed: HTTP ${response.status}`);
    }
  }

  /** Signs the user out and redirects to the post-logout URI. */
  async signOut(): Promise<void> {
    // Revoke the refresh token at the IdP BEFORE clearing local state so a
    // stolen token cannot mint new tokens after logout. Best-effort — never
    // block the local sign-out on a revocation error.
    try {
      await this.revokeRefreshToken();
    } catch (error) {
      console.error("Token revocation error during logout:", error);
    }
    await this.userManager.clearStaleState();
    await this.userManager.removeUser();
    await this.userManager.signoutRedirect({
      post_logout_redirect_uri: this.logoutRedirectUri,
      extraQueryParams: {
        logout_uri: this.logoutRedirectUri,
        redirect_uri: this.logoutRedirectUri,
        response_type: "code",
      },
    });
  }
}
