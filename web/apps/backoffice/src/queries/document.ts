import { createQueryKeys } from "@lukemorales/query-key-factory";

import { toastParseError, tryJson } from "@shelfalign/client-common/parsing";
import {
  AdminGetDocumentResponseSchema,
  AdminListDocumentsResponseSchema,
  AdminListDocumentVersionsResponseSchema,
} from "@shelfalign/schema/dtos/admin/document";

import { ky } from "@/lib/ky";

export const documentQueries = createQueryKeys("document", {
  list: (includeDeleted: boolean = false) => ({
    queryKey: [includeDeleted],
    queryFn: async () => {
      const res = await ky.get(
        `${import.meta.env.VITE_BASE_URL}/admin/documents`,
        {
          searchParams: includeDeleted ? { includeDeleted: "true" } : undefined,
        },
      );
      const response = await tryJson(
        await res.text(),
        AdminListDocumentsResponseSchema,
      );
      return toastParseError(res, response).data;
    },
  }),
  get: (slug: string, versionId?: string) => ({
    queryKey: [slug, versionId ?? "latest"],
    queryFn: async () => {
      const res = await ky.get(
        `${import.meta.env.VITE_BASE_URL}/admin/documents/${slug}`,
        {
          searchParams: versionId ? { versionId } : undefined,
        },
      );
      const response = await tryJson(
        await res.text(),
        AdminGetDocumentResponseSchema,
      );
      return toastParseError(res, response).data;
    },
  }),
  versions: (slug: string) => ({
    queryKey: [slug],
    queryFn: async () => {
      const res = await ky.get(
        `${import.meta.env.VITE_BASE_URL}/admin/documents/${slug}/versions`,
      );
      const response = await tryJson(
        await res.text(),
        AdminListDocumentVersionsResponseSchema,
      );
      return toastParseError(res, response).data;
    },
  }),
});
