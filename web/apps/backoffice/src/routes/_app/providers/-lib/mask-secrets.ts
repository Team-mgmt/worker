const SECRET_KEYS = ["clientSecret", "secret", "privateKey"];

export function maskSecrets(
  obj: Record<string, unknown>,
): Record<string, unknown> {
  return Object.fromEntries(
    Object.entries(obj).map(([key, value]) => {
      if (SECRET_KEYS.includes(key)) return [key, "[HIDDEN]"];
      if (
        typeof value === "object" &&
        value !== null &&
        !Array.isArray(value)
      ) {
        return [key, maskSecrets(value as Record<string, unknown>)];
      }
      return [key, value];
    }),
  );
}
