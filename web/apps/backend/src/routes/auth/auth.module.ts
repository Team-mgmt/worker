import { Module } from "@nestjs/common";

import { CoreAuthModule } from "@/core/auth/auth.module";
import { MailModule } from "@/core/mail/mail.module";
import { OrganizationModule } from "@/core/organization/organization.module";

import { AuthController } from "./auth.controller";
import { AuthService } from "./auth.service";

@Module({
  imports: [CoreAuthModule, MailModule, OrganizationModule],
  controllers: [AuthController],
  providers: [AuthService],
})
export class AuthModule {}
