import { createQueryKeys } from "@lukemorales/query-key-factory";

import { UnauthorizedError } from "@shelfalign/client-common/error";

import { ky } from "@/lib/ky";

export const authQueries = createQueryKeys("auth", {
  session: {
    queryKey: null,
    queryFn: async () => {
      const token = localStorage.getItem("accessToken");
      if (!token) {
        throw new UnauthorizedError();
      }

      try {
        const result = await ky
          .get("auth/session")
          .json<{ result: true; data: unknown }>();

        return result.data;
      } catch {
        localStorage.removeItem("accessToken");
        throw new UnauthorizedError();
      }
    },
  },
});
