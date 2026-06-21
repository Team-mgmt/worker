from fastapi import APIRouter, Depends, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from worker.core.database import get_db
from worker.schemas.catalog import SyncRequest
from worker.services.data4library_client import collect_item_srch
from worker.services.catalog_etl import process_and_load_items

router = APIRouter(prefix="/catalog", tags=["catalog"])

async def background_sync_task(request: SyncRequest, session: AsyncSession):
    try:
        items_iterator = collect_item_srch(
            lib_code=request.library_code,
            start_page=request.start_page,
            max_pages=request.max_pages,
            page_size=request.page_size
        )
        
        # Batch load items
        batch = []
        for item in items_iterator:
            batch.append(item)
            if len(batch) >= request.page_size:
                await process_and_load_items(session, request.library_code, batch)
                batch = []
                
        if batch:
            await process_and_load_items(session, request.library_code, batch)
            
        print(f"Sync completed for libCode: {request.library_code}")
    except Exception as e:
        print(f"Sync failed: {e}")

@router.post("/sync")
async def sync_catalog(request: SyncRequest, background_tasks: BackgroundTasks, db: AsyncSession = Depends(get_db)):
    background_tasks.add_task(background_sync_task, request, db)
    return {"message": f"Sync started for library {request.library_code} in background."}

@router.get("/search")
async def search_catalog(library_code: str, title: str = "", db: AsyncSession = Depends(get_db)):
    from worker.db_models.catalog import Book, Holding
    
    query = select(Holding).join(Book).where(Holding.library_code == library_code)
    if title:
        query = query.where(Book.bookname.ilike(f"%{title}%"))
        
    result = await db.execute(query.limit(100))
    holdings = result.scalars().all()
    
    return {"total": len(holdings), "items": [{"holding_id": h.holding_id, "call_number": h.call_number} for h in holdings]}
