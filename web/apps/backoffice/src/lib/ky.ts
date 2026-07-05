import { createKyClient } from "@shelfalign/client-common/request";

import { ADMIN_ORGANIZATION_ID } from "./constants";

export const ky = createKyClient({
  baseUrl: import.meta.env.VITE_BASE_URL,
  tokenRefresh: true,
  organization: { type: "static", organizationId: ADMIN_ORGANIZATION_ID },
});
