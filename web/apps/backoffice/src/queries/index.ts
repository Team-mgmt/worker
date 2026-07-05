import { mergeQueryKeys } from "@lukemorales/query-key-factory";

import { authQueries } from "./auth";
import { documentQueries } from "./document";
import { organizationQueries } from "./organization";
import { providerQueries } from "./provider";

export const queries = mergeQueryKeys(
  authQueries,
  documentQueries,
  organizationQueries,
  providerQueries,
);
