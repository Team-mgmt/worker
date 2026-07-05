import { createQueryKeys } from "@lukemorales/query-key-factory";

import { UnauthorizedError } from "@shelfalign/client-common/error";

export const authQueries = createQueryKeys("auth", {
  session: {
    queryKey: null,
    queryFn: async () => {
      const token = localStorage.getItem("accessToken");
      if (!token) {
        throw new UnauthorizedError();
      }

      try {
        const organizationId = localStorage.getItem("organization");
        const response = await fetch(
          `${import.meta.env.VITE_BASE_URL}/auth/session`,
          {
            headers: {
              Authorization: `Bearer ${token}`,
              ...(organizationId
                ? { "x-organization-id": organizationId }
                : {}),
            },
            credentials: "include",
          },
        );

        if (!response.ok) {
          throw new Error("Session request failed");
        }

        const result = (await response.json()) as {
          result: true;
          data: unknown;
        };

        return result.data;
      } catch {
        localStorage.removeItem("accessToken");
        throw new UnauthorizedError();
      }
    },
  },
});
