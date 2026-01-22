#!/usr/bin/env python3
"""
sparql_to_opensearch.py

Reads a YAML config describing datasets and query parts, generates SPARQL with a fixed template,
paginates via LIMIT/OFFSET against a common SPARQL endpoint, parses results, and bulk-indexes
documents into OpenSearch.

Install:
  pip install pyyaml requests opensearch-py

Example:
  python sparql_to_opensearch.py \
    --config config.yml \
    --endpoint "https://YOUR-SPARQL-ENDPOINT/sparql" \
    --dataset aat \
    --os-host localhost \
    --os-port 9200 \
    --os-index aat_entities \
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
import yaml
from opensearchpy import OpenSearch, RequestsHttpConnection, helpers


# ----------------------------
# SPARQL generation
# ----------------------------

FIXED_QUERY_TEMPLATE = """\
{prefixes}
SELECT
  ?subject
  ?prefLabel
  (GROUP_CONCAT(DISTINCT STR(?type);SEPARATOR="||") as ?types)
  (GROUP_CONCAT(?label;SEPARATOR="||") as ?labels)
  ?description
  (COUNT(?match) as ?numMatches)
WHERE {{
  GRAPH <{graph}> {{
    ?subject a {required_class}, ?type .
{pref_label_block}
{labels_block}
{description_block}
  }}
{matches_optional_block}
}}
GROUP BY ?subject ?prefLabel ?description
ORDER BY ?subject
LIMIT {limit}
OFFSET {offset}
"""

FIXED_MATCHES_OPTIONAL_BLOCK = """\
  OPTIONAL {
    GRAPH <http://schema.swissartresearch.net/rds/exact-match-statements> {
      ?subject <http://schema.swissartresearch.net/ontology/rds#related> ?match .
    }
  }"""


def _prefix_lines(prefixes: Dict[str, str]) -> str:
    items = sorted(prefixes.items(), key=lambda kv: kv[0])
    return "\n".join([f"PREFIX {p}: <{uri}>" for p, uri in items])


def _indent_block(block: str, spaces: int = 4) -> str:
    pad = " " * spaces
    lines = [ln.rstrip() for ln in block.strip("\n").splitlines()]
    return "\n".join(pad + ln if ln else "" for ln in lines) + "\n"


def _get_required_class(dataset_cfg: Dict[str, Any]) -> str:
    """
    This function expects exactly one required class per dataset (first entry under first types-group).
    """
    types_cfg = dataset_cfg.get("types", {})
    if not types_cfg:
        raise ValueError("Dataset is missing 'types' (e.g. types: {concept: [gvp:Concept]}).")

    first_group = next(iter(types_cfg.keys()))
    required_classes = types_cfg[first_group]
    if not isinstance(required_classes, list) or not required_classes:
        raise ValueError("Dataset 'types' must contain a non-empty list of required classes.")

    if len(required_classes) != 1:
        raise ValueError(
            "This script currently expects exactly one required class per dataset. "
            "If you need multiple required classes, we can switch to VALUES/UNION."
        )
    return required_classes[0]


def build_query(dataset_cfg: Dict[str, Any], limit: int, offset: int) -> str:
    prefixes = _prefix_lines(dataset_cfg.get("prefixes", {}))
    graph = dataset_cfg["graph"]
    required_class = _get_required_class(dataset_cfg)

    queries = dataset_cfg.get("queries", {})
    pref_label_block = queries.get("prefLabel", "")
    labels_block = queries.get("labels", "")
    description_block = queries.get("description", "")

    missing = [k for k in ("prefLabel", "labels", "description") if not queries.get(k)]
    if missing:
        raise ValueError(f"Dataset queries missing required parts: {', '.join(missing)}")

    return FIXED_QUERY_TEMPLATE.format(
        prefixes=prefixes,
        graph=graph,
        required_class=required_class,
        pref_label_block=_indent_block(pref_label_block, 4).rstrip("\n"),
        labels_block=_indent_block(labels_block, 4).rstrip("\n"),
        description_block=_indent_block(description_block, 4).rstrip("\n"),
        matches_optional_block=FIXED_MATCHES_OPTIONAL_BLOCK,
        limit=limit,
        offset=offset,
    )


# ----------------------------
# SPARQL HTTP + parsing
# ----------------------------

@dataclass
class SparqlClient:
    endpoint: str
    timeout_s: int = 60
    user_agent: str = "sparql-to-opensearch/1.0 (+requests)"

    def query(self, sparql: str) -> Dict[str, Any]:
        headers = {
            "Accept": "application/sparql-results+json",
            "User-Agent": self.user_agent,
        }
        resp = requests.post(
            self.endpoint,
            data={"query": sparql},
            headers=headers,
            timeout=self.timeout_s,
        )
        if resp.status_code != 200:
            raise RuntimeError(
                f"SPARQL endpoint error {resp.status_code}\n"
                f"Response (first 2000 chars):\n{resp.text[:2000]}\n\n"
                f"Query (first 4000 chars):\n{sparql[:4000]}"
            )
        return resp.json()


def _get_binding_value(binding: Dict[str, Any], var: str) -> Optional[str]:
    v = binding.get(var)
    if not v:
        return None
    return v.get("value")


def parse_rows(results_json: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    bindings = results_json.get("results", {}).get("bindings", [])

    for b in bindings:
        subject = _get_binding_value(b, "subject")
        pref_label = _get_binding_value(b, "prefLabel")
        types_concat = _get_binding_value(b, "types") or ""
        labels_concat = _get_binding_value(b, "labels") or ""
        description = _get_binding_value(b, "description")
        num_matches_str = _get_binding_value(b, "numMatches") or "0"

        types = [t for t in types_concat.split("||") if t] if types_concat else []
        labels = [l for l in labels_concat.split("||") if l] if labels_concat else []

        try:
            relevance = int(num_matches_str)
        except ValueError:
            relevance = 0

        if not subject:
            continue

        rows.append(
            {
                "uri": subject,
                "prefLabel": pref_label,
                "labels": labels,
                "types": types,
                "description": description,
                "relevance": relevance,
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
                "prefLabel": {
                    "type": "text",
                    "fields": {"raw": {"type": "keyword", "ignore_above": 256}},
                },
                "labels": {"type": "text"},
                "types": {"type": "keyword"},
                "description": {"type": "text"},
                "relevance": {"type": "integer"},
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
            "_op_type": "index",   # overwrite if exists
            "_index": index_name,
            "_id": uri,            # stable doc id = subject URI
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
    dataset_cfg: Dict[str, Any],
    page_size: int,
    max_pages: Optional[int],
    sleep_s: float,
) -> Iterable[Dict[str, Any]]:
    offset = 0
    page = 0

    while True:
        if max_pages is not None and page >= max_pages:
            break

        sparql = build_query(dataset_cfg, limit=page_size, offset=offset)
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
    dataset_cfg: Dict[str, Any],
    index_name: str,
    page_size: int,
    max_pages: Optional[int],
    sleep_s: float,
    bulk_chunk_size: int,
) -> int:
    ensure_index(os_client, index_name)

    buffer: List[Dict[str, Any]] = []
    total_indexed = 0

    for row in iter_dataset_rows(
        sparql_client=sparql_client,
        dataset_cfg=dataset_cfg,
        page_size=page_size,
        max_pages=max_pages,
        sleep_s=sleep_s,
    ):
        buffer.append(row)

        if len(buffer) >= bulk_chunk_size:
            total_indexed += bulk_index(os_client, index_name, buffer, chunk_size=bulk_chunk_size)
            buffer.clear()

    if buffer:
        total_indexed += bulk_index(os_client, index_name, buffer, chunk_size=bulk_chunk_size)

    os_client.indices.refresh(index=index_name)
    return total_indexed


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True, help="Path to YAML configuration")
    ap.add_argument("--endpoint", required=True, help="Common SPARQL endpoint URL")
    ap.add_argument("--dataset", required=True, help="Dataset key in YAML under datasets: (e.g. aat)")

    ap.add_argument("--page-size", type=int, default=1000, help="SPARQL LIMIT per page")
    ap.add_argument("--max-pages", type=int, default=None, help="Stop after N pages (debug/testing)")
    ap.add_argument("--sleep", type=float, default=0.0, help="Sleep between pages (seconds)")
    ap.add_argument("--sparql-timeout", type=int, default=60, help="SPARQL HTTP timeout seconds")

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

    dataset_cfg = datasets[args.dataset]

    sparql_client = SparqlClient(endpoint=args.endpoint, timeout_s=args.sparql_timeout)

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
        dataset_cfg=dataset_cfg,
        index_name=args.os_index,
        page_size=args.page_size,
        max_pages=args.max_pages,
        sleep_s=args.sleep,
        bulk_chunk_size=args.bulk_chunk_size,
    )

    print(f"Indexed {total} docs into '{args.os_index}'", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())