"""
노원중앙도서관 장서 EDA.

입력: exports/nowon_111058_raw.jsonl  (collect_nowon.py 산출물)
산출:
  - exports/nowon_111058_books.csv          : 평탄화한 전체 장서 CSV (도서관 비교용 데이터셋)
  - exports/nowon_111058_eda_kdc.csv        : KDC 대분류 분포
  - exports/nowon_111058_eda_summary.csv    : 지표 한 줄 요약 (CSV)
  - exports/nowon_111058_summary.txt        : 사람이 읽는 한 줄 요약

지표 정의:
  - 장서규모            : 레코드 수(numFound 단위, itemSrch type=ALL)
  - ISBN 결측률         : isbn13 가 빈 값인 비율
  - 저자기호(도서기호)  : callNumbers[].callNumber.book_code. 결측 = book_code 빈 값 비율
  - 청구기호            : class_no + ' ' + book_code 로 구성. 결측 = class_no 또는 book_code 중 하나라도 비어 구성 불가한 비율
  - KDC 분포 다양성     : 등장한 KDC 대분류 수(/10) + Shannon entropy(정규화)
  - 복본 비율           : isbn13(비공백) 기준 1 - 고유ISBN수/ISBN보유레코드수 (= 추가 복본 비중)
"""
import csv
import json
import math
import pathlib
from collections import Counter

ROOT = pathlib.Path(__file__).resolve().parents[1]
RAW = ROOT / "exports" / "nowon_111058_raw.jsonl"
EXPORTS = ROOT / "exports"

KDC_MAIN = {
    "0": "000 총류",
    "1": "100 철학",
    "2": "200 종교",
    "3": "300 사회과학",
    "4": "400 자연과학",
    "5": "500 기술과학",
    "6": "600 예술",
    "7": "700 언어",
    "8": "800 문학",
    "9": "900 역사",
}


def first_callnumber(doc):
    cns = doc.get("callNumbers") or []
    if not cns:
        return {}
    return cns[0].get("callNumber", {}) or {}


def kdc_main_of(class_no: str):
    class_no = (class_no or "").strip()
    if not class_no or not class_no[0].isdigit():
        return None
    return class_no[0]


def main():
    rows = []
    with RAW.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))

    n = len(rows)
    if n == 0:
        raise SystemExit("no records")

    # 평탄화 + CSV
    cols = ["isbn13", "set_isbn13", "bookname", "authors", "publisher",
            "publication_year", "class_no", "class_nm", "kdc_main",
            "book_code", "call_number", "shelf_loc_code", "shelf_loc_name",
            "separate_shelf_code", "separate_shelf_name", "copy_code",
            "vol", "addition_symbol", "reg_date", "num_callnumbers"]
    books_csv = EXPORTS / "nowon_111058_books.csv"
    isbn_counter = Counter()
    kdc_counter = Counter()
    miss_isbn = miss_classno = miss_bookcode = miss_callnumber = 0
    multi_cn = 0
    total_copies = 0

    with books_csv.open("w", newline="", encoding="utf-8-sig") as fp:
        w = csv.DictWriter(fp, fieldnames=cols)
        w.writeheader()
        for d in rows:
            cn = first_callnumber(d)
            class_no = (d.get("class_no") or "").strip()
            book_code = (cn.get("book_code") or "").strip()
            isbn = (d.get("isbn13") or "").strip()
            ncn = len(d.get("callNumbers") or [])
            kmain = kdc_main_of(class_no)

            if not isbn:
                miss_isbn += 1
            else:
                isbn_counter[isbn] += 1
            if not class_no:
                miss_classno += 1
            if not book_code:
                miss_bookcode += 1
            if not class_no or not book_code:
                miss_callnumber += 1
            if kmain:
                kdc_counter[kmain] += 1
            if ncn > 1:
                multi_cn += 1
            total_copies += max(ncn, 1)

            call_number = f"{class_no} {book_code}".strip() if (class_no and book_code) else ""
            w.writerow({
                "isbn13": isbn, "set_isbn13": d.get("set_isbn13", ""),
                "bookname": d.get("bookname", ""), "authors": d.get("authors", ""),
                "publisher": d.get("publisher", ""), "publication_year": d.get("publication_year", ""),
                "class_no": class_no, "class_nm": d.get("class_nm", ""), "kdc_main": kmain or "",
                "book_code": book_code, "call_number": call_number,
                "shelf_loc_code": cn.get("shelf_loc_code", ""), "shelf_loc_name": cn.get("shelf_loc_name", ""),
                "separate_shelf_code": cn.get("separate_shelf_code", ""), "separate_shelf_name": cn.get("separate_shelf_name", ""),
                "copy_code": cn.get("copy_code", ""), "vol": d.get("vol", ""),
                "addition_symbol": d.get("addition_symbol", ""), "reg_date": d.get("reg_date", ""),
                "num_callnumbers": ncn,
            })

    # KDC 분포 CSV
    kdc_csv = EXPORTS / "nowon_111058_eda_kdc.csv"
    with kdc_csv.open("w", newline="", encoding="utf-8-sig") as fp:
        w = csv.writer(fp)
        w.writerow(["kdc_main", "label", "count", "ratio"])
        classified = sum(kdc_counter.values())
        for k in [str(i) for i in range(10)]:
            c = kdc_counter.get(k, 0)
            w.writerow([k, KDC_MAIN[k], c, round(c / n, 6)])
        unclassified = n - classified
        w.writerow(["NA", "미분류/비KDC", unclassified, round(unclassified / n, 6)])

    # 다양성 지표
    present_classes = sum(1 for k in [str(i) for i in range(10)] if kdc_counter.get(k, 0) > 0)
    classified = sum(kdc_counter.values())
    entropy = 0.0
    if classified:
        for k in [str(i) for i in range(10)]:
            c = kdc_counter.get(k, 0)
            if c:
                p = c / classified
                entropy -= p * math.log(p, 2)
    norm_entropy = entropy / math.log(10, 2)  # 0~1

    # 복본
    isbn_records = sum(isbn_counter.values())
    distinct_isbn = len(isbn_counter)
    dup_ratio_isbn = (1 - distinct_isbn / isbn_records) if isbn_records else 0.0

    def pct(x):
        return round(100 * x, 3)

    summary = {
        "library": "노원중앙도서관",
        "lib_code": "111058",
        "collection_size": n,
        "isbn_missing_rate_pct": pct(miss_isbn / n),
        "classno_missing_rate_pct": pct(miss_classno / n),
        "bookcode_missing_rate_pct": pct(miss_bookcode / n),
        "callnumber_missing_rate_pct": pct(miss_callnumber / n),
        "kdc_classes_present": f"{present_classes}/10",
        "kdc_norm_entropy": round(norm_entropy, 4),
        "dup_copy_rate_isbn_pct": pct(dup_ratio_isbn),
        "records_with_isbn": isbn_records,
        "distinct_isbn": distinct_isbn,
        "records_multi_callnumber": multi_cn,
        "total_copies_incl_multi": total_copies,
    }

    sum_csv = EXPORTS / "nowon_111058_eda_summary.csv"
    with sum_csv.open("w", newline="", encoding="utf-8-sig") as fp:
        w = csv.writer(fp)
        w.writerow(list(summary.keys()))
        w.writerow(list(summary.values()))

    one_line = (
        f"[노원중앙도서관/111058] 장서규모 {n:,}건 | "
        f"ISBN결측률 {summary['isbn_missing_rate_pct']}% | "
        f"KDC분포다양성 {present_classes}/10대분류, 정규화엔트로피 {summary['kdc_norm_entropy']} | "
        f"저자기호(도서기호)결측률 {summary['bookcode_missing_rate_pct']}% "
        f"(청구기호구성불가 {summary['callnumber_missing_rate_pct']}%) | "
        f"복본비율(ISBN기준) {summary['dup_copy_rate_isbn_pct']}%"
    )
    (EXPORTS / "nowon_111058_summary.txt").write_text(one_line + "\n", encoding="utf-8")

    print("=== KDC 대분류 분포 ===")
    for k in [str(i) for i in range(10)]:
        c = kdc_counter.get(k, 0)
        print(f"  {KDC_MAIN[k]:<12} {c:>8,}  {100*c/n:6.2f}%")
    print(f"  {'미분류/비KDC':<12} {n-classified:>8,}  {100*(n-classified)/n:6.2f}%")
    print()
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print()
    print(one_line)
    print()
    print("written:")
    for p in [books_csv, kdc_csv, sum_csv, EXPORTS / "nowon_111058_summary.txt"]:
        print("  ", p)


if __name__ == "__main__":
    main()
