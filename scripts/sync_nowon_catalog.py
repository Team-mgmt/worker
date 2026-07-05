from __future__ import annotations

import argparse
import asyncio
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from worker.core.database import AsyncSessionLocal
from worker.services.catalog_etl import process_and_load_items
from worker.services.data4library_client import collect_item_srch


NOWON_JUNGANG_LIBRARY_CODE = "111058"
DEFAULT_SHELF_LOC_CONTAINS = "종합자료실"


def filter_item_call_numbers_by_shelf(item: dict, shelf_loc_contains: str | None) -> dict | None:
    if not shelf_loc_contains:
        return item

    call_numbers = item.get("callNumbers", [])
    if not call_numbers:
        shelf_loc_name = item.get("shelf_loc_name", "")
        return item if shelf_loc_contains in shelf_loc_name else None

    filtered_call_numbers = []
    for wrapper in call_numbers:
        call_number = wrapper.get("callNumber", {})
        if shelf_loc_contains in call_number.get("shelf_loc_name", ""):
            filtered_call_numbers.append(wrapper)

    if not filtered_call_numbers:
        return None

    filtered_item = dict(item)
    filtered_item["callNumbers"] = filtered_call_numbers
    return filtered_item


async def sync_catalog(lib_code: str, start_page: int, max_pages: int | None, page_size: int, shelf_loc_contains: str | None, kdc: str | None, start_year: int = 2026, end_year: int = 2016) -> None:
    total = 0
    seen = 0
    batch = []
    skipped = 0

    async with AsyncSessionLocal() as session:
        from sqlalchemy import select
        from worker.db_models.catalog import Book
        
        result = await session.execute(select(Book.isbn13).where(Book.isbn13.isnot(None)))
        existing_isbns = set(row[0] for row in result.all())
        print(f"Loaded {len(existing_isbns)} existing ISBNs from DB to skip.")

        for item in collect_item_srch(
            lib_code=lib_code,
            start_page=start_page,
            max_pages=max_pages,
            page_size=page_size,
            kdc=kdc,
            start_year=start_year,
            end_year=end_year,
        ):
            seen += 1
            
            # KDC filter in python (use exact prefix: e.g. '81' -> saves only 81X)
            class_no = item.get("class_no", "")
            if kdc and not class_no.startswith(kdc):
                continue
            
            isbn13 = item.get("isbn13")
            if isbn13 and isbn13 in existing_isbns:
                skipped += 1
                continue

            filtered_item = filter_item_call_numbers_by_shelf(item, shelf_loc_contains)
            if filtered_item is None:
                continue

            batch.append(filtered_item)
            if len(batch) >= page_size:
                await process_and_load_items(session, lib_code, batch)
                total += len(batch)
                print(f"Loaded {total} catalog rows for library {lib_code} after scanning {seen} API rows")
                batch = []

        if batch:
            await process_and_load_items(session, lib_code, batch)
            total += len(batch)

    shelf_msg = f" filtered by shelf containing '{shelf_loc_contains}'" if shelf_loc_contains else ""
    kdc_msg = f" with kdc '{kdc}'" if kdc else ""
    print(f"Done. Loaded {total} catalog rows for library {lib_code}{shelf_msg}{kdc_msg}. Scanned {seen} API rows, skipped {skipped} existing rows.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sync Data4Library itemSrch rows into the local ShelfAlign catalog.")
    parser.add_argument("--lib-code", default=NOWON_JUNGANG_LIBRARY_CODE, help="Data4Library libCode. Default: Nowon Jungang Library.")
    parser.add_argument("--start-page", type=int, default=1)
    parser.add_argument("--max-pages", type=int, default=None, help="Limit pages for MVP/dev runs. Omit to sync until the API is exhausted.")
    parser.add_argument("--page-size", type=int, default=100)
    parser.add_argument(
        "--shelf-loc-contains",
        default=DEFAULT_SHELF_LOC_CONTAINS,
        help="Only load holdings whose shelf_loc_name contains this text. Use an empty value to load all shelves.",
    )
    parser.add_argument("--kdc", default=None, help="Filter by KDC code. Example: '81' for Korean Literature.")
    parser.add_argument("--start-year", type=int, default=2026, help="Start year for sync (inclusive). Default: 2026")
    parser.add_argument("--end-year", type=int, default=2016, help="End year for sync (inclusive). Default: 2016")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    shelf_loc_contains = args.shelf_loc_contains or None
    asyncio.run(sync_catalog(args.lib_code, args.start_page, args.max_pages, args.page_size, shelf_loc_contains, args.kdc, args.start_year, args.end_year))


if __name__ == "__main__":
    main()
