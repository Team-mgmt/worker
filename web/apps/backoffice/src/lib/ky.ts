import { createKyClient } from "@shelfalign/client-common/request";

const configuredBaseUrl = import.meta.env.VITE_BASE_URL || "/api";
const baseUrl = new URL(
  configuredBaseUrl.endsWith("/")
    ? configuredBaseUrl
    : `${configuredBaseUrl}/`,
  window.location.origin,
).toString().replace(/\/$/, "");

export const ky = createKyClient({
  baseUrl,
  tokenRefresh: true,
  organization: { type: "dynamic", userType: "ADMIN" },
});
