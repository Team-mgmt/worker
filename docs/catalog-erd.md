# Catalog ERD

Entity-relationship diagram for `books` / `holdings` / `scan_sessions` / `detections`
(source: `worker/db_models/catalog.py`, `worker/db_models/inference.py`,
current schema as of `alembic/versions/2b9f0f3e7a12_preserve_detection_review_metadata.py`).

`holdings.library_code` is what distinguishes libraries — adding a new library
(e.g. Dobong-Ainara, `libCode=111189`) requires no schema change, only new rows.

```mermaid
erDiagram
    BOOKS ||--o{ HOLDINGS : "book_id (nullable)"
    SCAN_SESSIONS ||--o{ DETECTIONS : "scan_session_id"
    BOOKS ||--o{ DETECTIONS : "matched_book_id (nullable)"
    HOLDINGS ||--o{ DETECTIONS : "matched_holding_id (nullable)"

    BOOKS {
        int book_id PK
        string isbn13 UK "nullable, unique index"
        text bookname
        text normalized_bookname
        text authors
        text normalized_authors
        text publisher
        string publication_year
        text book_image_url
        datetime created_at
    }

    HOLDINGS {
        int holding_id PK
        int book_id FK "nullable"
        string library_code "distinguishes library"
        string class_no
        string class_no_clean
        numeric class_no_num
        string book_code
        string call_number
        string normalized_call_number
        string shelf_loc_code
        string shelf_loc_name
        string separate_shelf_code
        string separate_shelf_name
        string copy_code
        date reg_date
        datetime created_at
    }

    SCAN_SESSIONS {
        int scan_session_id PK
        string library_code
        string room_name
        numeric expected_shelf_start
        numeric expected_shelf_end
        numeric estimated_shelf_start
        numeric estimated_shelf_end
        numeric shelf_confidence
        string source_type
        text source_path
        datetime created_at
    }

    DETECTIONS {
        int detection_id PK
        int scan_session_id FK
        int frame_no
        int detected_order
        jsonb bbox
        text crop_image_path
        text ocr_raw_text
        text ocr_title
        text ocr_author
        text ocr_call_number
        numeric ocr_confidence
        int matched_book_id FK "nullable"
        int matched_holding_id FK "nullable"
        string match_method
        numeric match_score
        numeric score_margin
        jsonb top_candidates
        string status
        text reason
        datetime created_at
    }
```

## Notes

- `books.isbn13` is unique but nullable — multiple books with no ISBN are
  allowed (Postgres treats each `NULL` as distinct under a unique index).
  See `worker/services/catalog_etl.py` (`process_and_load_items`) and
  `scripts/load_library_excel.py`, both of which normalize a missing ISBN to
  `None` rather than `""` for this reason.
- `holdings.book_id` is nullable: a holding row is created even when no
  matching `books` row was found (e.g. ISBN-less items matched by
  bookname/authors/publisher instead — see `load_library_excel.py`).
- `detections.matched_book_id` / `matched_holding_id` are both nullable
  because a detection may end up `unmatched` (see `detections.status`).
