import { createZodDto } from "nestjs-zod";
import z from "zod";

import {
  CheckNicknameQuerySchema,
  CheckNicknameResponseSchema,
  DeleteSessionResponseSchema,
  GetSessionResponseSchema,
  ListOrganizationsResponseSchema,
  RefreshTokenResponseSchema,
  SetNicknameRequestSchema,
  SetNicknameResponseSchema,
  SetPhoneRequestSchema,
  SetPhoneResponseSchema,
  SignInAdminRequestSchema,
  SignInRequestSchema,
  SignInResponseSchema,
  SignUpRequestSchema,
  SignUpResponseSchema,
} from "@shelfalign/schema/dtos/auth";
import {
  MeResponseSchema,
  SetPictureRequestSchema,
  SetPictureResponseSchema,
} from "@shelfalign/schema/dtos/auth/me";
import {
  ForgotPasswordRequestSchema,
  ForgotPasswordResponseSchema,
  ResetPasswordRequestSchema,
  ResetPasswordResponseSchema,
} from "@shelfalign/schema/dtos/auth/password-reset";
import {
  VerifyEmailConfirmRequestSchema,
  VerifyEmailConfirmResponseSchema,
  VerifyEmailSendResponseSchema,
} from "@shelfalign/schema/dtos/auth/verify-email";

export class SignInRequestDto extends createZodDto(SignInRequestSchema) {}
export class SignInResponseDto extends createZodDto(SignInResponseSchema) {}
export class SignInAdminRequestDto extends createZodDto(
  SignInAdminRequestSchema,
) {}
export class SignUpRequestDto extends createZodDto(SignUpRequestSchema) {}
export class SignUpResponseDto extends createZodDto(SignUpResponseSchema) {}
export class RefreshTokenResponseDto extends createZodDto(
  RefreshTokenResponseSchema,
) {}
export class GetSessionResponseDto extends createZodDto(
  GetSessionResponseSchema,
) {}
export class DeleteSessionResponseDto extends createZodDto(
  DeleteSessionResponseSchema,
) {}
export const BaseProfileSchema = z.object({
  id: z.string(),
  name: z.string().min(1, "이름을 입력해주세요"),
  email: z.email("유효한 이메일 주소를 입력해주세요"),
});
export type BaseProfile = z.infer<typeof BaseProfileSchema>;
export class ListOrganizationsResponseDto extends createZodDto(
  ListOrganizationsResponseSchema,
) {}

export class MeResponseDto extends createZodDto(MeResponseSchema) {}

export class VerifyEmailSendResponseDto extends createZodDto(
  VerifyEmailSendResponseSchema,
) {}
export class VerifyEmailConfirmRequestDto extends createZodDto(
  VerifyEmailConfirmRequestSchema,
) {}
export class VerifyEmailConfirmResponseDto extends createZodDto(
  VerifyEmailConfirmResponseSchema,
) {}

export class ForgotPasswordRequestDto extends createZodDto(
  ForgotPasswordRequestSchema,
) {}
export class ForgotPasswordResponseDto extends createZodDto(
  ForgotPasswordResponseSchema,
) {}
export class ResetPasswordRequestDto extends createZodDto(
  ResetPasswordRequestSchema,
) {}
export class ResetPasswordResponseDto extends createZodDto(
  ResetPasswordResponseSchema,
) {}

export class SetNicknameRequestDto extends createZodDto(
  SetNicknameRequestSchema,
) {}
export class SetNicknameResponseDto extends createZodDto(
  SetNicknameResponseSchema,
) {}
export class SetPhoneRequestDto extends createZodDto(SetPhoneRequestSchema) {}
export class SetPhoneResponseDto extends createZodDto(SetPhoneResponseSchema) {}
export class SetPictureRequestDto extends createZodDto(
  SetPictureRequestSchema,
) {}
export class SetPictureResponseDto extends createZodDto(
  SetPictureResponseSchema,
) {}
export class CheckNicknameQueryDto extends createZodDto(
  CheckNicknameQuerySchema,
) {}
export class CheckNicknameResponseDto extends createZodDto(
  CheckNicknameResponseSchema,
) {}
