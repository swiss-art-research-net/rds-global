"""
# OpenSearch Search Proxy

A small FastAPI service that proxies search requests to an OpenSearch index.
The service exposes a `/search` endpoint which accepts a simple query string and translates it into an OpenSearch query.
It is designed to be used as a connector for ResearchSpace Ephedra services that are unable to construct complex OpenSearch queries on their own.

## Usage

Run the service:

    python app.py --opensearch-url http://localhost:9200 --index rds-entities --config config.yml

Optional authentication flags:

    python app.py --opensearch-url http://localhost:9200 --index rds-entities --config config.yml \
        --user admin --password admin

    python app.py --opensearch-url http://localhost:9200 --index rds-entities --config config.yml \
        --api-key "<your_api_key>"

Optional datasets argument to limit search to specific datasets defined in the config:

    python app.py --opensearch-url http://localhost:9200 --index rds-entities --config config.yml \
        --datasets "aat,gnd"

Optional maximum result limit to cap client requests:

    python app.py --opensearch-url http://localhost:9200 --index rds-entities --config config.yml \
        --max-limit 1000

You can also supply credentials via environment variables:
- OPENSEARCH_USER
- OPENSEARCH_PASSWORD
- OPENSEARCH_API_KEY

Example request:

    curl -X POST http://localhost:8000/search \
      -H "Content-Type: application/json" \
      -d '{"query":"Leonora Carrington"}'

"""

import argparse
import os
import json
from typing import Any, Dict, Optional, List

import httpx
import logging
import yaml
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, Field

app = FastAPI()

logger = logging.getLogger("opensearch_connector")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
level = os.getenv("LOG_LEVEL", "INFO").upper()
logger.setLevel(level)

DEFAULT_TOTAL_LIMIT = 100
DEFAULT_MAX_LIMIT = 1000


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=512)
    typeclass: Optional[str] = Field(default=None, max_length=128)
    dataset: Optional[str] = Field(default=None, max_length=128)
    limit: int = Field(default=DEFAULT_TOTAL_LIMIT, ge=1)


def sanitize_text(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None

    sanitized = value.strip()
    return sanitized or None


def parse_requested_datasets(value: Optional[str]) -> Optional[List[str]]:
    sanitized = sanitize_text(value)
    if sanitized is None:
        return None

    datasets = [dataset.strip() for dataset in sanitized.split(",") if dataset.strip()]
    return datasets or None


def sanitize_query(value: str) -> str:
    sanitized = value.strip()
    if not sanitized:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Query must not be blank.",
        )
    return sanitized


def resolve_dataset_names(
    config: Dict[str, Any],
    requested_datasets: Optional[List[str]] = None,
) -> List[str]:
    config_datasets = config.get("datasets", {})
    if not config_datasets:
        raise HTTPException(
            status_code=500,
            detail="OpenSearch connector misconfiguration: at least one dataset must be defined in 'datasets'.",
        )

    dataset_names = list(config_datasets.keys())

    if getattr(app.state, "datasets", None):
        dataset_names = [ds for ds in dataset_names if ds in app.state.datasets]

    if requested_datasets:
        allowed_datasets = set(dataset_names)
        dataset_names = []
        for dataset in requested_datasets:
            if dataset in allowed_datasets and dataset not in dataset_names:
                dataset_names.append(dataset)

    if not dataset_names:
        raise HTTPException(
            status_code=400,
            detail="No valid datasets found for the given criteria.",
        )

    return dataset_names

def build_msearch_query(
    q: str, 
    config: Dict[str, Any], 
    total_limit: int = DEFAULT_TOTAL_LIMIT,
    index: str = "rds-entities",
    typeclass_filter: Optional[str] = None,
    requested_datasets: Optional[List[str]] = None
) -> str:
    """
    Constructs an ndjson string for the OpenSearch _msearch endpoint.
    """
    msearch_payload = ""
    dataset_names = resolve_dataset_names(config=config, requested_datasets=requested_datasets)
    limit_per_dataset = max(1, total_limit // len(dataset_names))
    
    for dataset_name in dataset_names:
        header = {"index": index}

        must_conditions = [
            {"term": {"dataset": dataset_name}},
            {
                "multi_match": {
                    "query": q,
                    "fields": ["prefLabels^3", "labels"],
                    "operator": "and",
                    "fuzziness": "AUTO"
                }
            }
        ]
        if typeclass_filter:
            must_conditions.append({"term": {"typeClasses": typeclass_filter}})
        body = {
            "size": limit_per_dataset,
            "query": {
                "function_score": {
                    "query": {
                        "bool": {
                            "must": must_conditions,
                            "should": [
                                {"match_phrase": {"prefLabels": {"query": q, "boost": 10}}}
                            ]
                        }
                    },
                    "field_value_factor": {
                        "field": "numMatches",
                        "factor": 100,
                        "modifier": "sqrt",
                        "missing": 0
                    },
                    "boost_mode": "sum"
                }
            }
        }
        
        msearch_payload += json.dumps(header) + "\n"
        msearch_payload += json.dumps(body) + "\n"
        
    return msearch_payload

def normalize_entity_hits(
    response: Dict[str, Any],
    min_shared_matches: int = 1,
) -> Dict[str, Any]:
    """
    Normalize OpenSearch entity hits by grouping records that mutually
    reference each other via `_id` <-> `_source.matches`, or that share
    a configurable number of common values in `_source.matches`.

    For each connected group of equivalent records:
    - all members get the same `_score` = max score in the group
    - all members get `_reference` = deterministic representative `_id`

    Representative selection:
    1. highest original `_score`
    2. alphabetically smallest `_id`

    Rules for equivalence:
    - If A._id appears in B._source.matches and B._id appears in A._source.matches,
      then A and B are considered equivalent.
    - If A and B share at least `min_shared_matches` values in their
      `_source.matches`, they are considered equivalent.
    - Equivalence is transitively closed, so if A<->B and B<->C, all three are grouped.
    """
    result = response

    hits = result.get("hits", {}).get("hits", [])
    if not isinstance(hits, list) or not hits:
        return result

    if min_shared_matches is None:
        min_shared_matches = 0
    else:
        min_shared_matches = max(0, int(min_shared_matches))

    # Build lookup tables
    id_to_index: Dict[str, int] = {}
    id_to_matches: Dict[str, set] = {}
    id_to_score: Dict[str, float] = {}

    for i, hit in enumerate(hits):
        hit_id = hit.get("_id")
        if not hit_id:
            continue

        matches = hit.get("_source", {}).get("matches", []) or []
        if not isinstance(matches, list):
            matches = []

        id_to_index[hit_id] = i
        id_to_matches[hit_id] = set(matches)
        id_to_score[hit_id] = float(hit.get("_score", 0.0) or 0.0)

    # Build undirected graph of equivalent records.
    # Two hits are linked if they explicitly reference each other, or if
    # they share enough common matches.
    adjacency: Dict[str, set] = {hit_id: set() for hit_id in id_to_index}

    ids = sorted(id_to_index.keys())
    for i, a in enumerate(ids):
        matches_a = id_to_matches[a]
        for b in ids[i + 1:]:
            matches_b = id_to_matches[b]
            if a in matches_b and b in matches_a:
                adjacency[a].add(b)
                adjacency[b].add(a)

    match_to_ids: Dict[str, List[str]] = {}
    for hit_id in ids:
        for match in id_to_matches[hit_id]:
            match_to_ids.setdefault(match, []).append(hit_id)

    pair_shared_counts: Dict[tuple, int] = {}
    for shared_ids in match_to_ids.values():
        if len(shared_ids) < 2:
            continue

        shared_ids.sort()
        for i, a in enumerate(shared_ids):
            for b in shared_ids[i + 1:]:
                pair = (a, b)
                new_count = pair_shared_counts.get(pair, 0) + 1
                if new_count >= min_shared_matches:
                    adjacency[a].add(b)
                    adjacency[b].add(a)
                    pair_shared_counts.pop(pair, None)
                else:
                    pair_shared_counts[pair] = new_count

    # Find connected components
    visited = set()
    components: List[List[str]] = []

    for hit_id in ids:
        if hit_id in visited:
            continue

        stack = [hit_id]
        component = []

        while stack:
            current = stack.pop()
            if current in visited:
                continue
            visited.add(current)
            component.append(current)
            stack.extend(adjacency[current] - visited)

        components.append(component)

    # Normalize each component
    for component in components:
        if len(component) == 1:
            # Still add _reference to singletons for consistency
            ref_id = component[0]
            idx = id_to_index[ref_id]
            hits[idx]["_reference"] = ref_id
            continue

        max_score = max(id_to_score[hit_id] for hit_id in component)

        # Deterministic representative:
        # highest score desc, then _id asc
        ref_id = sorted(
            component,
            key=lambda hit_id: (-id_to_score[hit_id], hit_id),
        )[0]

        for hit_id in component:
            idx = id_to_index[hit_id]
            hits[idx]["_score"] = max_score
            hits[idx]["_reference"] = ref_id

    return result

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    # This captures the raw body that caused the error
    body = await request.body()
    logger.error(f"422 Error: {exc}")
    logger.error(f"Received Body: {body.decode()}")
    
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"detail": exc.errors(), "body": body.decode()},
    )

@app.get("/healthz")
def healthz() -> Dict[str, str]:
    return {"status": "ok"}

@app.post("/search")
async def search(body: SearchRequest) -> Any:
    endpoint: Optional[str] = getattr(app.state, "opensearch_url", None)
    index: Optional[str] = getattr(app.state, "opensearch_index", None)
    max_limit: int = getattr(app.state, "max_limit", DEFAULT_MAX_LIMIT)

    if not endpoint:
        raise HTTPException(status_code=500, detail="OpenSearch not configured")
    if not index:
        raise HTTPException(status_code=500, detail="OpenSearch index not configured")

    # Point to the global _msearch endpoint
    url = endpoint.rstrip("/") + "/_msearch"
    
    query = sanitize_query(body.query)
    dataset = sanitize_text(body.dataset)
    requested_datasets = parse_requested_datasets(dataset)
    typeclass = sanitize_text(body.typeclass)
    requested_limit = body.limit
    effective_limit = min(requested_limit, max_limit)

    if requested_limit > max_limit:
        logger.warning(
            "Requested limit %s exceeds configured maximum %s; clamping request.",
            requested_limit,
            max_limit,
        )

    try:
        clean_query = query.encode('latin-1').decode('utf-8')
    except (UnicodeEncodeError, UnicodeDecodeError):
        clean_query = query

    # Debug body to log
    if logger.isEnabledFor(logging.DEBUG):
        log_body = {
            "query": query,
            "typeclass": typeclass,
            "dataset": dataset,
            "limit": effective_limit,
        }
        logger.debug("Received search request: %s", json.dumps(log_body))
    
    # Pass config as the second argument
    payload = build_msearch_query(
        q=clean_query,
        config=app.state.config,
        total_limit=effective_limit,
        index=index,
        typeclass_filter=typeclass,
        requested_datasets=requested_datasets
    )
    
    #logger.debug("Constructed OpenSearch query (NDJSON payload)\n%s", payload)

    auth = None
    user = getattr(app.state, "opensearch_user", None)
    password = getattr(app.state, "opensearch_password", None)
    if user is not None and password is not None:
        auth = (user, password)

    headers = {"Content-Type": "application/x-ndjson"}
    api_key = getattr(app.state, "opensearch_api_key", None)
    if api_key:
        headers["Authorization"] = f"ApiKey {api_key}"

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(url, content=payload, headers=headers, auth=auth)
            if r.status_code >= 400:
                logger.error("OpenSearch error response: %d - %s", r.status_code, r.text)
                raise HTTPException(status_code=r.status_code, detail=r.text)
            
            raw_response = r.json()
            
            # Flattening for ResearchSpace Ephedra compatibility
            final_hits = []
            total_value = 0
            
            for resp in raw_response.get("responses", []):
                if "hits" in resp:
                    hits_list = resp["hits"].get("hits", [])
                    final_hits.extend(hits_list)
                    total_value += resp["hits"].get("total", {}).get("value", 0)
            
            # Reconstruct into a standard flat search result
            final_response = {
                "took": raw_response.get("took"),
                "hits": {
                    "total": {"value": total_value, "relation": "eq"},
                    "hits": final_hits
                }
            }
            normalized_response = normalize_entity_hits(
                final_response,
                min_shared_matches=getattr(app.state, "min_shared_matches", 1),
            )
            if logger.isEnabledFor(logging.DEBUG):
                all_hits = normalized_response.get("hits", {}).get("hits", [])
                log_hits_structure = {
                    "total": normalized_response.get("hits", {}).get("total"),
                    #"hits": all_hits[:0] + [f"... {len(all_hits) - 3} more hits omitted"] if len(all_hits) > 3 else all_hits
                    "hits": "...{}  hits omitted...".format(len(all_hits))
                }
                log_display = {
                "took": normalized_response.get("took"),
                "hits": log_hits_structure
                }
                logger.debug("Response to client (truncated): %s", json.dumps(log_display, indent=2)) 
            return normalized_response

    except httpx.RequestError as e:
        raise HTTPException(status_code=502, detail=f"OpenSearch request failed: {e}")
    
def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--opensearch-url", required=True, help="e.g. http://opensearch:9200")
    parser.add_argument("--index", required=True, help="OpenSearch index name")
    parser.add_argument("--user", default=os.getenv("OPENSEARCH_USER"))
    parser.add_argument("--password", default=os.getenv("OPENSEARCH_PASSWORD"))
    parser.add_argument("--api-key", default=os.getenv("OPENSEARCH_API_KEY"))
    parser.add_argument("--config", required=True, help="Path to YAML configuration")
    parser.add_argument("--datasets", help="Comma-separated list of dataset names to include in search (must be defined in config)")
    parser.add_argument("--max-limit", type=int, default=DEFAULT_MAX_LIMIT, help="Maximum total result limit accepted from client requests")
    parser.add_argument("--min-shared-matches", type=int, default=1, help="Minimum number of shared match URIs required to group entity hits")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    if args.max_limit < 1:
        parser.error("--max-limit must be greater than 0")
    if args.min_shared_matches < 1:
        parser.error("--min-shared-matches must be greater than 0")

    app.state.opensearch_url = args.opensearch_url
    app.state.opensearch_index = args.index
    app.state.opensearch_user = args.user
    app.state.opensearch_password = args.password
    app.state.opensearch_api_key = args.api_key
    app.state.datasets = [dataset.strip() for dataset in args.datasets.split(",") if dataset.strip()] if args.datasets else None
    app.state.max_limit = args.max_limit
    app.state.min_shared_matches = args.min_shared_matches

    # Load additional configuration from YAML file
    with open(args.config, "r") as f:
        config = yaml.safe_load(f)
    app.state.config = config

    import uvicorn
    logger.info(
        "Starting service with index=%s, url=%s, max_limit=%s, min_shared_matches=%s",
        args.index,
        args.opensearch_url,
        args.max_limit,
        args.min_shared_matches,
    )
    uvicorn.run(app, host=args.host, port=args.port)

if __name__ == "__main__":
    main()
