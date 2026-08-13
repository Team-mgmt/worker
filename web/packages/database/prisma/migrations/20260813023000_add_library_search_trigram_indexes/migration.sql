CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE INDEX "LibraryBook_normalizedBookname_trgm_idx"
ON "LibraryBook" USING GIN ("normalizedBookname" gin_trgm_ops);

CREATE INDEX "LibraryBook_normalizedAuthors_trgm_idx"
ON "LibraryBook" USING GIN ("normalizedAuthors" gin_trgm_ops);

CREATE INDEX "LibraryHolding_normalizedCallNumber_trgm_idx"
ON "LibraryHolding" USING GIN ("normalizedCallNumber" gin_trgm_ops);

CREATE INDEX "LibraryHolding_bookCode_trgm_idx"
ON "LibraryHolding" USING GIN ("bookCode" gin_trgm_ops);
