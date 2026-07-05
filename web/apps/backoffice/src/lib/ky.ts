import { createKyClient } from "@shelfalign/client-common/request";

export const ky = createKyClient({
  baseUrl: import.meta.env.VITE_BASE_URL,
  tokenRefresh: true,
  organization: { type: "dynamic", userType: "ADMIN" },
});
