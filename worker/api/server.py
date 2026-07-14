import sys
import asyncio

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from worker.api import artifact_evaluation, catalog, inference

app = FastAPI(
    title="ShelfAlign Worker API",
    description="Worker backend for collecting catalog and performing OCR inferences.",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount Routers
app.include_router(catalog.router)
app.include_router(inference.router)
app.include_router(artifact_evaluation.router)

@app.exception_handler(Exception)
async def unhandled_exception_handler(request, exc):
    return JSONResponse(
        status_code=500,
        content={"detail": f"Unhandled worker error: {exc}"},
    )

@app.get("/health")
def health_check():
    return {"status": "ok"}
