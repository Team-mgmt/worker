import time
from typing import Any, Dict, Iterator, Optional

import requests

from worker.core.config import settings


def collect_item_srch(
    lib_code: str,
    start_page: int = 1,
    max_pages: Optional[int] = None,
    page_size: int = 100,
    kdc: Optional[str] = None,
    start_year: int = 2026,
    end_year: int = 2016,
) -> Iterator[Dict[str, Any]]:
    base_url = "http://data4library.kr/api/itemSrch"
    api_key = settings.JUNGBO_NARU_API_KEY
    if not api_key:
        raise ValueError("JUNGBO_NARU_API_KEY is not set")

    pages_fetched = 0

    for year in range(start_year, end_year - 1, -1):
        start_dt = f"{year}-01-01"
        end_dt = f"{year}-12-31"
        current_page = start_page if year == start_year else 1

        print(f"Fetching data for year {year}...")

        while True:
            if max_pages is not None and pages_fetched >= max_pages:
                return

            params = {
                "authKey": api_key,
                "libCode": lib_code,
                "type": "ALL",
                "startDt": start_dt,
                "endDt": end_dt,
                "pageNo": current_page,
                "pageSize": page_size,
                "format": "json",
            }
            if kdc:
                params["kdc"] = kdc[0]

            docs = []
            max_retries = 10
            for attempt in range(1, max_retries + 1):
                try:
                    response = requests.get(base_url, params=params, timeout=30)
                    response.raise_for_status()

                    if not response.text.strip():
                        raise ValueError("Empty response received from API, likely rate limited.")

                    data = response.json()
                    response_body = data.get("response", {})
                    if "errCode" in response_body:
                        err_code = response_body.get("errCode")
                        if err_code == "outOflimit":
                            raise PermissionError(
                                "Daily data4library API limit exceeded for this key."
                            )
                        raise ValueError(f"API Error: {response_body.get('error', err_code)}")

                    docs = response_body.get("docs", [])
                    break
                except Exception as exc:
                    print(
                        f"Error fetching year {year} page {current_page} "
                        f"(attempt {attempt}/{max_retries}): {exc}"
                    )
                    if attempt >= max_retries:
                        print(
                            f"Failed to fetch year {year} page {current_page}; "
                            "moving to next year."
                        )
                        docs = []
                        break
                    time.sleep(60)

            if not docs:
                break

            for doc in docs:
                yield doc.get("doc", {})

            pages_fetched += 1
            current_page += 1
            time.sleep(3.0)
