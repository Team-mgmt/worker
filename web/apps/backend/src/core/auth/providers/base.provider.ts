import { NotImplementedException } from "@nestjs/common";

import {
  AuthorizeUrlResult,
  BaseProfileResult,
  GetProfileResult,
  GetTokenResult,
  ProviderConfig,
} from "@shelfalign/schema/auth/providers/base";

export abstract class BaseProvider<
  Config extends ProviderConfig = ProviderConfig,
  Profile = unknown,
> {
  constructor() {
    if (this.constructor === BaseProvider) {
      throw new NotImplementedException();
    }
  }

  async getToken(
    _providerId: string,
    _config: Config,
    _code: string,
    _codeVerifier: string,
  ): Promise<GetTokenResult> {
    throw new NotImplementedException();
  }

  async getAuthorizeUrl(
    _providerId: string,
    _config: Config,
  ): Promise<AuthorizeUrlResult> {
    throw new NotImplementedException();
  }

  async getProfile(_accessToken: string): Promise<GetProfileResult<Profile>> {
    throw new NotImplementedException();
  }

  async getBaseProfile(_profile: Profile): Promise<BaseProfileResult> {
    throw new NotImplementedException();
  }
}
