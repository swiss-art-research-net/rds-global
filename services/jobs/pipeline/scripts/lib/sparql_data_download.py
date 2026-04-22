import time
from pathlib import Path

import requests
from tqdm import tqdm


def _retry_delay(response: requests.Response | None, attempt: int, base_delay_s: float) -> float:
    if response is not None:
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                return max(float(retry_after), base_delay_s)
            except ValueError:
                pass
    return base_delay_s * (2 ** attempt)


def run_sparql_get(
    *,
    endpoint: str,
    query: str,
    accept: str,
    max_retries: int = 6,
    base_delay_s: float = 2.0,
) -> requests.Response:
    headers = {"Accept": accept}
    response = None
    for attempt in range(max_retries + 1):
        response = requests.get(
            endpoint,
            params={"query": query},
            headers=headers,
            timeout=120,
        )
        if response.status_code == 200:
            return response
        if response.status_code not in {429, 500, 502, 503, 504}:
            response.raise_for_status()
        if attempt >= max_retries:
            response.raise_for_status()
        delay_s = _retry_delay(response, attempt, base_delay_s)
        print(
            f"Request throttled or failed with {response.status_code}; "
            f"sleeping {delay_s:.1f}s before retry {attempt + 1}/{max_retries}."
        )
        time.sleep(delay_s)
    raise RuntimeError("SPARQL request failed without returning a response")


def count_distinct_subjects(nt_payload: str) -> int:
    subjects = set()
    for line in nt_payload.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        subject, _, _ = stripped.partition(" ")
        if subject:
            subjects.add(subject)
    return len(subjects)


def fetch_total_count(*, endpoint: str, count_query: str) -> int:
    response = run_sparql_get(
        endpoint=endpoint,
        query=count_query,
        accept="application/sparql-results+json",
    )
    data = response.json()
    bindings = data.get("results", {}).get("bindings", [])
    if not bindings:
        raise RuntimeError("Count query returned no bindings")
    first_row = bindings[0]
    for key in ("count", "total"):
        if key in first_row and "value" in first_row[key]:
            return int(first_row[key]["value"])
    raise RuntimeError("Count query must return ?count or ?total")


def download_construct_query(
    *,
    query: str,
    endpoint: str,
    out_path: Path,
    page_size: int,
    offset: int = 0,
    count_query: str | None = None,
    max_retries: int = 6,
    base_delay_s: float = 2.0,
    inter_page_delay_s: float = 0.5,
) -> None:
    page = offset // page_size if page_size > 0 else 0
    current_offset = offset
    has_results = True
    progress = None
    if count_query:
        total_count = fetch_total_count(endpoint=endpoint, count_query=count_query)
        print(f"Total count from count query: {total_count}")
        progress = tqdm(
            total=total_count,
            initial=min(offset, total_count),
            desc="Downloading entities",
            unit="entity",
        )
        progress.set_postfix({"offset": current_offset})

    while has_results:
        paged_query = f"{query}\nLIMIT {page_size} OFFSET {current_offset}"
        response = run_sparql_get(
            endpoint=endpoint,
            query=paged_query,
            accept="application/n-triples",
            max_retries=max_retries,
            base_delay_s=base_delay_s,
        )

        page_file = out_path / f"data_page_{page}.nt"
        payload = response.text.strip()
        if not payload:
            has_results = False
            print("No more results, finished downloading.")
            break

        with open(page_file, "w", encoding="utf-8") as f:
            f.write(payload)
            if not payload.endswith("\n"):
                f.write("\n")

        if progress is not None:
            progress.update(count_distinct_subjects(payload))
            progress.set_postfix({"offset": current_offset})

        page += 1
        current_offset += page_size
        time.sleep(inter_page_delay_s)

    if progress is not None:
        progress.close()
