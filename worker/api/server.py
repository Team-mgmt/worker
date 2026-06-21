import sys
import asyncio

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from worker.api import catalog, inference

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

@app.get("/health")
def health_check():
    return {"status": "ok"}
