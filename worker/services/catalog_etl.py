import unicodedata
from typing import List, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.dialects.postgresql import insert
from worker.db_models.catalog import Book, Holding

def normalize_kdc(class_no: str) -> str:
    if not class_no:
        return ""
    return unicodedata.normalize("NFKC", class_no)

def generate_call_number(class_no: str, book_code: str) -> str:
    parts = []
    if class_no:
        parts.append(class_no)
    if book_code:
        parts.append(book_code)
    return " ".join(parts)

def normalize_text(text: str) -> str:
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    return " ".join(text.split()).strip().lower()

async def process_and_load_items(session: AsyncSession, lib_code: str, items: List[Dict[str, Any]]):
    for item in items:
        isbn13 = item.get("isbn13") or None
        bookname = item.get("bookname", "")
        authors = item.get("authors", "")
        publisher = item.get("publisher", "")
        pub_year = item.get("publication_year", "")
        bookImageURL = item.get("bookImageURL", "")
        
        class_no = item.get("class_no", "")
        book_code = item.get("book_code", "")
        vol = item.get("vol", "")
        copy_code = item.get("copy_code", "")
        shelf_loc_name = item.get("shelf_loc_name", "")

        normalized_bookname = normalize_text(bookname)
        normalized_authors = normalize_text(authors)

        # 1. Upsert Book
        book_stmt = insert(Book).values(
            isbn13=isbn13,
            bookname=bookname,
            normalized_bookname=normalized_bookname,
            authors=authors,
            normalized_authors=normalized_authors,
            publisher=publisher,
            publication_year=pub_year,
            book_image_url=bookImageURL
        )

        book_update_dict = {
            "bookname": bookname,
            "normalized_bookname": normalized_bookname,
            "authors": authors,
            "normalized_authors": normalized_authors
        }

        if isbn13:
            book_stmt = book_stmt.on_conflict_do_update(
                index_elements=['isbn13'],
                set_=book_update_dict
            ).returning(Book.book_id)
        else:
            # No ISBN to dedupe on: plain insert, one Book row per item.
            book_stmt = book_stmt.returning(Book.book_id)

        result = await session.execute(book_stmt)
        book_id = result.scalar_one_or_none()

        if not book_id and isbn13:
            # Fallback if no returning (isbn13 upsert path only; without an
            # isbn13 the plain insert above always returns a book_id directly).
            b_res = await session.execute(select(Book).where(Book.isbn13 == isbn13))
            b_obj = b_res.scalars().first()
            if b_obj:
                book_id = b_obj.book_id
        
        # 2. Upsert Holding
        if book_id:
            call_numbers = item.get("callNumbers", [])
            if not call_numbers:
                # Fallback if no callNumbers array
                call_numbers = [{"callNumber": {
                    "book_code": item.get("book_code", ""),
                    "shelf_loc_name": item.get("shelf_loc_name", ""),
                    "copy_code": item.get("copy_code", "")
                }}]

            for cn_wrapper in call_numbers:
                cn = cn_wrapper.get("callNumber", {})
                b_code = cn.get("book_code", "")
                s_loc_name = cn.get("shelf_loc_name", "")
                c_code = cn.get("copy_code", "")

                norm_class = normalize_kdc(class_no)
                call_num = generate_call_number(norm_class, b_code)
                
                holding = Holding(
                    book_id=book_id,
                    library_code=lib_code,
                    class_no=class_no,
                    class_no_clean=norm_class,
                    book_code=b_code,
                    call_number=call_num,
                    normalized_call_number=normalize_text(call_num),
                    shelf_loc_name=s_loc_name,
                    copy_code=c_code
                )
                session.add(holding)
    
    await session.commit()
