"""
Reads a YAML config describing datasets and query parts, generates SPARQL with a template,
paginates via LIMIT/OFFSET against a common SPARQL endpoint, parses results, and bulk-indexes
documents into OpenSearch.

Install:
  pip install pyyaml requests opensearch-py tqdm

Example:
  python indexOpenSearchFromSparql.py \
    --config config.yml \
    --endpoint "https://YOUR-SPARQL-ENDPOINT/sparql" \
    --dataset aat \
    --os-host localhost \
    --os-port 9200 \
    --os-index rds-entities \
    --page-size 1000
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional

import requests
from opensearchpy import OpenSearch, RequestsHttpConnection, helpers
from tqdm.auto import tqdm

from lib.utils import load_config, RDS_GRAPH_NAMESPACE, RDS_ONTOLOGY_NAMESPACE


# ----------------------------
# SPARQL generation
# ----------------------------

SUBJECT_QUERY_TEMPLATE = """\
{prefixes}
SELECT DISTINCT ?subject WHERE {{
    GRAPH <{types_graph}> {{
        {type_constraint_block}
        ?subject a ?queryType .
    }}

    GRAPH <{dataset_graph}> {{
        ?subject a ?type .
    }}

    GRAPH <{labels_graph}> {{
        {pref_label_block}
    }}
}}
ORDER BY ?subject
LIMIT {limit}
OFFSET {offset}
"""

INDEX_QUERY_TEMPLATE = """\
{prefixes}
SELECT
  ?subject
  (GROUP_CONCAT(DISTINCT STR(?prefLabel); SEPARATOR="||") AS ?prefLabels)
  (GROUP_CONCAT(DISTINCT STR(?type); SEPARATOR="||") AS ?types)
  (GROUP_CONCAT(DISTINCT ?typeClass; SEPARATOR="||") AS ?typeClasses)
  (GROUP_CONCAT(DISTINCT STR(?label); SEPARATOR="||") AS ?labels)
  ?description
WHERE {{
    VALUES ?subject {{
        {subject_values}
    }}
    GRAPH <{types_graph}> {{
        {type_constraint_block}
        ?subject a ?queryType .
    }}
    GRAPH <{dataset_graph}> {{
        ?subject a ?type .
    }}
    GRAPH <{labels_graph}> {{
        {pref_label_block}
    }}

    OPTIONAL {{
        GRAPH <{dataset_graph}> {{
            {description_block}
        }}
    }}

    OPTIONAL {{
        GRAPH <{dataset_graph}> {{
            {labels_block}
        }}
    }}
}}
GROUP BY ?subject ?description
"""

COUNT_QUERY_TEMPLATE = """\
{prefixes}
SELECT (COUNT(DISTINCT ?subject) as ?total)
WHERE {{
    GRAPH <{types_graph}> {{
        {type_constraint_block}
        ?subject a ?queryType .
    }}

    GRAPH <{dataset_graph}> {{
        ?subject a ?type .
    }}

    GRAPH <{labels_graph}> {{
        {pref_label_block}
    }}
}}
"""

MATCHES_QUERY_TEMPLATE = """\
{prefixes}
SELECT
  ?subject
  (GROUP_CONCAT(DISTINCT STR(?match); SEPARATOR="||") AS ?matches)
  (COUNT(DISTINCT ?match) AS ?numMatches)
WHERE {{
    VALUES ?subject {{
        {subject_values}
    }}

    GRAPH <http://schema.swissartresearch.net/rds/exact-match-statements> {{
        {{ ?subject <http://schema.swissartresearch.net/ontology/rds#related> ?match . }}
    }}
}}
GROUP BY ?subject
ORDER BY ?subject
"""


def _build_type_constraint_block(types_by_class: Dict[str, List[str]]) -> str:
    """
    Builds a SPARQL block that constrains ?queryType to be one of the given types, grouped by their classes.
    """
    if not types_by_class:
        return ""
    rows = []
    for type_class in types_by_class.keys():
        type_class_uri = f"<{RDS_ONTOLOGY_NAMESPACE}{type_class}>"
        rows.append(f"( \"{type_class}\" {type_class_uri} )")
    values_block = "VALUES (?typeClass ?queryType) {\n  " + "\n  ".join(rows) + "\n}"
    return values_block

def _generate_prefixes(prefixes: Dict[str, str]) -> str:
    items = sorted(prefixes.items(), key=lambda kv: kv[0])
    return "\n".join([f"PREFIX {p}: <{uri}>" for p, uri in items])

def _prepare_query_parts(dataset_config: Dict[str, Any]) -> Dict[str, str]:
    prefixes = _generate_prefixes(dataset_config.get("prefixes", {}))
    dataset_graph = dataset_config["graph"]

    type_constraint_block = _build_type_constraint_block(dataset_config.get("types", []))

    queries = dataset_config.get("queries", {})
    missing = [k for k in ("prefLabel", "labels", "description") if not queries.get(k)]
    if missing:
        raise ValueError(f"Dataset queries missing required parts: {', '.join(missing)}")

    pref_label_block = f"?subject <{RDS_ONTOLOGY_NAMESPACE}label> ?prefLabel ."
    labels_block = queries["labels"].replace("?value", "?label")
    description_block = queries["description"].replace("?value", "?description")
    types_graph = RDS_GRAPH_NAMESPACE + "types"
    labels_graph = RDS_GRAPH_NAMESPACE + "labels"

    return {
        "prefixes": prefixes,
        "dataset_graph": dataset_graph,
        "types_graph": types_graph,
        "labels_graph": labels_graph,
        "type_constraint_block": type_constraint_block,
        "pref_label_block": pref_label_block,
        "labels_block": labels_block,
        "description_block": description_block,
    }

def build_count_query(dataset_config: Dict[str, Any]) -> str:
    parts = _prepare_query_parts(dataset_config)
    return COUNT_QUERY_TEMPLATE.format(**parts)

def build_index_query(dataset_config: Dict[str, Any], subjects: List[str]) -> str:
    parts = _prepare_query_parts(dataset_config)
    subject_values = "\n        ".join(f"<{subject}>" for subject in subjects)
    return INDEX_QUERY_TEMPLATE.format(**parts, subject_values=subject_values)

def build_matches_query(dataset_config: Dict[str, Any], subjects: List[str]) -> str:
    parts = _prepare_query_parts(dataset_config)
    subject_values = "\n        ".join(f"<{subject}>" for subject in subjects)
    return MATCHES_QUERY_TEMPLATE.format(**parts, subject_values=subject_values)

def build_subjects_query(dataset_config: Dict[str, Any], limit: int, offset: int) -> str:
    parts = _prepare_query_parts(dataset_config)
    return SUBJECT_QUERY_TEMPLATE.format(**parts, limit=limit, offset=offset)


# ----------------------------
# SPARQL HTTP + parsing
# ----------------------------

@dataclass
class SparqlClient:
    endpoint: str
    timeout_s: int = 60
    user_agent: str = "sparql-to-opensearch/1.3 (+requests)"
    max_retries: int = 3
    retry_sleep_s: float = 2.0

    def query(self, sparql: str) -> Dict[str, Any]:
        headers = {
            "Accept": "application/sparql-results+json",
            "User-Agent": self.user_agent,
        }

        last_error: Optional[Exception] = None

        for attempt in range(1, self.max_retries + 1):
            try:
                resp = requests.post(
                    self.endpoint,
                    data={"query": sparql},
                    headers=headers,
                    timeout=self.timeout_s,
                )

                if resp.status_code == 200:
                    return resp.json()

                raise RuntimeError(
                    f"SPARQL endpoint returned HTTP {resp.status_code}\n"
                    f"Response (first 1000 chars):\n{resp.text[:1000]}"
                )

            except Exception as e:
                last_error = e
                if attempt < self.max_retries:
                    sleep_time = self.retry_sleep_s * attempt
                    tqdm.write(
                        f"[SPARQL] attempt {attempt}/{self.max_retries} failed, retrying in {sleep_time:.1f}s...",
                        file=sys.stderr,
                    )
                    time.sleep(sleep_time)
                else:
                    break

        raise RuntimeError(
            f"SPARQL query failed after {self.max_retries} attempts"
        ) from last_error


def _get_binding_value(binding: Dict[str, Any], var: str) -> Optional[str]:
    v = binding.get(var)
    if not v:
        return None
    return v.get("value")

def parse_count(results_json: Dict[str, Any]) -> int:
    bindings = results_json.get("results", {}).get("bindings", [])
    if not bindings:
        raise RuntimeError("COUNT query returned no bindings")
    val = bindings[0].get("total", {}).get("value")
    if val is None:
        raise RuntimeError("COUNT query missing ?total binding")
    try:
        return int(val)
    except ValueError as e:
        raise RuntimeError(f"COUNT query returned non-integer: {val!r}") from e

def parse_rows(results_json: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    bindings = results_json.get("results", {}).get("bindings", [])

    for b in bindings:
        subject = _get_binding_value(b, "subject")
        pref_labels_concat = _get_binding_value(b, "prefLabels")
        types_concat = _get_binding_value(b, "types") or ""
        type_classes_concat = _get_binding_value(b, "typeClasses") or ""
        labels_concat = _get_binding_value(b, "labels") or ""
        description = _get_binding_value(b, "description")

        types = [t for t in types_concat.split("||") if t] if types_concat else []
        type_classes = [tc for tc in type_classes_concat.split("||") if tc] if type_classes_concat else []
        labels = [l for l in labels_concat.split("||") if l] if labels_concat else []
        pref_labels = [pl for pl in pref_labels_concat.split("||") if pl] if pref_labels_concat else []

        if not subject:
            continue

        rows.append(
            {
                "uri": subject,
                "prefLabels": pref_labels,
                "labels": labels,
                "types": types,
                "typeClasses": type_classes,
                "description": description,
                "matches": [],
                "numMatches": 0,
            }
        )

    return rows


def parse_match_rows(results_json: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    rows_by_subject: Dict[str, Dict[str, Any]] = {}
    bindings = results_json.get("results", {}).get("bindings", [])

    for b in bindings:
        subject = _get_binding_value(b, "subject")
        if not subject:
            continue

        matches_concat = _get_binding_value(b, "matches") or ""
        num_matches_str = _get_binding_value(b, "numMatches") or "0"

        matches = [m for m in matches_concat.split("||") if m] if matches_concat else []

        try:
            num_matches = int(num_matches_str)
        except ValueError:
            num_matches = 0

        rows_by_subject[subject] = {
            "matches": matches,
            "numMatches": num_matches,
        }

    return rows_by_subject


# ----------------------------
# OpenSearch helpers
# ----------------------------

def make_os_client(
    host: str,
    port: int,
    username: Optional[str],
    password: Optional[str],
    use_ssl: bool,
    verify_certs: bool,
    timeout_s: int,
) -> OpenSearch:
    http_auth = (username, password) if username and password else None
    return OpenSearch(
        hosts=[{"host": host, "port": port}],
        http_auth=http_auth,
        use_ssl=use_ssl,
        verify_certs=verify_certs,
        connection_class=RequestsHttpConnection,
        timeout=timeout_s,
        max_retries=3,
        retry_on_timeout=True,
    )

def ensure_index(os_client: OpenSearch, index_name: str) -> None:
    if os_client.indices.exists(index=index_name):
        return

    body = {
        "settings": {
            "index": {
                "number_of_shards": 1,
                "number_of_replicas": 1,
            }
        },
        "mappings": {
            "properties": {
                "uri": {"type": "keyword"},
                "prefLabels": {
                    "type": "text",
                    "fields": {"raw": {"type": "keyword", "ignore_above": 256}},
                },
                "labels": {"type": "text"},
                "types": {"type": "keyword"},
                "typeClasses": {"type": "keyword"},
                "matches": {"type": "keyword"},
                "dataset": {"type": "keyword"},
                "description": {"type": "text"},
                "numMatches": {"type": "integer"},
            }
        },
    }
    os_client.indices.create(index=index_name, body=body)

def iter_bulk_actions(index_name: str, rows: Iterable[Dict[str, Any]]) -> Iterable[Dict[str, Any]]:
    for r in rows:
        uri = r.get("uri")
        if not uri:
            continue
        yield {
            "_op_type": "index",
            "_index": index_name,
            "_id": uri,
            "_source": r,
        }


def iter_bulk_update_actions(
    index_name: str,
    rows: Iterable[Dict[str, Any]],
) -> Iterable[Dict[str, Any]]:
    for r in rows:
        uri = r.get("uri")
        if not uri:
            continue
        yield {
            "_op_type": "update",
            "_index": index_name,
            "_id": uri,
            "doc": {
                "matches": r.get("matches", []),
                "numMatches": r.get("numMatches", 0),
            },
            "doc_as_upsert": False,
        }


def bulk_index(os_client: OpenSearch, index_name: str, rows: List[Dict[str, Any]], chunk_size: int) -> int:
    success, errors = helpers.bulk(
        os_client,
        iter_bulk_actions(index_name, rows),
        chunk_size=chunk_size,
        request_timeout=120,
        raise_on_error=False,
        raise_on_exception=False,
    )
    if errors:
        tqdm.write(
            f"Bulk completed with {len(errors)} errors (showing first 3):",
            file=sys.stderr,
        )
        tqdm.write(
            json.dumps(errors[:3], indent=2, ensure_ascii=False)[:4000],
            file=sys.stderr,
        )
    return int(success)

def bulk_update_matches(os_client: OpenSearch, index_name: str, rows: List[Dict[str, Any]], chunk_size: int) -> int:
    success, errors = helpers.bulk(
        os_client,
        iter_bulk_update_actions(index_name, rows),
        chunk_size=chunk_size,
        request_timeout=120,
        raise_on_error=False,
        raise_on_exception=False,
    )
    if errors:
        tqdm.write(
            f"Bulk update completed with {len(errors)} errors (showing first 3):",
            file=sys.stderr,
        )
        tqdm.write(
            json.dumps(errors[:3], indent=2, ensure_ascii=False)[:4000],
            file=sys.stderr,
        )
    return int(success)


# ----------------------------
# Main loop
# ----------------------------

def iter_dataset_rows(
    sparql_client: SparqlClient,
    dataset_config: Dict[str, Any],
    page_size: int,
    max_pages: Optional[int],
    sleep_s: float,
) -> Iterable[Dict[str, Any]]:
    offset = 0
    page = 0

    while True:
        if max_pages is not None and page >= max_pages:
            break

        sparql = build_index_query(dataset_config, limit=page_size, offset=offset)
        data = sparql_client.query(sparql)
        rows = parse_rows(data)

        if not rows:
            break

        for r in rows:
            yield r

        page += 1
        offset += page_size

        if sleep_s > 0:
            time.sleep(sleep_s)

def update_matches_for_batch(
    sparql_client: SparqlClient,
    os_client: OpenSearch,
    dataset_config: Dict[str, Any],
    index_name: str,
    uris: List[str],
    bulk_chunk_size: int,
) -> int:
    if not uris:
        return 0

    sparql = build_matches_query(dataset_config, uris)
    data = sparql_client.query(sparql)
    match_rows_by_subject = parse_match_rows(data)

    updates: List[Dict[str, Any]] = []
    for uri in uris:
        match_row = match_rows_by_subject.get(uri)
        if match_row is None:
            updates.append(
                {
                    "uri": uri,
                    "matches": [],
                    "numMatches": 0,
                }
            )
        else:
            updates.append(
                {
                    "uri": uri,
                    "matches": match_row["matches"],
                    "numMatches": match_row["numMatches"],
                }
            )

    return bulk_update_matches(os_client, index_name, updates, chunk_size=bulk_chunk_size)

def index_dataset_to_opensearch(
    sparql_client: SparqlClient,
    os_client: OpenSearch,
    dataset_config: Dict[str, Any],
    index_name: str,
    dataset_name: str,
    page_size: int,
    max_pages: Optional[int],
    sleep_s: float,
    bulk_chunk_size: int,
) -> int:
    ensure_index(os_client, index_name)

    count_query = build_count_query(dataset_config)
    total_expected = parse_count(sparql_client.query(count_query))

    buffer: List[Dict[str, Any]] = []
    unique_done = 0
    seen_uris: set[str] = set()
    start_time = time.time()

    with tqdm(
        total=total_expected,
        desc=f"Indexing {dataset_name}",
        unit="entity",
        dynamic_ncols=True,
        file=sys.stderr,
    ) as pbar:
        for row in iter_dataset_rows(
            sparql_client=sparql_client,
            dataset_config=dataset_config,
            page_size=page_size,
            max_pages=max_pages,
            sleep_s=sleep_s,
        ):
            uri = row.get("uri")
            if not uri:
                continue

            if uri in seen_uris:
                continue

            seen_uris.add(uri)
            unique_done += 1
            pbar.update(1)

            row["dataset"] = dataset_name
            buffer.append(row)

            if len(buffer) >= bulk_chunk_size:
                bulk_index(os_client, index_name, buffer, chunk_size=bulk_chunk_size)

                uris = [r["uri"] for r in buffer]
                update_matches_for_batch(
                    sparql_client=sparql_client,
                    os_client=os_client,
                    dataset_config=dataset_config,
                    index_name=index_name,
                    uris=uris,
                    bulk_chunk_size=bulk_chunk_size,
                )

                buffer.clear()

                elapsed = time.time() - start_time
                rate = (unique_done / elapsed) if elapsed > 0 else 0.0
                pbar.set_postfix(rate=f"{rate:.1f}/s")

        if buffer:
            bulk_index(os_client, index_name, buffer, chunk_size=bulk_chunk_size)

            uris = [r["uri"] for r in buffer]
            update_matches_for_batch(
                sparql_client=sparql_client,
                os_client=os_client,
                dataset_config=dataset_config,
                index_name=index_name,
                uris=uris,
                bulk_chunk_size=bulk_chunk_size,
            )

            buffer.clear()

            elapsed = time.time() - start_time
            rate = (unique_done / elapsed) if elapsed > 0 else 0.0
            pbar.set_postfix(rate=f"{rate:.1f}/s")

    os_client.indices.refresh(index=index_name)
    tqdm.write("Done!", file=sys.stderr)
    return unique_done

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True, help="Path to YAML configuration")
    ap.add_argument("--endpoint", required=True, help="Common SPARQL endpoint URL")
    ap.add_argument("--dataset", required=True, help="Dataset key in YAML under datasets: (e.g. aat, gnd)")

    ap.add_argument("--page-size", type=int, default=1000, help="SPARQL LIMIT per page")
    ap.add_argument("--max-pages", type=int, default=None, help="Stop after N pages (debug/testing)")
    ap.add_argument("--sleep", type=float, default=0.0, help="Sleep between pages (seconds)")
    ap.add_argument("--sparql-timeout", type=int, default=60, help="SPARQL HTTP timeout seconds")
    ap.add_argument("--sparql-retries", type=int, default=3, help="SPARQL retry attempts")
    ap.add_argument("--sparql-retry-sleep", type=float, default=2.0, help="Base sleep time between SPARQL retries (seconds)")

    ap.add_argument("--os-host", default="localhost", help="OpenSearch host")
    ap.add_argument("--os-port", type=int, default=9200, help="OpenSearch port")
    ap.add_argument("--os-user", default=None, help="OpenSearch username (optional)")
    ap.add_argument("--os-pass", default=None, help="OpenSearch password (optional)")
    ap.add_argument("--os-ssl", action="store_true", help="Use SSL (https) for OpenSearch")
    ap.add_argument("--os-no-verify-certs", action="store_true", help="Disable TLS cert verification")
    ap.add_argument("--os-timeout", type=int, default=60, help="OpenSearch client timeout seconds")
    ap.add_argument("--os-index", required=True, help="OpenSearch index name")

    ap.add_argument("--bulk-chunk-size", type=int, default=2000, help="Bulk indexing chunk size")
    args = ap.parse_args()

    cfg = load_config(args.config)
    datasets = cfg.get("datasets", {})
    if args.dataset not in datasets:
        available = ", ".join(sorted(datasets.keys()))
        print(f"Dataset '{args.dataset}' not found in config. Available: {available}", file=sys.stderr)
        return 2

    dataset_config = datasets[args.dataset]

    sparql_client = SparqlClient(
        endpoint=args.endpoint,
        timeout_s=args.sparql_timeout,
        max_retries=args.sparql_retries,
        retry_sleep_s=args.sparql_retry_sleep,
    )

    os_client = make_os_client(
        host=args.os_host,
        port=args.os_port,
        username=args.os_user,
        password=args.os_pass,
        use_ssl=args.os_ssl,
        verify_certs=(not args.os_no_verify_certs),
        timeout_s=args.os_timeout,
    )

    total = index_dataset_to_opensearch(
        sparql_client=sparql_client,
        os_client=os_client,
        dataset_config=dataset_config,
        index_name=args.os_index,
        dataset_name=args.dataset,
        page_size=args.page_size,
        max_pages=args.max_pages,
        sleep_s=args.sleep,
        bulk_chunk_size=args.bulk_chunk_size,
    )

    tqdm.write(f"Indexed {total} entities into '{args.os_index}'", file=sys.stderr)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())