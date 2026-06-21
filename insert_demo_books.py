import sys
import asyncio
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from sqlalchemy.ext.asyncio import AsyncSession
from worker.core.database import AsyncSessionLocal
from worker.db_models.catalog import Book, Holding

async def insert_demo_books():
    books_data = [
        {"title": "지우전", "author": "박영광", "class_no": "813.6", "book_code": "박62ㅈ"},
        {"title": "나비사냥 SEASON 2", "author": "박영광", "class_no": "813.6", "book_code": "박64ㄴ v.2"},
        {"title": "폴리스", "author": "박영광", "class_no": "813.6", "book_code": "박67ㅍ"},
        {"title": "러브 어게인", "author": "박영", "class_no": "813.6", "book_code": "박64ㄹ"},
        {"title": "못된 정신의 확산", "author": "박영광", "class_no": "813.6", "book_code": "박64ㅁ"},
        {"title": "지상의 방 한 칸", "author": "박영광", "class_no": "813.6", "book_code": "박64ㅈ"},
        {"title": "영어로 영어를 가르치자!", "author": "황인기", "class_no": "740", "book_code": "황19ㅇ"}
    ]
    
    async with AsyncSessionLocal() as session:
        for i, bd in enumerate(books_data):
            # Create Book
            isbn13 = f"demo_isbn_{i}"
            new_book = Book(
                isbn13=isbn13,
                bookname=bd["title"],
                normalized_bookname=bd["title"].replace(" ", ""),
                authors=bd["author"],
                normalized_authors=bd["author"].replace(" ", ""),
                publisher="데모출판사",
                publication_year="2020"
            )
            session.add(new_book)
            await session.flush()
            
            # Create Holding
            new_holding = Holding(
                book_id=new_book.book_id,
                library_code="111058",
                class_no=bd["class_no"],
                class_no_clean=bd["class_no"].split(".")[0] if "." in bd["class_no"] else bd["class_no"],
                class_no_num=float(bd["class_no"]) if bd["class_no"].replace(".", "").isdigit() else 0.0,
                book_code=bd["book_code"],
                call_number=f"{bd['class_no']} {bd['book_code']}",
                shelf_loc_code="DEMO",
                shelf_loc_name="노원중앙종합자료실"
            )
            session.add(new_holding)
            
        await session.commit()
        print("Demo books inserted successfully!")

if __name__ == "__main__":
    asyncio.run(insert_demo_books())
