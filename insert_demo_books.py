import uuid
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
import re
from worker.core.config import settings

def normalize_string(s: str) -> str:
    if not s:
        return ""
    return re.sub(r'[^\w\uAC00-\uD7A3]', '', s).lower()

books = [
    ("813.6 박62ㅇ", "부엉이 소녀 욜란드", "박애진"),
    ("813.6 박62ㅈ", "지우전 (모두 나를 칼이라 했다)", "박애진"),
    ("813.6 박63ㅇ", "영매 소녀 O 박에스더", "박애진"),
    ("813.6 박64ㄴ", "나의 고독한 두리안 나무", "박영란"),
    ("813.6 박64ㄴ v.2", "나비사냥", "박영광"),
    ("813.6 박64ㅅ", "시그니처", "박영광"),
    ("813.6 박67ㅍ", "폴리스", "박영란"),
    ("813.6 박64ㄹ", "라구나 이야기 외전", "박영란"),
    ("813.6 박64ㄹ", "러브 어게인", "박영광"),
    ("813.6 박64ㅁ v.2", "머나먼 쏭바강 제2부", "박영광"),
    ("813.6 박64모", "못된 정신의 확산", "박영란"),
    ("813.6 박64ㅅ", "쉿, 고요히", "박영란"),
    ("813.6 박64여", "여름과 루비", "박연준"),
    ("813.6 박64우", "운동장이 없는 학교", "박영희"),
    ("813.6 박64ㅈ", "지상의 방 한 칸", "박영한"),
    ("813.6 박64ㅈ", "조귀인", "박영주"),
    ("740 황19ㅇ", "영원히 영어를 가르치자!", "황정희"),
]

def clean_class_no(class_no: str) -> str:
    return re.sub(r"[^\d.]", "", class_no)

def main():
    library_code = "111058"
    engine = create_engine(settings.DATABASE_URL.replace("postgresql://", "postgresql+psycopg://"))
    
    with Session(engine) as session:
        # 1. Get Library ID
        res = session.execute(text('SELECT id FROM "Library" WHERE code = :code'), {"code": library_code})
        library_id = res.scalar()
        if not library_id:
            print("Library not found!")
            return

        print(f"Library ID: {library_id}")

        for call_number, title, author in books:
            book_id = str(uuid.uuid4())
            holding_id = str(uuid.uuid4())

            norm_title = normalize_string(title)
            norm_author = normalize_string(author)

            parts = call_number.split()
            class_no = parts[0] if parts else ""
            book_code = " ".join(parts[1:]) if len(parts) > 1 else ""
            class_no_clean = clean_class_no(class_no)
            class_no_num = float(class_no_clean) if class_no_clean else None
            norm_call_number = normalize_string(call_number)

            # Insert Book
            session.execute(
                text('''
                    INSERT INTO "LibraryBook" (id, bookname, "normalizedBookname", authors, "normalizedAuthors", "updatedAt")
                    VALUES (:id, :bookname, :norm_title, :authors, :norm_author, NOW())
                '''),
                {
                    "id": book_id,
                    "bookname": title,
                    "norm_title": norm_title,
                    "authors": author,
                    "norm_author": norm_author,
                }
            )

            # Insert Holding
            session.execute(
                text('''
                    INSERT INTO "LibraryHolding" (
                        id, "bookId", "libraryId", "libraryCode", "classNo", "classNoClean", "classNoNum", "bookCode", "callNumber", "normalizedCallNumber"
                    ) VALUES (
                        :id, :book_id, :lib_id, :lib_code, :class_no, :class_no_clean, :class_no_num, :book_code, :call_number, :norm_call
                    )
                '''),
                {
                    "id": holding_id,
                    "book_id": book_id,
                    "lib_id": library_id,
                    "lib_code": library_code,
                    "class_no": class_no,
                    "class_no_clean": class_no_clean,
                    "class_no_num": class_no_num,
                    "book_code": book_code,
                    "call_number": call_number,
                    "norm_call": norm_call_number,
                }
            )
            print(f"Inserted: {title} ({call_number})")
        
        session.commit()
        print("Done!")

if __name__ == "__main__":
    main()
