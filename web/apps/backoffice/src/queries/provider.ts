import { createQueryKeys } from "@lukemorales/query-key-factory";

import { toastParseError, tryJson } from "@shelfalign/client-common/parsing";
import {
  AdminListProvidersResponseSchema,
  AdminProviderResponseSchema,
} from "@shelfalign/schema/dtos/admin/provider";

import { ky } from "@/lib/ky";

export const providerQueries = createQueryKeys("provider", {
  list: (page: number, pageSize: number = 10) => ({
    queryKey: [page, pageSize],
    queryFn: async () => {
      const res = await ky.get(
        `${import.meta.env.VITE_BASE_URL}/admin/providers`,
        {
          searchParams: {
            page: page.toString(),
            pageSize: pageSize.toString(),
          },
        },
      );
      const response = await tryJson(
        await res.text(),
        AdminListProvidersResponseSchema,
      );
      return toastParseError(res, response);
    },
  }),
  get: (id: string) => ({
    queryKey: [id],
    queryFn: async () => {
      const res = await ky.get(
        `${import.meta.env.VITE_BASE_URL}/admin/providers/${id}`,
      );
      const response = await tryJson(
        await res.text(),
        AdminProviderResponseSchema,
      );
      return toastParseError(res, response).data;
    },
  }),
});
