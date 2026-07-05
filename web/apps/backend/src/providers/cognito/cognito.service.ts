import { Inject, Injectable } from "@nestjs/common";

import { CognitoIdentityClient } from "@aws-sdk/client-cognito-identity";

import { EnvType, registerEnv } from "@/common/utils/env";

@Injectable()
export class CognitoService {
  client: CognitoIdentityClient;

  constructor(@Inject(registerEnv.KEY) private readonly env: EnvType) {
    const accessKey = this.env.AWS_ACCESS_KEY_ID;
    const secretKey = this.env.AWS_SECRET_ACCESS_KEY;
    const sessionToken = this.env.AWS_SESSION_TOKEN;
    const region = this.env.AWS_REGION;
    const credentials =
      accessKey && secretKey
        ? { accessKeyId: accessKey, secretAccessKey: secretKey, sessionToken }
        : undefined;

    this.client = new CognitoIdentityClient({ region, credentials });
  }
}
