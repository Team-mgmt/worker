import { ProviderConfigSchema } from "@shelfalign/schema/auth/providers/base";

export function getProviderType(config: unknown): string {
  const parsed = ProviderConfigSchema.safeParse(config);
  if (!parsed.success) return "알 수 없음";
  return parsed.data.type;
}
