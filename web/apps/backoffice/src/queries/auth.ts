import { createQueryKeys } from "@lukemorales/query-key-factory";

import { UnauthorizedError } from "@shelfalign/client-common/error";

import { ADMIN_ORGANIZATION_ID } from "@/lib/constants";

export const authQueries = createQueryKeys("auth", {
  session: {
    queryKey: null,
    queryFn: async () => {
      const token = localStorage.getItem("accessToken");
      if (token === "test-token") {
        return {
          id: "123e4567-e89b-12d3-a456-426614174000",
          createdAt: new Date().toISOString(),
          expiresAt: new Date(Date.now() + 86_400_000).toISOString(),
          user: {
            id: "123e4567-e89b-12d3-a456-426614174000",
            name: "관리자",
            nickname: "Admin",
            primaryEmail: "admin@shelfalign.kr",
          },
          membership: [
            {
              id: "123e4567-e89b-12d3-a456-426614174001",
              name: "관리자",
              type: "ADMIN" as const,
              organizationId: ADMIN_ORGANIZATION_ID,
            },
          ],
        };
      }
      throw new UnauthorizedError();
    },
  },
});
