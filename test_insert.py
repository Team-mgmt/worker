import asyncio
from worker.core.database import AsyncSessionLocal
from worker.services.catalog_etl import process_and_load_items
from worker.services.data4library_client import collect_item_srch

async def run():
    session = AsyncSessionLocal()
    print("Fetching items...")
    items = list(collect_item_srch('111058', max_pages=1, page_size=2))
    print(f"Fetched {len(items)} items.")
    print("Loading into DB...")
    await process_and_load_items(session, '111058', items)
    await session.close()
    print('Done!')

if __name__ == "__main__":
    import sys
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(run())
