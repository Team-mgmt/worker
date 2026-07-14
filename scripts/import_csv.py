import asyncio
import sys
import csv

if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from pathlib import Path
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from worker.core.database import AsyncSessionLocal
from worker.db_models.catalog import Book, Holding
from worker.services.catalog_etl import normalize_text, normalize_kdc, generate_call_number

def extract_class_no_num(class_no: str):
    try:
        return float(''.join(c for c in class_no if c.isdigit() or c == '.'))
    except ValueError:
        return None

async def import_csv_to_db(csv_path: str, lib_code: str = "111058"):
    print(f"Reading CSV from {csv_path}...")
    
    async with AsyncSessionLocal() as session:
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            
            books_to_add = []
            holdings_to_add = []
            
            count = 0
            for row in reader:
                isbn13 = row.get('isbn13') or None
                book_code = row.get('bookCode', '')
                class_no = row.get('classNo', '')

                existing_book_id = None
                if isbn13:
                    # Check if book already exists to avoid duplicates
                    result = await session.execute(select(Book.book_id).where(Book.isbn13 == isbn13))
                    existing_book_id = result.scalar_one_or_none()

                if not existing_book_id:
                    # Create Book. Without an isbn13 there is nothing to dedupe
                    # on, so every ISBN-less row gets its own Book row (isbn13
                    # stays NULL, which the unique index allows multiple of).
                    bookname = row.get('bookname', '')
                    authors = row.get('authors', '')

                    book = Book(
                        isbn13=isbn13,
                        bookname=bookname,
                        normalized_bookname=normalize_text(bookname),
                        authors=authors,
                        normalized_authors=normalize_text(authors),
                        publisher=row.get('publisher', ''),
                        publication_year=row.get('publicationYear', ''),
                        book_image_url=""
                    )
                    session.add(book)
                    await session.flush() # Flush to get book_id
                    existing_book_id = book.book_id

                # Create Holding. call_number is regenerated from class_no +
                # book_code (not taken from the CSV's callNumber column,
                # which may be missing/stale) to match catalog_etl.py.
                call_number = generate_call_number(normalize_kdc(class_no), book_code)

                holding = Holding(
                    book_id=existing_book_id,
                    library_code=lib_code,
                    class_no=class_no,
                    class_no_clean=normalize_kdc(class_no),
                    class_no_num=extract_class_no_num(class_no),
                    book_code=book_code,
                    call_number=call_number,
                    normalized_call_number=normalize_text(call_number),
                    shelf_loc_name=row.get('shelfLocName', ''),
                    separate_shelf_name=row.get('separateShelfName', ''),
                    copy_code=row.get('copyCode', '')
                )
                session.add(holding)
                
                count += 1
                if count % 100 == 0:
                    print(f"Imported {count} rows...")
                    await session.commit()
            
            await session.commit()
            print(f"Successfully imported total {count} rows into the database!")

if __name__ == "__main__":
    csv_file = r"c:\dev\comp_lib\worker\exports\노원중앙도서관_API추출 3천건정도.csv"
    asyncio.run(import_csv_to_db(csv_file))
