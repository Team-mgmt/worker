import { Inject, Injectable, Logger } from "@nestjs/common";

import { oauth2, oauth2_v2 } from "@googleapis/oauth2";
import { CodeChallengeMethod, OAuth2Client } from "google-auth-library";
import { v4 as uuidv4 } from "uuid";

import { GoogleProviderConfig } from "@shelfalign/schema/auth/providers/google";

import { EnvType, registerEnv } from "@/common/utils/env";
import { createDigest } from "@/common/utils/error";
import { uuidToBase64Url } from "@/common/utils/string";

import { BaseProvider } from "./base.provider";

@Injectable()
export class GoogleProvider extends BaseProvider<
  GoogleProviderConfig,
  oauth2_v2.Schema$Userinfo
> {
  private readonly logger = new Logger(GoogleProvider.name);
  private readonly baseUrl: string;

  constructor(
    @Inject(registerEnv.KEY)
    private readonly env: EnvType,
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

  override async getToken(
    providerId: string,
    config: GoogleProviderConfig,
    code: string,
    codeVerifier: string,
  ) {
    try {
      if (config.credential.type === "static") {
        const client = new OAuth2Client({
          clientId: config.clientId,
          clientSecret: config.credential.clientSecret,
          redirectUri: `${this.baseUrl}/auth/signin/${uuidToBase64Url(providerId)}/callback`,
        });

        const token = await client.getToken({ code, codeVerifier });

        if (!token.tokens.access_token) {
          const digest = createDigest(
            this.logger,
            "Empty access token received from Google",
          );
          return { result: false, digest } as const;
        }

        return { result: true, token: token.tokens.access_token } as const;
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
      `Unsupported credential type "${config.credential.type}" for Google provider`,
    );
    return { result: false, digest } as const;
  }

  override async getAuthorizeUrl(
    providerId: string,
    config: GoogleProviderConfig,
  ) {
    const state = uuidv4();

    const client = new OAuth2Client({
      clientId: config.clientId,
      redirectUri: `${this.baseUrl}/auth/signin/${uuidToBase64Url(providerId)}/callback`,
    });

    const codeVerifier = await client.generateCodeVerifierAsync();

    const url = client.generateAuthUrl({
      code_challenge: codeVerifier.codeChallenge,
      code_challenge_method: CodeChallengeMethod.S256,
      scope: ["openid", "email", "profile"],
      state,
      hd: config.domainHint,
    });

    return {
      result: true,
      url,
      codeVerifier: codeVerifier.codeVerifier,
      state,
    } as const;
  }

  override async getProfile(accessToken: string) {
    try {
      const client = new OAuth2Client({});
      client.setCredentials({ access_token: accessToken });

      const oauth2Client = oauth2({
        auth: client,
        version: "v2",
      });

      const res = await oauth2Client.userinfo.get();

      if (!res.data || !res.data.id) {
        const digest = createDigest(
          this.logger,
          "Empty profile data received from Google",
        );
        return { result: false, digest } as const;
      }

      return { result: true, profile: res.data } as const;
    } catch (error) {
      const digest = createDigest(
        this.logger,
        `Profile retrieval failed: ${error instanceof Error ? error.message : String(error)}`,
      );
      return { result: false, digest } as const;
    }
  }

  override async getBaseProfile(profile: oauth2_v2.Schema$Userinfo) {
    if (!profile.id || !profile.email) {
      const digest = createDigest(
        this.logger,
        "Incomplete profile data received from Google",
      );
      return { result: false, digest } as const;
    }

    return {
      result: true,
      profile: {
        id: profile.id,
        email: profile.email,
        name: profile.name || "사용자",
      },
    } as const;
  }
}
