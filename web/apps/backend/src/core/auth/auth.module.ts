import { Global, Module } from "@nestjs/common";

import { CognitoModule } from "@/providers/cognito/cognito.module";
import { KeyModule } from "@/providers/keys/keys.module";

import { CoreAuthService } from "./auth.service";
import { GoogleProvider } from "./providers/google.provider";
import { MicrosoftProvider } from "./providers/microsoft.provider";
import { EmailTokenService } from "./tokens/email-token.service";

@Global()
@Module({
  imports: [KeyModule, CognitoModule],
  providers: [
    CoreAuthService,
    MicrosoftProvider,
    GoogleProvider,
    EmailTokenService,
  ],
  exports: [
    KeyModule,
    CoreAuthService,
    MicrosoftProvider,
    GoogleProvider,
    EmailTokenService,
  ],
})
export class CoreAuthModule {}
