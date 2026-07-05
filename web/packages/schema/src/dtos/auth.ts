import z from "zod";

import { OrganizationMemberSchema } from "@/models/organization-member.js";
import { OrganizationSchema } from "@/models/organization.js";

import { ServicesSchema } from "./base.js";

export const AccessTokenPayloadSchema = z.object({
  sessionId: z.uuid(),
  permissions: z.record(z.uuid(), z.enum(["ADMIN", "LIBRARIAN"])),
});

export type AccessTokenPayload = z.infer<typeof AccessTokenPayloadSchema>;

export const RefreshTokenPayloadSchema = z.object({});

export type RefreshTokenPayload = z.infer<typeof RefreshTokenPayloadSchema>;

export const SignUpRequestSchema = z
  .object({
    name: z.string().trim().min(1, "이름을 입력해주세요"),
    nickname: z
      .string()
      .trim()
      .min(2, "닉네임은 최소 2자 이상이어야 합니다")
      .max(20, "닉네임은 최대 20자까지 입력할 수 있습니다"),
    email: z.email("유효한 이메일 주소를 입력해주세요"),
    phone: z
      .string()
      .trim()
      .min(1, "전화번호를 입력해주세요")
      .regex(/^[0-9+\-\s()]+$/, "유효한 전화번호를 입력해주세요"),
    password: z.string().min(8, "비밀번호는 최소 8자 이상이어야 합니다"),
    passwordRepeat: z.string().min(1, "비밀번호를 다시 입력해주세요"),
    type: z.enum(["ADMIN", "LIBRARIAN"]),
  })
  .refine((data) => data.password === data.passwordRepeat, {
    message: "비밀번호가 일치하지 않습니다",
    path: ["passwordRepeat"],
  });
export type SignUpRequest = z.infer<typeof SignUpRequestSchema>;

export const SignUpResponseSchema = z.object({
  result: z.literal(true),
  data: z.object({
    accessToken: z.string(),
  }),
});

export const SignInRequestSchema = z.object({
  email: z.email("유효한 이메일 주소를 입력해주세요"),
  password: z.string().min(1, "비밀번호를 입력해주세요"),
});

export const SignInResponseSchema = z.object({
  result: z.literal(true),
  data: z.object({
    accessToken: z.string(),
    organizations: OrganizationMemberSchema.array(),
  }),
});
export type SignInResponse = z.infer<typeof SignInResponseSchema>;

export const SignInAdminRequestSchema = z.object({
  initiatedFrom: ServicesSchema,
});

export const SelectOrganizationRequestSchema = z.object({
  sessionToken: z.string(),
  organizationMemberId: z.uuid(),
});

export const SelectOrganizationResponseSchema = z.object({
  result: z.literal(true),
  data: z.object({
    accessToken: z.string(),
  }),
});

export const RefreshTokenResponseSchema = z.object({
  result: z.literal(true),
  data: z.object({
    accessToken: z.string(),
  }),
});

export const MembershipSchema = z.object({
  id: z.uuid(),
  name: z.string(),
  type: z.enum(["ADMIN", "LIBRARIAN"]),
  organizationId: z.uuid(),
});

export const GetSessionDataSchema = z.object({
  id: z.uuid(),
  createdAt: z.iso.datetime(),
  expiresAt: z.iso.datetime(),
  user: z.object({
    id: z.uuid(),
    name: z.string(),
    nickname: z.string().nullable(),
    primaryEmail: z.email(),
  }),
  membership: z.array(MembershipSchema),
});

export const GetSessionResponseSchema = z.object({
  result: z.literal(true),
  data: GetSessionDataSchema,
});

export const DeleteSessionResponseSchema = z.object({
  result: z.literal(true),
});

export const SetNicknameRequestSchema = z.object({
  nickname: z
    .string()
    .trim()
    .min(2, "닉네임은 최소 2자 이상이어야 합니다")
    .max(20, "닉네임은 최대 20자까지 입력할 수 있습니다"),
});
export type SetNicknameRequest = z.infer<typeof SetNicknameRequestSchema>;

export const SetNicknameResponseSchema = z.object({
  result: z.literal(true),
});
export type SetNicknameResponse = z.infer<typeof SetNicknameResponseSchema>;

export const SetPhoneRequestSchema = z.object({
  phone: z
    .string()
    .trim()
    .min(1, "전화번호를 입력해주세요")
    .max(20, "전화번호는 20자 이하로 입력해주세요")
    .regex(/^[0-9+\-\s()]+$/, "유효한 전화번호를 입력해주세요")
    .nullable(),
});
export type SetPhoneRequest = z.infer<typeof SetPhoneRequestSchema>;

export const SetPhoneResponseSchema = z.object({
  result: z.literal(true),
});
export type SetPhoneResponse = z.infer<typeof SetPhoneResponseSchema>;

export const CheckNicknameQuerySchema = z.object({
  nickname: z.string().trim().min(1),
});
export type CheckNicknameQuery = z.infer<typeof CheckNicknameQuerySchema>;

export const CheckNicknameResponseSchema = z.object({
  result: z.literal(true),
  data: z.object({
    available: z.boolean(),
  }),
});
export type CheckNicknameResponse = z.infer<typeof CheckNicknameResponseSchema>;

export const ListOrganizationsResponseSchema = z.object({
  result: z.literal(true),
  data: z.array(
    OrganizationSchema.extend({
      members: OrganizationMemberSchema.array(),
    }),
  ),
});
export type ListOrganizationsResponse = z.infer<
  typeof ListOrganizationsResponseSchema
>;
