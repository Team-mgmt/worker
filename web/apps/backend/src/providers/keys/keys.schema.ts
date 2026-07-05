import z from "zod";

export const KeyChainSchema = z
  .object({
    LATEST_KEY_ID: z.uuid(),
  })
  .catchall(z.string())
  .superRefine((obj, ctx) => {
    for (const key of Object.keys(obj)) {
      if (key === "LATEST_KEY_ID") continue;
      if (!z.uuid().safeParse(key).success) {
        ctx.addIssue({
          code: "unrecognized_keys",
          keys: [key],
          message: `Key ID ${key} is not a valid UUID`,
        });
      }
    }

    if (!Object.prototype.hasOwnProperty.call(obj, obj.LATEST_KEY_ID)) {
      ctx.addIssue({
        code: "invalid_value",
        values: [obj.LATEST_KEY_ID],
        message: `LATEST_KEY_ID must match one of the key IDs`,
      });
    }
  });

export type KeyChainType = z.infer<typeof KeyChainSchema>;

export const LocalKeyFileSchema = z.object({
  privateKey: z
    .object({
      kty: z.literal("EC"),
      crv: z.literal("P-521"),
      x: z.string(),
      y: z.string(),
      d: z.string(),
    })
    .passthrough(),
  publicKey: z
    .object({
      kty: z.literal("EC"),
      crv: z.literal("P-521"),
      x: z.string(),
      y: z.string(),
    })
    .passthrough(),
});

export type ParsedKeyChain = {
  latestKeyId: string;
  keys: {
    [kid: string]: { public: CryptoKey; private: CryptoKey }; // [privateKey, publicKey]
  };
};
