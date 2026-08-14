# Catalog matching

The worker matches each OCR result against `LibraryHolding` and `LibraryBook`
for the selected `libraryCode`. The API response and S3 `result.json` continue
to expose the existing aggregate score and top candidates.

## Candidate generation

1. When OCR produced a call number, query the indexed
   `LibraryHolding.normalizedCallNumber` value first.
2. If there is no exact holding, fall back to the KDC and book-code prefix
   candidate query.
3. When OCR did not produce a call number, require a normalized core-title
   match instead of comparing an arbitrary first 1,500 catalog rows.

This makes exact holdings both faster and deterministic. A title-only OCR
result that is absent from the selected library returns no candidate rather
than an unrelated low-score candidate.

## Title reranking

Titles are normalized with NFKC and reduced to their identifying core. Common
bibliographic responsibility and form expressions such as `장편소설`,
`소설집`, `시집`, `지음`, `옮김`, and `대활자본` do not contribute to title
identity. Text after a catalog subtitle separator (`:`) is also excluded from
the primary-title comparison. A parallel title after `=` is treated as an
alias, so `코케인 = Cocaine : 진연주 장편소설` has the core title `코케인`.

Candidate titles are reranked with a corpus-local character 2/3-gram TF-IDF
cosine score combined with a compact-title RapidFuzz score. Character n-grams
retain tolerance to OCR spacing and single-character errors, while preventing
the same author or the generic phrase `장편소설` from making different works
look like the same title.

Call-number and author evidence remain part of the aggregate score. Do not
lower the confirmation threshold merely to increase the number of automatic
matches; evaluate Top-1 accuracy, false confirmation rate, and score margin on
ground truth first.
