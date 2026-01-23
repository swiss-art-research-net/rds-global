#!/usr/bin/env python3
"""
Reads a YAML config describing datasets and query parts, generates SPARQL with a template,
paginates via LIMIT/OFFSET against a common SPARQL endpoint, parses results, and bulk-indexes
documents into OpenSearch.

Install:
  pip install pyyaml requests opensearch-py

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
from typing import Any, Dict, Iterable, List, Optional, Tuple

import requests
import yaml
from opensearchpy import OpenSearch, RequestsHttpConnection, helpers


# ----------------------------
# SPARQL generation
# ----------------------------

INDEX_QUERY_TEMPLATE = """\
{prefixes}
SELECT
  ?subject
  (GROUP_CONCAT(DISTINCT STR(?prefLabel); SEPARATOR="||") AS ?prefLabels)
  (GROUP_CONCAT(DISTINCT STR(?type); SEPARATOR="||") AS ?types)
  (GROUP_CONCAT(DISTINCT ?typeClass; SEPARATOR="||") AS ?typeClasses)
  (GROUP_CONCAT(DISTINCT STR(?label); SEPARATOR="||") AS ?labels)
  (GROUP_CONCAT(DISTINCT STR(?match); SEPARATOR="||") AS ?matches)
  (MIN(?description_raw) AS ?description)
  (COUNT(DISTINCT ?match) AS ?numMatches)
WHERE {{
  {{
    SELECT ?subject ?type ?typeClass WHERE {{
      GRAPH <{graph}> {{
        {type_constraint_block}
      }}
    }}
    ORDER BY ?subject
    LIMIT {limit}
    OFFSET {offset}
  }}

  GRAPH <{graph}> {{
    {pref_label_block}
    {description_block}
  }} 
  
  OPTIONAL {{
    GRAPH <{graph}> {{
        {labels_block}
    }}
  }}
  OPTIONAL {{
    GRAPH <http://schema.swissartresearch.net/rds/exact-match-statements> {{
      ?subject <http://schema.swissartresearch.net/ontology/rds#related> ?match .
    }}
  }}
}}
GROUP BY ?subject
ORDER BY ?subject
"""

COUNT_QUERY_TEMPLATE = """\
{prefixes}
SELECT (COUNT(DISTINCT ?subject) as ?total)
WHERE {{
  GRAPH <{graph}> {{
    {type_constraint_block}
    FILTER EXISTS {{
        {pref_label_block}
        {description_block}
    }}
  }}
}}
"""

def _build_type_constraint_block(class_pairs: List[Tuple[str, str]]) -> str:
    """
    Constrain subjects to ANY allowed requiredClass, and bind the corresponding typeClass label.

    VALUES (?requiredClass ?typeClass) {
      (gnd:DifferentiatedPerson "actor")
      (gnd:Work "artwork")
      ...
    }
    ?subject a ?requiredClass, ?type .
    """
    if not class_pairs:
        raise ValueError("No (requiredClass, typeClass) pairs found in dataset.types.")

    # Escape double quotes in group names just in case
    rows = []
    for required_class, type_class in class_pairs:
        safe_label = type_class.replace('"', '\\"')
        rows.append(f'({required_class} "{safe_label}")')

    values_rows = "\n      ".join(rows)
    block = f"""\
    VALUES (?requiredClass ?typeClass) {{
      {values_rows}
    }}
    ?subject a ?requiredClass, ?type ."""
    return block

def _collect_required_class_pairs(dataset_config: Dict[str, Any]) -> List[Tuple[str, str]]:
    """
    Build pairs of (requiredClassQName, typeClassLabel) from dataset.types.

    Example:
      types:
        actor: [gnd:DifferentiatedPerson, gnd:Gods]
        artwork: [gnd:Work]

    Produces:
      [("gnd:DifferentiatedPerson","actor"), ("gnd:Gods","actor"), ("gnd:Work","artwork"), ...]
    """
    types_cfg = dataset_config.get("types", {})
    if not isinstance(types_cfg, dict) or not types_cfg:
        raise ValueError("Dataset is missing 'types' or it is not a dict of groups -> class lists.")

    pairs: List[Tuple[str, str]] = []
    for group_name, class_list in types_cfg.items():
        if not isinstance(group_name, str) or not group_name.strip():
            raise ValueError(f"Invalid types group name: {group_name!r}")
        if not isinstance(class_list, list) or not class_list:
            raise ValueError(f"types.{group_name} must be a non-empty list.")

        for c in class_list:
            if not isinstance(c, str) or not c.strip():
                raise ValueError(f"Invalid class value in types.{group_name}: {c!r}")
            pairs.append((c.strip(), group_name.strip()))

    # De-dup pairs while preserving order
    seen = set()
    deduped: List[Tuple[str, str]] = []
    for p in pairs:
        if p not in seen:
            seen.add(p)
            deduped.append(p)

    return deduped

def _generate_prefixes(prefixes: Dict[str, str]) -> str:
    items = sorted(prefixes.items(), key=lambda kv: kv[0])
    return "\n".join([f"PREFIX {p}: <{uri}>" for p, uri in items])

def _prepare_query_parts(dataset_config: Dict[str, Any]) -> Dict[str, str]:
    prefixes = _generate_prefixes(dataset_config.get("prefixes", {}))
    graph = dataset_config["graph"]

    class_pairs = _collect_required_class_pairs(dataset_config)
    type_constraint_block = _build_type_constraint_block(class_pairs)

    queries = dataset_config.get("queries", {})
    missing = [k for k in ("prefLabel", "labels", "description") if not queries.get(k)]
    if missing:
        raise ValueError(f"Dataset queries missing required parts: {', '.join(missing)}")

    pref_label_block = queries["prefLabel"].replace("?value", "?prefLabel")
    labels_block = queries["labels"].replace("?value", "?label")
    description_block = queries["description"].replace("?value", "?description_raw")

    return {
        "prefixes": prefixes,
        "graph": graph,
        "type_constraint_block": type_constraint_block,
        "pref_label_block": pref_label_block,
        "labels_block": labels_block,
        "description_block": description_block,
    }

def build_count_query(dataset_config: Dict[str, Any]) -> str:
    parts = _prepare_query_parts(dataset_config)
    return COUNT_QUERY_TEMPLATE.format(**parts)

def build_query(dataset_config: Dict[str, Any], limit: int, offset: int) -> str:
    parts = _prepare_query_parts(dataset_config)
    return INDEX_QUERY_TEMPLATE.format(**parts, limit=limit, offset=offset)


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

                # Non-200 response → retryable error
                raise RuntimeError(
                    f"SPARQL endpoint returned HTTP {resp.status_code}\n"
                    f"Response (first 1000 chars):\n{resp.text[:1000]}"
                )

            except Exception as e:
                last_error = e
                if attempt < self.max_retries:
                    sleep_time = self.retry_sleep_s * attempt  # simple linear backoff
                    print(
                        f"[SPARQL] attempt {attempt}/{self.max_retries} failed, retrying in {sleep_time:.1f}s…",
                        file=sys.stderr,
                    )
                    time.sleep(sleep_time)
                else:
                    break

        # All retries exhausted
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
        matches_concat = _get_binding_value(b, "matches") or ""
        description = _get_binding_value(b, "description")
        num_matches_str = _get_binding_value(b, "numMatches") or "0"

        types = [t for t in types_concat.split("||") if t] if types_concat else []
        type_classes = [tc for tc in type_classes_concat.split("||") if tc] if type_classes_concat else []
        labels = [l for l in labels_concat.split("||") if l] if labels_concat else []
        pref_labels = [pl for pl in pref_labels_concat.split("||") if pl] if pref_labels_concat else []
        matches = [m for m in matches_concat.split("||") if m] if matches_concat else []

        try:
            num_matches = int(num_matches_str)
        except ValueError:
            num_matches = 0

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
                "matches": matches,
                "numMatches": num_matches,
            }
        )

    return rows

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
        print(f"Bulk completed with {len(errors)} errors (showing first 3):", file=sys.stderr)
        print(json.dumps(errors[:3], indent=2, ensure_ascii=False)[:4000], file=sys.stderr)
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

        sparql = build_query(dataset_config, limit=page_size, offset=offset)
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

def load_config(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

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

    print(
        f"Indexing {total_expected} entities for the dataset {dataset_name}...",
        file=sys.stderr,
    )

    buffer: List[Dict[str, Any]] = []
    unique_done = 0
    seen_uris: set[str] = set()
    start_time = time.time()

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

        row["dataset"] = dataset_name
        buffer.append(row)

        if len(buffer) >= bulk_chunk_size:
            bulk_index(os_client, index_name, buffer, chunk_size=bulk_chunk_size)
            buffer.clear()

            elapsed = time.time() - start_time
            rate = (unique_done / elapsed) if elapsed > 0 else 0.0
            pct = (unique_done / total_expected * 100.0) if total_expected > 0 else 0.0

            print(
                f"{pct:.1f}% "
                f"({rate:.1f} entities/s)",
                file=sys.stderr,
            )

    if buffer:
        bulk_index(os_client, index_name, buffer, chunk_size=bulk_chunk_size)
        buffer.clear()

        elapsed = time.time() - start_time
        rate = (unique_done / elapsed) if elapsed > 0 else 0.0
        pct = (unique_done / total_expected * 100.0) if total_expected > 0 else 0.0
        print(f"{pct:.1f}% ({rate:.1f} entities/s)", file=sys.stderr)

    os_client.indices.refresh(index=index_name)
    print(f"Done!", file=sys.stderr)
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

    print(f"Indexed {total} entities into '{args.os_index}'", file=sys.stderr)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())