import crypto from "node:crypto";

import { Inject, Injectable, Logger } from "@nestjs/common";

import { GetOpenIdTokenForDeveloperIdentityCommand } from "@aws-sdk/client-cognito-identity";
import { ConfidentialClientApplication } from "@azure/msal-node";
import { Client } from "@microsoft/microsoft-graph-client";
import { User } from "@microsoft/microsoft-graph-types";
import { v4 as uuidv4 } from "uuid";

import { CognitoCredential } from "@shelfalign/schema/auth/credentials/cognito";
import { MicrosoftProviderConfig } from "@shelfalign/schema/auth/providers/microsoft";

import { EnvType, registerEnv } from "@/common/utils/env";
import { createDigest } from "@/common/utils/error";
import { CognitoService } from "@/providers/cognito/cognito.service";

import { BaseProvider } from "./base.provider";

@Injectable()
export class MicrosoftProvider extends BaseProvider<
  MicrosoftProviderConfig,
  User
> {
  private readonly logger = new Logger(MicrosoftProvider.name);
  private readonly baseUrl: string;

  constructor(
    @Inject(registerEnv.KEY)
    private readonly env: EnvType,
    private readonly cognitoService: CognitoService,
  ) {
    super();

    if (this.env.NODE_ENV === "production") {
      this.baseUrl = "https://api.shelfalign.kr";
    } else if (this.env.NODE_ENV === "staging") {
      this.baseUrl = "https://stg-api.shelfalign.kr";
    } else if (this.env.NODE_ENV === "development") {
      this.baseUrl = "https://dev-api.shelfalign.kr";
    } else {
      this.baseUrl = `http://localhost:${this.env.PORT}`;
    }
  }

  private async getClientFromCognito(
    clientId: string,
    tenantId: string,
    credential: CognitoCredential,
  ) {
    return new ConfidentialClientApplication({
      auth: {
        clientId,
        authority: `https://login.microsoftonline.com/${tenantId}`,
        clientAssertion: async () => {
          const cognitoResponse = await this.cognitoService.client.send(
            new GetOpenIdTokenForDeveloperIdentityCommand({
              IdentityPoolId: credential.identityPoolId,
              Logins: {
                [credential.providerName]: credential.loginName,
              },
            }),
          );

          if (!cognitoResponse.Token) {
            throw new Error("Empty cognito token");
          }

          return cognitoResponse.Token;
        },
      },
    });
  }

  override async getToken(
    providerId: string,
    config: MicrosoftProviderConfig,
    code: string,
    codeVerifier: string,
  ) {
    try {
      if (config.credential.type === "cognito") {
        const client = await this.getClientFromCognito(
          config.clientId,
          config.tenantId,
          config.credential,
        );
        const token = await client.acquireTokenByCode({
          code,
          scopes: ["openid", "profile", "email", "User.Read"],
          redirectUri: `${this.baseUrl}/auth/signin/${providerId}/callback`,
          codeVerifier,
        });
        return { result: true, token: token.accessToken } as const;
      }
    } catch (error) {
      const digest = createDigest(
        this.logger,
        `Token acquisition failed: ${error instanceof Error ? error.message : String(error)}`,
      );
      return { result: false, digest } as const;
    }

    const digest = createDigest(
      this.logger,
      `Unsupported credential type "${config.credential.type}" for Microsoft provider`,
    );
    return { result: false, digest } as const;
  }

  override async getAuthorizeUrl(
    providerId: string,
    config: MicrosoftProviderConfig,
  ) {
    const state = uuidv4();
    const codeVerifier = uuidv4();
    const codeChallenge = crypto
      .createHash("sha256")
      .update(codeVerifier)
      .digest("base64url");

    const url = new URL(
      `https://login.microsoftonline.com/${config.tenantId}/oauth2/v2.0/authorize`,
    );
    url.searchParams.append("client_id", config.clientId);
    url.searchParams.append("response_type", "code");
    url.searchParams.append(
      "redirect_uri",
      `${this.baseUrl}/auth/signin/${providerId}/callback`,
    );
    url.searchParams.append(
      "scope",
      ["openid", "profile", "email", "User.Read"].join(" "),
    );
    url.searchParams.append("response_mode", "query");
    url.searchParams.append("state", state);
    if (config.domainHint) {
      url.searchParams.append("domain_hint", config.domainHint);
    }
    url.searchParams.append("code_challenge", codeChallenge);
    url.searchParams.append("code_challenge_method", "S256");

    return { state, codeVerifier, url: url.toString() };
  }

  override async getProfile(accessToken: string) {
    try {
      const graphClient = Client.init({
        authProvider: (done) => {
          done(null, accessToken);
        },
      });
      const profile = await graphClient.api("/me").get();
      return { result: true, profile: profile as User } as const;
    } catch (error) {
      const digest = createDigest(
        this.logger,
        `Failed to fetch profile: ${error instanceof Error ? error.message : String(error)}`,
      );
      return { result: false, digest } as const;
    }
  }

  override async getBaseProfile(profile: User) {
    if (!profile.id) {
      const digest = createDigest(this.logger, "No user ID in profile");
      return { result: false, digest } as const;
    }

    if (!profile.mail) {
      const digest = createDigest(this.logger, "No email in profile");
      return { result: false, digest } as const;
    }

    return {
      result: true,
      profile: {
        id: profile.id,
        email: profile.mail,
        name: profile.displayName || "사용자",
      },
    } as const;
  }
}
