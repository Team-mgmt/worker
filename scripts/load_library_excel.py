"""
도봉아이나라도서관(libCode=111189) 10만건 데이터셋 적재 테스트.

기존 scripts/import_csv.py는 행 단위 SELECT+INSERT라 10만 건 규모에서 매우 느리고,
source의 callNumber 컬럼을 그대로 쓰며(생성 함수 미사용), isbn13 결측 행은 홀딩까지
통째로 버린다. 이 스크립트는 그 문제들을 피해 배치(bulk) 방식으로 실제 적재 성능/정합성을
검증한다.
"""
import time
import math
import pandas as pd
from sqlalchemy import create_engine, text

from worker.services.catalog_etl import normalize_text, normalize_kdc, generate_call_number

LIB_CODE = "111189"
XLSX_PATH = "/mnt/user-data/uploads/도봉아이나라도서관_전체_데이터셋_10만건_.xlsx"
DB_URL = "postgresql+psycopg://shelfalign:shelfalign@localhost:5432/shelfalign"


def sval(v):
    """어떤 값이 와도 안전하게 '유효한 문자열' 또는 빈 문자열을 반환.
    None / float('nan') / pd.NA / 빈 문자열 -> ""  , 그 외 -> str(v).strip()
    (pandas 신형 string dtype은 결측치를 다시 읽을 때 float('nan')으로 반환하는
    경우가 있어, 흔한 `x or ""` 패턴은 NaN이 참(truthy)이라 걸러지지 않는 함정이 있음)"""
    if v is None:
        return ""
    if isinstance(v, float) and math.isnan(v):
        return ""
    try:
        if pd.isna(v):
            return ""
    except (TypeError, ValueError):
        pass
    s = str(v).strip()
    return s


def clean_str(v):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    s = str(v).strip()
    return s if s else None


def isbn_to_str(v):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    return str(int(v))


def num_to_str(v):
    # classNo/copyCode 등은 원본이 숫자(float)로 저장돼 있어 그대로 문자열화하면
    # "1.0" 처럼 어색해지는 대신, 정수면 정수형, 아니면 그대로 반환
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    if isinstance(v, float) and v.is_integer():
        return str(v)  # 1.30 같은 소수는 그대로 유지 (KDC는 소수 분류가 실제 규칙)
    return str(v)


def main():
    t0 = time.time()
    df = pd.read_excel(XLSX_PATH, sheet_name="Result_39")
    print(f"[1/4] 엑셀 로드 완료: {len(df)}행, {time.time()-t0:.1f}s")

    df["isbn13_clean"] = df["isbn13"].apply(isbn_to_str)
    df["classNo_str"] = df["classNo"].apply(num_to_str)
    df["bookCode_str"] = df["bookCode"].apply(clean_str)
    df["call_number_regen"] = df.apply(
        lambda r: generate_call_number(sval(r["classNo_str"]), sval(r["bookCode_str"])), axis=1
    )

    # --- Book: isbn13 기준 dedup (isbn13 없는 행은 book_id 없이 개별 책으로 취급) ---
    t1 = time.time()
    books_with_isbn = (
        df[df["isbn13_clean"].notnull()]
        .drop_duplicates(subset="isbn13_clean", keep="first")
        [["isbn13_clean", "bookname", "authors", "publisher", "publicationYear", "bookImageUrl"]]
    )
    books_without_isbn = (
        df[df["isbn13_clean"].isnull()]
        [["bookname", "authors", "publisher", "publicationYear", "bookImageUrl"]]
    )
    print(f"[2/4] Book 후보 정리: ISBN있음 {len(books_with_isbn)}종 / ISBN없음 {len(books_without_isbn)}종, {time.time()-t1:.1f}s")

    engine = create_engine(DB_URL)
    with engine.begin() as conn:
        # 1) ISBN 있는 책들 bulk insert
        book_rows = [
            {
                "isbn13": r.isbn13_clean,
                "bookname": sval(clean_str(r.bookname)),
                "normalized_bookname": normalize_text(sval(clean_str(r.bookname))),
                "authors": sval(clean_str(r.authors)),
                "normalized_authors": normalize_text(sval(clean_str(r.authors))),
                "publisher": sval(clean_str(r.publisher)),
                "publication_year": sval(num_to_str(r.publicationYear)),
                "book_image_url": sval(clean_str(r.bookImageUrl)),
            }
            for r in books_with_isbn.itertuples()
        ]
        # 2) ISBN 없는 책들 (isbn13=NULL, 여러 건 있어도 unique index 충돌 없음 -- 이전에 발견한 버그 수정 반영된 상태 확인)
        book_rows_no_isbn = [
            {
                "isbn13": None,
                "bookname": sval(clean_str(r.bookname)),
                "normalized_bookname": normalize_text(sval(clean_str(r.bookname))),
                "authors": sval(clean_str(r.authors)),
                "normalized_authors": normalize_text(sval(clean_str(r.authors))),
                "publisher": sval(clean_str(r.publisher)),
                "publication_year": sval(num_to_str(r.publicationYear)),
                "book_image_url": sval(clean_str(r.bookImageUrl)),
            }
            for r in books_without_isbn.itertuples()
        ]

        t2 = time.time()
        conn.execute(
            text("""INSERT INTO books (isbn13, bookname, normalized_bookname, authors, normalized_authors,
                     publisher, publication_year, book_image_url)
                     VALUES (:isbn13, :bookname, :normalized_bookname, :authors, :normalized_authors,
                     :publisher, :publication_year, :book_image_url)"""),
            book_rows,
        )
        if book_rows_no_isbn:
            conn.execute(
                text("""INSERT INTO books (isbn13, bookname, normalized_bookname, authors, normalized_authors,
                         publisher, publication_year, book_image_url)
                         VALUES (:isbn13, :bookname, :normalized_bookname, :authors, :normalized_authors,
                         :publisher, :publication_year, :book_image_url)"""),
                book_rows_no_isbn,
            )
        print(f"[3/4] books 적재 완료: {len(book_rows) + len(book_rows_no_isbn)}건, {time.time()-t2:.1f}s")

        # isbn13 -> book_id 매핑 조회 (holdings 연결용)
        isbn_to_bookid = dict(conn.execute(text("SELECT isbn13, book_id FROM books WHERE isbn13 IS NOT NULL")).fetchall())

        # ISBN 없는 책은 bookname+authors+publisher 로 방금 넣은 book_id 역추적 (순서 보존 가정 안 하고 재조회)
        no_isbn_lookup = {}
        if book_rows_no_isbn:
            res = conn.execute(text(
                "SELECT book_id, bookname, authors, publisher FROM books WHERE isbn13 IS NULL"
            )).fetchall()
            for bid, bn, au, pub in res:
                no_isbn_lookup.setdefault((bn, au, pub), []).append(bid)

        # --- Holdings: 원본 104,653행 전부 (isbn13 유무 상관없이 holding은 항상 생성) ---
        t3 = time.time()
        holding_rows = []
        used_no_isbn_idx = {}
        for r in df.itertuples():
            isbn13_val = sval(r.isbn13_clean)
            if isbn13_val:
                book_id = isbn_to_bookid.get(isbn13_val)
            else:
                key = (sval(clean_str(r.bookname)), sval(clean_str(r.authors)), sval(clean_str(r.publisher)))
                idx = used_no_isbn_idx.get(key, 0)
                candidates = no_isbn_lookup.get(key, [])
                book_id = candidates[idx] if idx < len(candidates) else (candidates[0] if candidates else None)
                used_no_isbn_idx[key] = idx  # 같은 책 반복 매칭은 첫 후보 재사용

            class_no_str = sval(r.classNo_str)
            holding_rows.append({
                "book_id": book_id,
                "library_code": LIB_CODE,
                "class_no": class_no_str,
                "class_no_clean": normalize_kdc(class_no_str),
                "class_no_num": float(class_no_str) if class_no_str and class_no_str.replace(".", "", 1).isdigit() else None,
                "book_code": sval(r.bookCode_str),
                "call_number": sval(r.call_number_regen),
                "normalized_call_number": normalize_text(sval(r.call_number_regen)),
                "shelf_loc_name": sval(clean_str(r.shelfLocName)),
                "separate_shelf_name": sval(clean_str(r.separateShelfName)),
                "copy_code": sval(num_to_str(r.copyCode)),
            })

        conn.execute(
            text("""INSERT INTO holdings (book_id, library_code, class_no, class_no_clean, class_no_num,
                     book_code, call_number, normalized_call_number, shelf_loc_name, separate_shelf_name, copy_code)
                     VALUES (:book_id, :library_code, :class_no, :class_no_clean, :class_no_num,
                     :book_code, :call_number, :normalized_call_number, :shelf_loc_name, :separate_shelf_name, :copy_code)"""),
            holding_rows,
        )
        print(f"[4/4] holdings 적재 완료: {len(holding_rows)}건, {time.time()-t3:.1f}s")

    # --- 검증 쿼리 ---
    with engine.connect() as conn:
        book_cnt = conn.execute(text("SELECT COUNT(*) FROM books")).scalar()
        holding_cnt = conn.execute(text("SELECT COUNT(*) FROM holdings")).scalar()
        orphan_cnt = conn.execute(text("SELECT COUNT(*) FROM holdings WHERE book_id IS NULL")).scalar()
        dup_isbn = conn.execute(text(
            "SELECT COUNT(*) FROM (SELECT isbn13 FROM books WHERE isbn13 IS NOT NULL GROUP BY isbn13 HAVING COUNT(*)>1) t"
        )).scalar()
        sample = conn.execute(text(
            "SELECT b.bookname, b.isbn13, h.class_no, h.book_code, h.call_number, h.shelf_loc_name "
            "FROM holdings h JOIN books b ON b.book_id=h.book_id ORDER BY h.holding_id LIMIT 5"
        )).fetchall()

    total_t = time.time() - t0
    print("\n=== 최종 검증 ===")
    print(f"books 행 수      : {book_cnt}  (기대: {len(books_with_isbn)+len(books_without_isbn)})")
    print(f"holdings 행 수   : {holding_cnt}  (기대: {len(df)})")
    print(f"book_id NULL인 holding(고아 데이터) : {orphan_cnt}")
    print(f"isbn13 중복(unique 위반 여부)      : {dup_isbn}")
    print(f"총 소요 시간     : {total_t:.1f}s")
    print("\n=== 샘플 5건 (holdings JOIN books) ===")
    for s in sample:
        print(f"  {s.bookname[:20]:<22} | isbn={s.isbn13} | class_no={s.class_no} | book_code={s.book_code} | call_number='{s.call_number}' | shelf={s.shelf_loc_name}")


if __name__ == "__main__":
    main()
