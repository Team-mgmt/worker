from pydantic import BaseModel
from typing import Optional, List
from datetime import date

class SyncRequest(BaseModel):
    library_code: str
    start_page: int = 1
    max_pages: Optional[int] = None
    page_size: int = 100

class BookResponse(BaseModel):
    book_id: int
    isbn13: Optional[str]
    bookname: str
    authors: Optional[str]
    publisher: Optional[str]
    publication_year: Optional[str]

class HoldingResponse(BaseModel):
    library_code: str
    call_number: Optional[str]
    book: BookResponse

class SearchResponse(BaseModel):
    items: List[HoldingResponse]
    total: int
