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

LIMIT_PER_DATASET = 10
class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1)
    typeclass: Optional[str] = None
    dataset: Optional[str] = None

def build_msearch_query(
    q: str, 
    config: Dict[str, Any], 
    limit_per_dataset: int = LIMIT_PER_DATASET, 
    index: str = "rds-entities",
    typeclass_filter: Optional[str] = None,
    requested_dataset: Optional[str] = None
) -> str:
    """
    Constructs an ndjson string for the OpenSearch _msearch endpoint.
    """
    msearch_payload = ""
    config_datasets = config.get('datasets', {})
    if not config_datasets:
        raise HTTPException(
            status_code=500,
            detail="OpenSearch connector misconfiguration: at least one dataset must be defined in 'datasets'.",
        )
    dataset_names = list(config_datasets.keys())

    if getattr(app.state, "datasets", None):
        dataset_names = [ds for ds in dataset_names if ds in app.state.datasets]

    if requested_dataset:
        dataset_names = [requested_dataset] if requested_dataset in dataset_names else []

    if not dataset_names:
        raise HTTPException(
            status_code=400,
            detail="No valid datasets found for the given criteria.",
        )
    
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

def normalize_entity_hits(response: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize OpenSearch entity hits by grouping records that mutually
    reference each other via `_id` <-> `_source.matches`.

    For each connected group of equivalent records:
    - all members get the same `_score` = max score in the group
    - all members get `_reference` = deterministic representative `_id`

    Representative selection:
    1. highest original `_score`
    2. alphabetically smallest `_id`

    Rules for equivalence:
    - If A._id appears in B._source.matches and B._id appears in A._source.matches,
      then A and B are considered equivalent.
    - Equivalence is transitively closed, so if A<->B and B<->C, all three are grouped.
    """
    result = response

    hits = result.get("hits", {}).get("hits", [])
    if not isinstance(hits, list) or not hits:
        return result

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

    # Build undirected graph of mutual references
    adjacency: Dict[str, set] = {hit_id: set() for hit_id in id_to_index}

    ids = set(id_to_index.keys())
    for a in ids:
        for b in id_to_matches[a]:
            if b in ids and a != b:
                if a in id_to_matches.get(b, set()):
                    adjacency[a].add(b)
                    adjacency[b].add(a)

    # Find connected components
    visited = set()
    components: List[List[str]] = []

    for hit_id in sorted(ids):
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

    if not endpoint:
        raise HTTPException(status_code=500, detail="OpenSearch not configured")
    if not index:
        raise HTTPException(status_code=500, detail="OpenSearch index not configured")

    # Point to the global _msearch endpoint
    url = endpoint.rstrip("/") + "/_msearch"
    
    try:
        clean_query = body.query.encode('latin-1').decode('utf-8')
    except (UnicodeEncodeError, UnicodeDecodeError):
        clean_query = body.query

    # Debug body to log
    if logger.isEnabledFor(logging.DEBUG):
        logger.debug("Received search request: %s", body.json())
    
    # Pass config as the second argument
    payload = build_msearch_query(
        q=clean_query,
        config=app.state.config,
        limit_per_dataset=LIMIT_PER_DATASET,
        index=index,
        typeclass_filter=body.typeclass,
        requested_dataset=body.dataset
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
            normalized_response = normalize_entity_hits(final_response)
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
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    app.state.opensearch_url = args.opensearch_url
    app.state.opensearch_index = args.index
    app.state.opensearch_user = args.user
    app.state.opensearch_password = args.password
    app.state.opensearch_api_key = args.api_key
    app.state.datasets = args.datasets.split(",") if args.datasets else None

    # Load additional configuration from YAML file
    with open(args.config, "r") as f:
        config = yaml.safe_load(f)
    app.state.config = config

    import uvicorn
    logger.info("Starting service with index=%s, url=%s", args.index, args.opensearch_url)
    uvicorn.run(app, host=args.host, port=args.port)

if __name__ == "__main__":
    main()