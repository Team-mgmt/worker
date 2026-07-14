"""
정보나루(Data4Library) itemSrch 전체 장서 수집기 — libCode를 인자로 받는 범용 버전.
(scripts/collect_nowon.py를 기반으로, 노원(111058)에 하드코딩됐던 부분을 인자화함)

- pageSize 단위로 페이지를 나눠 ThreadPool로 병렬 수집
- 페이지별 결과를 exports/shards_<libCode>/page_XXXXX.json 으로 저장 -> 재개(resume) 가능
- 타임아웃/throttle(JSON 아님)/빈 응답 시 지수 백오프 재시도
- 모든 페이지 확보되면 exports/<libCode>_raw.jsonl 로 합침

usage:
    python scripts/collect_library.py --lib-code 111189 --name dobong
    python scripts/collect_library.py --lib-code 111058 --name nowon   # 기존 노원과 동일 동작
"""
import argparse
import json
import math
import pathlib
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

ROOT = pathlib.Path(__file__).resolve().parents[1]
PAGE_SIZE = 200
MAX_WORKERS = 6
MAX_RETRIES = 6
BASE_URL = "http://data4library.kr/api/itemSrch"


def get_key() -> str:
    txt = (ROOT / ".env").read_text(encoding="utf-8")
    m = re.search(r"JUNGBO_NARU_API_KEY=(\S+)", txt)
    if not m:
        raise SystemExit("JUNGBO_NARU_API_KEY not found in .env")
    return m.group(1)


def fetch_meta(key: str, lib_code: str):
    r = requests.get(BASE_URL, params={
        "authKey": key, "libCode": lib_code, "type": "ALL",
        "pageNo": 1, "pageSize": 1, "format": "json"}, timeout=60)
    return r.json()["response"]["numFound"]


def fetch_page(key: str, lib_code: str, shard_dir: pathlib.Path, page_no: int):
    """한 페이지를 받아 doc 리스트를 반환. 재시도 포함."""
    shard = shard_dir / f"page_{page_no:05d}.json"
    if shard.exists():
        return page_no, "cached"

    last_err = None
    for attempt in range(MAX_RETRIES):
        try:
            r = requests.get(BASE_URL, params={
                "authKey": key, "libCode": lib_code, "type": "ALL",
                "pageNo": page_no, "pageSize": PAGE_SIZE, "format": "json"}, timeout=90)
            r.raise_for_status()
            data = r.json()  # throttle 시 JSON 아님 -> 예외
            resp = data.get("response", {})
            # 일일 호출 한도(IP 미등록 500/일) 초과 시 errCode 반환 -> 즉시 중단 신호
            if resp.get("errCode"):
                return page_no, f"OUTOFLIMIT: {resp.get('error')}"
            docs = [d.get("doc", {}) for d in resp.get("docs", [])]
            # 빈 docs 는 정상 페이지에선 나올 수 없음(마지막 페이지도 일부 채워짐) -> 재시도
            if not docs:
                raise ValueError("empty docs (throttle/limit suspected)")
            shard.write_text(json.dumps(docs, ensure_ascii=False), encoding="utf-8")
            return page_no, len(docs)
        except Exception as e:  # noqa: BLE001
            last_err = e
            time.sleep(min(2 ** attempt, 30))
    return page_no, f"FAILED: {last_err}"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--lib-code", required=True, help="정보나루 libCode (예: 도봉아이나라도서관=111189)")
    ap.add_argument("--name", required=True, help="출력 파일 접두어로 쓸 짧은 이름 (예: dobong)")
    args = ap.parse_args()

    key = get_key()
    shard_dir = ROOT / "exports" / f"shards_{args.name}"
    out_jsonl = ROOT / "exports" / f"{args.name}_{args.lib_code}_raw.jsonl"
    shard_dir.mkdir(parents=True, exist_ok=True)

    num_found = fetch_meta(key, args.lib_code)
    total_pages = math.ceil(num_found / PAGE_SIZE)
    print(f"libCode={args.lib_code} numFound={num_found}, total_pages={total_pages}, "
          f"pageSize={PAGE_SIZE}, workers={MAX_WORKERS}", flush=True)

    pages = list(range(1, total_pages + 1))
    done = 0
    failures = []
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futs = {ex.submit(fetch_page, key, args.lib_code, shard_dir, p): p for p in pages}
        for fut in as_completed(futs):
            pno, res = fut.result()
            done += 1
            if isinstance(res, str) and res.startswith("FAILED"):
                failures.append(pno)
            if done % 50 == 0 or done == total_pages:
                el = time.time() - t0
                rate = done / el if el else 0
                eta = (total_pages - done) / rate if rate else 0
                print(f"  {done}/{total_pages} pages | {el:.0f}s elapsed | ETA {eta:.0f}s | failures={len(failures)}", flush=True)

    if failures:
        print(f"retrying {len(failures)} failed pages sequentially...", flush=True)
        for p in failures:
            pno, res = fetch_page(key, args.lib_code, shard_dir, p)
            print(f"  retry page {pno}: {res}", flush=True)

    # assemble
    shards = sorted(shard_dir.glob("page_*.json"))
    total = 0
    with out_jsonl.open("w", encoding="utf-8") as out:
        for sh in shards:
            docs = json.loads(sh.read_text(encoding="utf-8"))
            for d in docs:
                out.write(json.dumps(d, ensure_ascii=False) + "\n")
                total += 1
    print(f"DONE. wrote {total} records to {out_jsonl} (numFound={num_found})", flush=True)
    if total != num_found:
        print(f"WARNING: collected {total} != numFound {num_found}", flush=True)


if __name__ == "__main__":
    main()
