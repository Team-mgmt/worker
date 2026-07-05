import {
  BadRequestException,
  Body,
  Controller,
  Delete,
  ForbiddenException,
  Get,
  Headers,
  Inject,
  Param,
  Patch,
  Post,
  Query,
  Res,
  UseGuards,
} from "@nestjs/common";

import { type Response } from "express";
import { RealIP } from "nestjs-real-ip";
import { ZodSerializerDto } from "nestjs-zod";

import { Cookies } from "@/common/decorators/cookies.decorator";
import { Organization } from "@/common/decorators/organization.decorator";
import { Session } from "@/common/decorators/session.decorator";
import { RedirectError } from "@/common/filters/redirect.filter";
import { AuthGuard } from "@/common/guards/auth.guard";
import { RateLimitGuard } from "@/common/guards/rate-limit.guard";
import { TurnstileGuard } from "@/common/guards/turnstile.guard";
import { EnvType, registerEnv } from "@/common/utils/env";
import { base64UrlToUuid } from "@/common/utils/string";
import { handleDateTime } from "@/common/utils/zod";

import {
  CheckNicknameQueryDto,
  CheckNicknameResponseDto,
  DeleteSessionResponseDto,
  ForgotPasswordRequestDto,
  ForgotPasswordResponseDto,
  GetSessionResponseDto,
  ListOrganizationsResponseDto,
  MeResponseDto,
  RefreshTokenResponseDto,
  ResetPasswordRequestDto,
  ResetPasswordResponseDto,
  SetNicknameRequestDto,
  SetNicknameResponseDto,
  SetPhoneRequestDto,
  SetPhoneResponseDto,
  SetPictureRequestDto,
  SetPictureResponseDto,
  SignInAdminRequestDto,
  SignInRequestDto,
  SignInResponseDto,
  SignUpRequestDto,
  SignUpResponseDto,
  VerifyEmailConfirmRequestDto,
  VerifyEmailConfirmResponseDto,
  VerifyEmailSendResponseDto,
} from "./auth.schema";
import { AuthService } from "./auth.service";

const turnstileNoTokenError = new BadRequestException({
  code: "TURNSTILE_TOKEN_MISSING",
  params: {},
});

const turnstileFailedError = new ForbiddenException({
  code: "TURNSTILE_VERIFICATION_FAILED",
  params: {},
});

@Controller("/auth")
export class AuthController {
  constructor(
    @Inject(registerEnv.KEY)
    private readonly env: EnvType,
    private readonly authService: AuthService,
  ) {}

  private setRefreshTokenCookie(res: Response, token: string) {
    res.cookie(this.env.AUTH_REFRESH_TOKEN_COOKIE_NAME, token, {
      httpOnly: true,
      secure: this.env.NODE_ENV !== "local",
      sameSite: "lax",
      path: "/",
      maxAge: 3 * 60 * 60 * 1000, // 3 hours
    });
  }

  @UseGuards(
    TurnstileGuard({
      customNoTokenError: turnstileNoTokenError,
      customFailedError: turnstileFailedError,
    }),
  )
  @ZodSerializerDto(SignInResponseDto)
  @Post("/signin")
  async signIn(
    @Body() body: SignInRequestDto,
    @Res({ passthrough: true }) res: Response,
  ): Promise<SignInResponseDto> {
    const data = await this.authService.signIn(body);

    this.setRefreshTokenCookie(res, data.refreshToken);

    return {
      result: true,
      data: handleDateTime({
        accessToken: data.accessToken,
        organizations: data.organizations,
      }),
    } satisfies SignInResponseDto;
  }

  @Post("/signin/:provider")
  async signInWithProvider(
    @RealIP() requestIp: string,
    @Headers("user-agent") userAgent: string,
    @Param("provider") provider: string,
    @Body() body: SignInAdminRequestDto,
    @Res({ passthrough: true }) res: Response,
  ) {
    const { url, session } = await this.authService.signInWithProvider(
      requestIp,
      userAgent,
      body.initiatedFrom,
      base64UrlToUuid(provider),
    );

    res.cookie(`__Host-Http-oauth-session-${provider}`, session, {
      httpOnly: true,
      secure: true,
      sameSite: "lax",
      path: "/",
      maxAge: 5 * 60 * 1000,
    });

    res.redirect(url.toString());
  }

  @Get("/signin/:provider/callback")
  async signInWithProviderCallback(
    @RealIP() requestIp: string,
    @Headers("user-agent") userAgent: string,
    @Param("provider") provider: string,
    @Query() query: Record<string, string | string[]>,
    @Cookies() cookies: Record<string, string>,
    @Res({ passthrough: true }) res: Response,
  ) {
    const sessionCookieName = `__Host-Http-oauth-session-${provider}`;

    if (!(sessionCookieName in cookies) || !cookies[sessionCookieName]) {
      throw new RedirectError("/auth/signin?error=SESSION_MISSING");
    }

    if (!query.code || !query.state) {
      throw new RedirectError("/auth/signin?error=BAD_REQUEST");
    }

    if (typeof query.code !== "string" || typeof query.state !== "string") {
      throw new RedirectError("/auth/signin?error=BAD_REQUEST");
    }

    const data = await this.authService.signInWithProviderCallback(
      requestIp,
      userAgent,
      cookies[sessionCookieName],
      query.code,
      query.state,
    );

    res.clearCookie(`__Host-Http-oauth-session-${provider}`);
    this.setRefreshTokenCookie(res, data.refreshToken);
    throw new RedirectError("/", data.initiatedFrom);
  }

  @UseGuards(TurnstileGuard())
  @ZodSerializerDto(SignUpResponseDto)
  @Post("/signup")
  async signUp(
    @Body() body: SignUpRequestDto,
    @Res({ passthrough: true }) res: Response,
  ): Promise<SignUpResponseDto> {
    const data = await this.authService.signUp(body);

    this.setRefreshTokenCookie(res, data.refreshToken);

    return {
      result: true,
      data: {
        accessToken: data.accessToken,
      },
    } satisfies SignUpResponseDto;
  }

  @Post("/refresh")
  @ZodSerializerDto(RefreshTokenResponseDto)
  async refreshToken(
    @Cookies() cookies: Record<string, string>,
    @Res({ passthrough: true }) res: Response,
  ): Promise<RefreshTokenResponseDto> {
    const refreshToken = cookies[this.env.AUTH_REFRESH_TOKEN_COOKIE_NAME];
    if (!refreshToken) {
      throw new BadRequestException({
        code: "REFRESH_TOKEN_MISSING",
        params: {},
      });
    }

    const data = await this.authService.refreshToken(refreshToken);

    if (data.refreshToken !== null) {
      this.setRefreshTokenCookie(res, data.refreshToken);
    }

    return {
      result: true,
      data: {
        accessToken: data.accessToken,
      },
    } satisfies RefreshTokenResponseDto;
  }

  @Get("/session")
  @UseGuards(AuthGuard({ organization: "skip" }))
  @ZodSerializerDto(GetSessionResponseDto)
  async checkAuth(
    @Session() sessionId: string,
    @Organization() organizationId?: string,
  ): Promise<GetSessionResponseDto> {
    const data = await this.authService.getSession(sessionId, organizationId);
    return {
      result: true,
      data: handleDateTime(data),
    } satisfies GetSessionResponseDto;
  }

  @Delete("/session")
  @UseGuards(AuthGuard({ organization: "skip" }))
  @ZodSerializerDto(DeleteSessionResponseDto)
  async deleteSession(
    @Session() sessionId: string,
    @Res({ passthrough: true }) res: Response,
  ): Promise<DeleteSessionResponseDto> {
    await this.authService.deleteSession(sessionId);

    // Clear the refresh token cookie
    res.clearCookie(this.env.AUTH_REFRESH_TOKEN_COOKIE_NAME, {
      httpOnly: true,
      secure: this.env.NODE_ENV !== "local",
      sameSite: "lax",
      path: "/",
    });

    return { result: true } satisfies DeleteSessionResponseDto;
  }

  @Get("/organizations")
  @UseGuards(AuthGuard({ organization: "skip" }))
  @ZodSerializerDto(ListOrganizationsResponseDto)
  async getOrganizations(
    @Session() sessionId: string,
  ): Promise<ListOrganizationsResponseDto> {
    const data = await this.authService.getOrganizationsBySessionId(sessionId);
    return {
      result: true,
      data: handleDateTime(data),
    } satisfies ListOrganizationsResponseDto;
  }

  @Get("/me")
  @UseGuards(AuthGuard({ organization: "skip" }))
  @ZodSerializerDto(MeResponseDto)
  async me(@Session() sessionId: string): Promise<MeResponseDto> {
    const data = await this.authService.getMe(sessionId);
    return { result: true, data } satisfies MeResponseDto;
  }

  @Patch("/me/nickname")
  @UseGuards(AuthGuard({ organization: "skip" }))
  @ZodSerializerDto(SetNicknameResponseDto)
  async setNickname(
    @Session() sessionId: string,
    @Body() body: SetNicknameRequestDto,
  ): Promise<SetNicknameResponseDto> {
    await this.authService.setNickname(sessionId, body.nickname);
    return { result: true } satisfies SetNicknameResponseDto;
  }

  @Patch("/me/phone")
  @UseGuards(AuthGuard({ organization: "skip" }))
  @ZodSerializerDto(SetPhoneResponseDto)
  async setPhone(
    @Session() sessionId: string,
    @Body() body: SetPhoneRequestDto,
  ): Promise<SetPhoneResponseDto> {
    await this.authService.setPhone(sessionId, body.phone);
    return { result: true } satisfies SetPhoneResponseDto;
  }

  @Patch("/me/picture")
  @UseGuards(AuthGuard({ organization: "skip" }))
  @ZodSerializerDto(SetPictureResponseDto)
  async setPicture(
    @Session() sessionId: string,
    @Body() body: SetPictureRequestDto,
  ): Promise<SetPictureResponseDto> {
    const data = await this.authService.setPicture(sessionId, body.picture);
    return { result: true, data } satisfies SetPictureResponseDto;
  }

  @Get("/nickname/check")
  @UseGuards(
    RateLimitGuard({
      name: "nickname-check",
      authenticated: { capacity: 120, windowSec: 60 },
      anonymous: { capacity: 120, windowSec: 60 },
    }),
  )
  @ZodSerializerDto(CheckNicknameResponseDto)
  async checkNickname(
    @Query() query: CheckNicknameQueryDto,
  ): Promise<CheckNicknameResponseDto> {
    const available = await this.authService.checkNicknameAvailable(
      query.nickname,
    );
    return {
      result: true,
      data: { available },
    } satisfies CheckNicknameResponseDto;
  }

  @Post("/verify-email/send")
  @UseGuards(AuthGuard({ organization: "skip" }))
  @ZodSerializerDto(VerifyEmailSendResponseDto)
  async verifyEmailSend(
    @Session() sessionId: string,
  ): Promise<VerifyEmailSendResponseDto> {
    await this.authService.sendVerificationEmail(sessionId);
    return { result: true } satisfies VerifyEmailSendResponseDto;
  }

  @Post("/verify-email/confirm")
  @ZodSerializerDto(VerifyEmailConfirmResponseDto)
  async verifyEmailConfirm(
    @Body() body: VerifyEmailConfirmRequestDto,
  ): Promise<VerifyEmailConfirmResponseDto> {
    await this.authService.confirmVerificationEmail(body.token);
    return { result: true } satisfies VerifyEmailConfirmResponseDto;
  }

  @Post("/password/forgot")
  @UseGuards(TurnstileGuard())
  @ZodSerializerDto(ForgotPasswordResponseDto)
  async passwordForgot(
    @Body() body: ForgotPasswordRequestDto,
  ): Promise<ForgotPasswordResponseDto> {
    await this.authService.sendPasswordReset(body.email);
    return { result: true } satisfies ForgotPasswordResponseDto;
  }

  @Post("/password/reset")
  @UseGuards(TurnstileGuard())
  @ZodSerializerDto(ResetPasswordResponseDto)
  async passwordReset(
    @Body() body: ResetPasswordRequestDto,
  ): Promise<ResetPasswordResponseDto> {
    await this.authService.resetPassword(body.token, body.password);
    return { result: true } satisfies ResetPasswordResponseDto;
  }
}
