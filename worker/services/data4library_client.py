import requests
import time
from typing import Iterator, Dict, Any
from worker.core.config import settings

def collect_item_srch(lib_code: str, start_page: int = 1, max_pages: int = None, page_size: int = 100) -> Iterator[Dict[str, Any]]:
    base_url = "http://data4library.kr/api/itemSrch"
    api_key = settings.JUNGBO_NARU_API_KEY
    if not api_key:
        raise ValueError("JUNGBO_NARU_API_KEY is not set")

    current_page = start_page
    pages_fetched = 0

    while True:
        if max_pages is not None and pages_fetched >= max_pages:
            break

        params = {
            "authKey": api_key,
            "libCode": lib_code,
            "startDt": "2024-01-01",
            "endDt": "2026-12-31",
            "pageNo": current_page,
            "pageSize": page_size,
            "format": "json"
        }

        try:
            response = requests.get(base_url, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
            
            docs = data.get("response", {}).get("docs", [])
            if not docs:
                break # No more data

            for doc in docs:
                yield doc.get("doc", {})

            pages_fetched += 1
            current_page += 1
            
            # API Rate limit sleep
            time.sleep(0.5)

        except Exception as e:
            print(f"Error fetching page {current_page}: {e}")
            break
