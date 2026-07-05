import { createQueryKeys } from "@lukemorales/query-key-factory";

import { toastParseError, tryJson } from "@shelfalign/client-common/parsing";
import {
  AdminListOrganizationsResponseSchema,
  AdminOrganizationResponseSchema,
} from "@shelfalign/schema/dtos/admin/organization";

import { ky } from "@/lib/ky";

export const organizationQueries = createQueryKeys("organization", {
  list: (page: number, pageSize: number = 10) => ({
    queryKey: [page, pageSize],
    queryFn: async () => {
      const res = await ky.get(
        `${import.meta.env.VITE_BASE_URL}/admin/organizations`,
        {
          searchParams: {
            page: page.toString(),
            pageSize: pageSize.toString(),
          },
        },
      );
      const response = await tryJson(
        await res.text(),
        AdminListOrganizationsResponseSchema,
      );
      return toastParseError(res, response);
    },
  }),
  get: (id: string) => ({
    queryKey: [id],
    queryFn: async () => {
      const res = await ky.get(
        `${import.meta.env.VITE_BASE_URL}/admin/organizations/${id}`,
      );
      const response = await tryJson(
        await res.text(),
        AdminOrganizationResponseSchema,
      );
      return toastParseError(res, response).data;
    },
  }),
});
