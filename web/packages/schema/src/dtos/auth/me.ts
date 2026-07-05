import z from "zod";

export const MeOrganizationSchema = z.object({
  id: z.uuid(),
  name: z.string(),
  type: z.enum(["ADMIN", "LIBRARIAN"]),
  membershipId: z.uuid(),
  verificationStatus: z.enum(["VERIFIED", "UNVERIFIED"]),
  isOwner: z.boolean(),
});
export type MeOrganization = z.infer<typeof MeOrganizationSchema>;

export const MeResponseSchema = z.object({
  result: z.literal(true),
  data: z.object({
    user: z.object({
      id: z.uuid(),
      name: z.string(),
      nickname: z.string().nullable(),
      email: z.string(),
      phone: z.string().nullable(),
      // Presigned download URL for the user's profile picture; null when no
      // picture is set. Computed server-side from User.picture (S3 key);
      // clients never see the raw key.
      pictureUrl: z.url().nullable(),
      emailVerifiedAt: z.iso.datetime().nullable(),
    }),
    organizations: z.array(MeOrganizationSchema),
  }),
});
export type MeResponse = z.infer<typeof MeResponseSchema>;

export const SetPictureRequestSchema = z.object({
  // S3 key returned by POST /service/upload. Pass `null` to clear an
  // existing picture.
  picture: z.string().min(1).nullable(),
});
export type SetPictureRequest = z.infer<typeof SetPictureRequestSchema>;

export const SetPictureResponseSchema = z.object({
  result: z.literal(true),
  data: z.object({
    pictureUrl: z.url().nullable(),
  }),
});
export type SetPictureResponse = z.infer<typeof SetPictureResponseSchema>;
