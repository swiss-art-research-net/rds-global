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
import asyncio
import os
import json
from typing import Any, Dict, Optional, List

import httpx
import logging
import yaml
from fastapi import FastAPI, HTTPException, Request, status, Query
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, Field
from fastapi import Body
from fastapi.middleware.cors import CORSMiddleware
import html

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

# --- CORS for all endpoints (OpenRefine/browser compatibility) 
app.add_middleware(
    CORSMiddleware, 
    allow_origins=["*"], 
    allow_credentials=True, 
    allow_methods=["*"], 
    allow_headers=["*"],
    )


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=512)
    typeclass: Optional[str] = Field(default=None, max_length=128)
    dataset: Optional[str] = Field(default=None, max_length=128)
    limit: int = Field(default=DEFAULT_TOTAL_LIMIT, ge=1)


EXTEND_PROPERTIES = {
    "matches": "Matches",
    "dataset": "Dataset",
    "description": "Description",
    "type": "Type",
    "sourceType": "Source Type",
}


def sanitize_text(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None

    sanitized = value.strip()
    return sanitized or None


def split_comma_separated_values(value: Optional[str]) -> Optional[List[str]]:
    sanitized = sanitize_text(value)
    if sanitized is None:
        return None

    values: List[str] = []
    for candidate in sanitized.split(","):
        normalized = candidate.strip()
        if normalized and normalized not in values:
            values.append(normalized)

    return values or None

def sanitize_query(value: str) -> str:
    sanitized = value.strip()
    if not sanitized:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Query must not be blank.",
        )
    return sanitized


def _to_extend_values(property_id: str, source: Dict[str, Any]) -> List[Any]:
    """Map one extend property to normalized response values from a source document."""
    values: List[Any] = []

    if property_id == "matches":
        values = source.get("matches") if isinstance(source.get("matches"), list) else []
    elif property_id == "dataset":
        value = source.get("dataset")
        values = [value] if value else []
    elif property_id == "description":
        description = source.get("description")
        if not description:
            descriptions = source.get("descriptions")
            if isinstance(descriptions, list) and descriptions:
                description = descriptions[0]
            elif isinstance(descriptions, str):
                description = descriptions
        values = [description] if description else []
    elif property_id == "type":
        type_classes = source.get("typeClasses") if isinstance(source.get("typeClasses"), list) else []
        values = [
            value.get("id") or value.get("name") if isinstance(value, dict) else value
            for value in type_classes
        ]
    elif property_id == "sourceType":
        values = source.get("types") if isinstance(source.get("types"), list) else []

    out: List[Dict[str, str]] = []
    for value in values:
        if value is None:
            continue
        normalized = str(value).strip()
        if normalized:
            out.append({"str": normalized})
    return out # e.g.


async def _fetch_sources_by_ids(ids: List[str]) -> Dict[str, Dict[str, Any]]:
    """Fetch source documents by entity ids via OpenSearch _mget using configured auth settings."""
    endpoint = getattr(app.state, "opensearch_url", None)
    index = getattr(app.state, "opensearch_index", None)
    if not endpoint or not index:
        raise HTTPException(status_code=500, detail="OpenSearch not configured")

    # Use OpenSearch _mget to retrieve many ids in a single round-trip.
    url = endpoint.rstrip("/") + f"/{index}/_mget"

    auth = None
    user = getattr(app.state, "opensearch_user", None)
    password = getattr(app.state, "opensearch_password", None)
    if user is not None and password is not None:
        auth = (user, password)

    headers = {"Content-Type": "application/json"}
    api_key = getattr(app.state, "opensearch_api_key", None)
    if api_key:
        headers["Authorization"] = f"ApiKey {api_key}"

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            # OpenSearch _mget payload {"ids": ["..."]}
            r = await client.post(url, json={"ids": ids}, headers=headers, auth=auth)
            r.raise_for_status()
            payload = r.json()
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=e.response.text)
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"OpenSearch request failed: {e}")

    # Normalize OpenSearch docs array into id -> _source mapping.
    sources: Dict[str, Dict[str, Any]] = {}
    for doc in payload.get("docs", []):
        if not doc.get("found"):
            continue
        doc_id = doc.get("_id")
        source = doc.get("_source") or {}
        if doc_id and isinstance(source, dict):
            sources[str(doc_id)] = source

    return sources # example: {"id1": {"field": "value"}, "id2": {"field": "value"}}


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
    typeclass_filters: Optional[List[str]] = None,
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
        if typeclass_filters:
            must_conditions.append({"terms": {"typeClasses": typeclass_filters}})
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


# --- Dynamic manifest generator
async def get_manifest(request: Request):

    types = await get_type_classes()

    if not types:
        types = [{"id": "Entity", "name": "All Entities"}]  
    types.sort(key=lambda t: t["name"])

    configured_base_url = getattr(app.state, "reconciliation_base_url", None)
    base_url = configured_base_url.strip().rstrip("/") if configured_base_url else str(request.base_url).rstrip("/")
    platform_host_name = getattr(app.state, "platform_host_name", None)
    if platform_host_name:
        view_url = f"{platform_host_name.strip().rstrip('/')}/resource/?uri={{{{id}}}}"
    else:
        view_url = "https://rds-cloud.swissartresearch.net/resource/?uri={{id}}"
    
    return {
        "versions": ["0.2"],
        "name": "RDS Reconciliation Service",
        "identifierSpace": "https://rds.swissartresearch.net/resource/",
        "schemaSpace": "http://schema.swissartresearch.net/ontology/rds#",

        "defaultTypes": types,
        "view": {
            "url": view_url
        },
        "preview": {
            "url": f"{base_url}/preview?id={{{{id}}}}",
            "width": 400,
            "height": 250
        },

        "suggest": {
            "entity": {
                "service_url": base_url,
                "service_path": "/suggest/entity"
            },
            "type": {
                "service_url": base_url,
                "service_path": "/suggest/type"
            },
            "property": {
                "service_url": base_url,
                "service_path": "/suggest/property"
            }
        },
        "extend": {
            "property_settings": [
                {
                    "name": "limit",
                    "label": "Limit",
                    "type": "number",
                    "default": 0,
                    "help_text": "Maximum number of values returned per property (0 for no limit)"
                },
                {
                    "name": "content",
                    "label": "Content",
                    "type": "select",
                    "default": "literal",
                    "help_text": "Return values as literal strings or as id objects",
                    "choices": [
                        {
                            "value": "literal",
                            "name": "Literal"
                        },
                        {
                            "value": "id",
                            "name": "ID"
                        }
                    ]
                }
            ]
        },

    }


async def get_type_classes():
    return getattr(app.state, "type_classes", [])

async def load_type_classes():

    endpoint = app.state.opensearch_url
    index = app.state.opensearch_index

    url = f"{endpoint.rstrip('/')}/{index}/_search"

    body = {
        "size": 0,
        "aggs": {
            "types": {
                "terms": {
                    "field": "typeClasses",
                    "size": 1000
                }
            }
        }
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post(url, json=body)
        r.raise_for_status()
        data = r.json()

    buckets = data.get("aggregations", {}).get("types", {}).get("buckets", [])
    
    return sorted(
        [
            {
                "id": bucket["key"],
                "name": bucket["key"]
            }
            for bucket in buckets
        ],
        key=lambda t: t["name"]
    )


@app.api_route("/", methods=["GET", "POST"])
async def root(request: Request):

    # GET without queries: MANIFEST
    if (
        request.method == "GET"
        and "queries" not in request.query_params
        and "extend" not in request.query_params
    ):
        return JSONResponse(content=await get_manifest(request))

    # GET with queries: RECONCILIATION
    if request.method == "GET":
        queries_raw = request.query_params.get("queries")
        extend_raw = request.query_params.get("extend")

    # POST: RECONCILIATION (x-www-form-urlencoded)
    elif request.method == "POST":
        form = await request.form()
        queries_raw = form.get("queries")
        extend_raw = form.get("extend")

    else:
        return {}

    # 0.2 data extension requests are sent as ?extend={...} on the root endpoint
    if extend_raw:
        return await _handle_extend_query(extend_raw)

    if not queries_raw:
        return {}

    try:
        queries = json.loads(queries_raw)
    except Exception:
        return {}

    if not isinstance(queries, dict):
        return {}

    results = {}

    for qid, q in queries.items():
        print( f"Processing query id={qid} with content: {q}")
        results[qid] = await _reconcile_single(q)

    return results


async def _handle_extend_query(extend_raw: str):
    # Reconciliation API 0.2 uses root-level `extend` requests
    extend_payload: Dict[str, Any] = {}
    try:
        parsed = json.loads(extend_raw)
        if isinstance(parsed, dict):
            extend_payload = parsed
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"Invalid extend payload JSON: {e.msg}")

    if not extend_payload:
        raise HTTPException(status_code=400, detail="Extend payload must be a JSON object")

    payload_ids = extend_payload.get("ids")
    payload_properties = extend_payload.get("properties")

    if not isinstance(payload_ids, list):
        raise HTTPException(status_code=400, detail="Extend payload must include 'ids' as an array")
    if not isinstance(payload_properties, list):
        raise HTTPException(status_code=400, detail="Extend payload must include 'properties' as an array")

    ids: List[str] = []
    for raw_id in payload_ids:
        normalized_id = str(raw_id).strip() if raw_id is not None else ""
        if not normalized_id:
            continue
        if normalized_id not in ids:
            ids.append(normalized_id)

    # Preserve property order while filtering and validating against supported property ids
    property_ids: List[str] = []
    property_settings_by_id: Dict[str, Dict[str, Any]] = {}
    unknown_property_ids: List[str] = []
    for item in payload_properties:
        if not isinstance(item, dict):
            raise HTTPException(status_code=400, detail="Each property must be an object with an 'id' field")

        raw_prop_id = item.get("id")
        settings = item.get("settings")

        if raw_prop_id is None:
            raise HTTPException(status_code=400, detail="Each property object must include an 'id' field")

        prop_id = str(raw_prop_id).strip()
        if not prop_id:
            raise HTTPException(status_code=400, detail="Property id must be a non-empty string")

        if prop_id not in EXTEND_PROPERTIES:
            if prop_id not in unknown_property_ids:
                unknown_property_ids.append(prop_id)
            continue

        if prop_id not in property_ids:
            property_ids.append(prop_id)

        if settings is not None and not isinstance(settings, dict):
            raise HTTPException(status_code=400, detail=f"Settings for property '{prop_id}' must be an object")
        if isinstance(settings, dict):
            property_settings_by_id[prop_id] = settings

    if unknown_property_ids:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported extend property id(s): {', '.join(unknown_property_ids)}",
        )

    if not ids:
        return {
            "meta": [{"id": p, "name": EXTEND_PROPERTIES.get(p, p)} for p in property_ids],
            "rows": {},
        }

    sources = await _fetch_sources_by_ids(ids)

    rows: Dict[str, Dict[str, List[Any]]] = {}
    for entity_id in ids:
        source = sources.get(entity_id, {})
        row: Dict[str, List[Any]] = {}
        for prop in property_ids:
            values = _to_extend_values(prop, source)
            settings = property_settings_by_id.get(prop) or {}

            limit_raw = settings.get("limit")
            try:
                limit = int(limit_raw) if limit_raw is not None else 0
            except (TypeError, ValueError):
                limit = 0
            if limit > 0:
                values = values[:limit]

            content = str(settings.get("content", "literal")).strip().lower()
            if content == "id":
                id_values: List[Dict[str, str]] = []
                for value in values:
                    raw = value.get("str") if isinstance(value, dict) else None
                    if raw:
                        id_values.append({"id": raw, "name": raw})
                values = id_values

            row[prop] = values

        rows[entity_id] = row

    return {
        "meta": [{"id": p, "name": EXTEND_PROPERTIES.get(p, p)} for p in property_ids],
        "rows": rows,
    }


async def _reconcile_single(q: Dict[str, Any]):

    query_string = (q.get("query") or "").strip()
    try:
        requested_limit = int(q.get("limit", 10))
    except (TypeError, ValueError):
        requested_limit = 10
    requested_limit = max(1, requested_limit)

    max_limit = getattr(app.state, "max_limit", DEFAULT_MAX_LIMIT)
    effective_limit = min(requested_limit, max_limit)
    if requested_limit > max_limit:
        logger.warning(
            "Reconciliation requested limit %s exceeds configured maximum %s; clamping request.",
            requested_limit,
            max_limit,
        )

    try:
        clean_query = query_string.encode('latin-1').decode('utf-8')
    except (UnicodeEncodeError, UnicodeDecodeError):
        clean_query = query_string

    entity_type = q.get("type")
    requested_typeclasses: List[str] = []
    if isinstance(entity_type, list):
        for t in entity_type:
            if isinstance(t, dict):
                type_value = t.get("id") or t.get("name")
            else:
                type_value = t
            parsed_types = split_comma_separated_values(str(type_value)) if type_value else None
            if parsed_types:
                for parsed_type in parsed_types:
                    if parsed_type not in requested_typeclasses:
                        requested_typeclasses.append(parsed_type)
    elif entity_type:
        parsed_types = split_comma_separated_values(str(entity_type)) or [str(entity_type)]
        for parsed_type in parsed_types:
            if parsed_type not in requested_typeclasses:
                requested_typeclasses.append(parsed_type)

    properties = q.get("properties", [])
    datasets = None

    if isinstance(properties, list):
        for p in properties:
            if p.get("pid") == "dataset":
                val = p.get("v")
                if val:
                    datasets = [val]
            elif p.get("pid") == "type":
                val = p.get("v")
                if isinstance(val, dict):
                    type_value = val.get("id") or val.get("name")
                else:
                    type_value = val
                parsed_types = split_comma_separated_values(str(type_value)) if type_value else None
                if parsed_types:
                    for parsed_type in parsed_types:
                        if parsed_type not in requested_typeclasses:
                            requested_typeclasses.append(parsed_type)

    if not query_string:
        return {"result": []}

    # using max limit to ensure we have enough hits to normalize and filter
    search_limit = min(
        max_limit,
        max(effective_limit, DEFAULT_TOTAL_LIMIT, effective_limit * 20),
    )

    try:
        hits = await run_search(
            query=clean_query,
            datasets=datasets,
            limit=search_limit,
            typeclass_filters=requested_typeclasses or None,
        )
    except Exception as e:
        logger.exception("SEARCH ERROR for query=%s: %s", query_string, e)
        return {"result": []}

    if not hits:
        return {"result": []}

    # Apply the same hit normalization used by /search
    normalized_response = normalize_entity_hits(
        {
            "hits": {
                "total": {"value": len(hits), "relation": "eq"},
                "hits": hits,
            }
        },
        min_shared_matches=getattr(app.state, "min_shared_matches", 1),
    )
    hits = normalized_response.get("hits", {}).get("hits", [])

    # only consider matches with score >= 90% of the top hit's score.
    # For very small absolute scores avoid treating them as matches.
    top_score = max(float(h.get("_score", 0.0) or 0.0) for h in hits)
    threshold = max(top_score * 0.9, 10.0)

    results = []

    for h in hits:
        source = h["_source"]
        subject = h.get("_id")
        reference = h.get("_reference") or subject

        label = (
            (source.get("prefLabels") or [None])[0]
            or (source.get("labels") or [None])[0]
        )

        if not label:
            continue

        score = float(h.get("_score", 0.0))

        type_classes = source.get("typeClasses") or []
        types = []
        normalized_type_classes: List[str] = []

        for t in type_classes:
            if isinstance(t, dict):
                type_id = t.get("id") or t.get("name")
                type_name = t.get("name") or t.get("id")
                type_id_text = str(type_id).strip() if type_id is not None else ""
                type_name_text = str(type_name).strip() if type_name is not None else ""
                if not type_id_text:
                    continue
                if not type_name_text:
                    type_name_text = type_id_text
                normalized_type_classes.append(type_id_text)
                types.append({
                    "id": type_id_text,
                    "name": type_name_text
                })
            else:
                type_text = str(t).strip() if t is not None else ""
                if not type_text:
                    continue
                normalized_type_classes.append(type_text)
                types.append({
                    "id": type_text,
                    "name": type_text
                })

        dataset = source.get("dataset")
        has_matches = "matches" in source
        has_types = "types" in source
        
        description = source.get("description")

        if description is None:
            descs = source.get("descriptions")
            if isinstance(descs, list) and descs:
                description = descs[0]
            elif isinstance(descs, str):
                description = descs


        # Following SPARQL behavior
        if not (
            subject
            and label
            and dataset is not None
            and normalized_type_classes
            and has_matches
            and has_types
            and reference
        ):
            continue

        record_id = str(subject).rsplit("/", 1)[-1].rsplit("#", 1)[-1]
        is_reference = 1 if subject == reference else 0
        score_display = round(score * 10) / 10

        result = {
            "id": subject,
            "name": label,
            "type": types,
            "score": score,
            "scoreDisplay": score_display,
            "match": (
                score >= threshold
                and score > 0
            ),
            "dataset": dataset,
            "reference": reference,
            "recordId": record_id,
            "isReference": is_reference,
        }

        # Description is optional in 0.2; include only when it is a string
        if isinstance(description, str):
            result["description"] = description

        results.append(result)

    # ordering like SPARQL: score DESC, isReference DESC, reference ASC.
    def sort_key(item: Dict[str, Any]):
        return (
            -float(item.get("score", 0.0)),
            -int(item.get("isReference", 0)),
            str(item.get("reference") or ""),
        )

    results.sort(key=sort_key)

    return {"result": results[:effective_limit]}


@app.get("/preview")
async def preview(id: str):

    index = getattr(app.state, "opensearch_index", None)
    endpoint = getattr(app.state, "opensearch_url", None)

    if not index or not endpoint:
        return HTMLResponse("<p>Server not configured</p>")

    source = None

    async with httpx.AsyncClient(timeout=10.0) as client:

        # direct lookup by _id
        url_get = endpoint.rstrip("/") + f"/{index}/_doc/{id}"

        try:
            r = await client.get(url_get)
            if r.status_code == 200:
                doc = r.json()
                source = doc.get("_source")
        except Exception:
            pass

        # fallback to search by uri field
        if not source:
            url_search = endpoint.rstrip("/") + f"/{index}/_search"

            body = {
                "size": 1,
                "query": {
                    "term": {
                        "uri": id
                    }
                }
            }

            try:
                r = await client.post(url_search, json=body)
                r.raise_for_status()
                hits = r.json().get("hits", {}).get("hits", [])
                if hits:
                    source = hits[0].get("_source")
            except Exception:
                pass

    if not source:
        return HTMLResponse(f"<p>No data for {html.escape(id)}</p>")

    # extract fields
    label = (
        (source.get("prefLabels") or [None])[0]
        or (source.get("labels") or [None])[0]
        or "Unknown"
    )

    description = (
        source.get("description")
        or (source.get("descriptions") or [None])[0]
        or ""
    )

    types = ", ".join([
        t.get("name") if isinstance(t, dict) else str(t)
        for t in (source.get("typeClasses") or [])
    ])

    # escape for safe HTML rendering
    label = html.escape(label)
    description = html.escape(description)
    types = html.escape(types)
    id_safe = html.escape(id)
    
    html_content = f"""
    <html>
      <head>
        <meta charset="utf-8"/>
        <style>
          body {{
            font-family: sans-serif;
            font-size: 14px;
            margin: 10px;
          }}
          h3 {{
            margin: 0 0 5px 0;
          }}
          .meta {{
            color: #555;
            font-size: 12px;
          }}
        </style>
      </head>
      <body>
        <h3>{label}</h3>
        <div class="meta">{types}</div>
        <p>{description}</p>
        <div class="meta">{id_safe}</div>
      </body>
    </html>
    """

    return HTMLResponse(content=html_content)

@app.get("/suggest/entity")
async def suggest_entity(prefix: str = "", limit: int = 5):

    if not prefix:
        return {"result": []}

    hits = await run_search(query=prefix, datasets=None, limit=20)

    results = []
    prefix_lower = prefix.lower()

    for hit in hits:
        source = hit.get("_source", {})
        label = (
            (source.get("prefLabels") or [None])[0]
            or (source.get("labels") or [None])[0]
        )

        if not label:
            continue

        label_lower = label.lower()
        entity_id = hit.get("_id", "")

        # match label OR id
        if not (
            label_lower.startswith(prefix_lower)
            or prefix_lower in label_lower
            or prefix_lower in entity_id.lower()
        ):
            continue

        # description
        description = (
            source.get("description")
            or (source.get("descriptions") or [None])[0]
            or ""
        )

        # notable types
        type_classes = source.get("typeClasses") or []
        notable = [
            {"id": t, "name": t} if not isinstance(t, dict) else {
                "id": t.get("id") or t.get("name"),
                "name": t.get("name") or t.get("id")
            }
            for t in type_classes[:2]  # keep small number of types for suggestions
        ]

        results.append({
            "id": entity_id,
            "name": label,
            "description": description,
            "notable": notable
        })

        if len(results) >= limit:
            break

    return {"result": results}


@app.get("/suggest/type")
async def suggest_type(prefix: str = Query("")): # no limit as they are a few, return all matching types

    types = await get_type_classes()
    types.sort(key=lambda t: t["name"])
    
    prefix_lower = prefix.lower()

    results = [
        t for t in types
        if prefix_lower in t["name"].lower()
    ]

    return {"result": results}




@app.get("/suggest/property")
async def suggest_property(prefix: str = Query("")):

    properties = [
        {
            "id": "matches",
            "name": "Matches",
            "description": "External identifiers for enrichment"
        },
        {
            "id": "dataset",
            "name": "Dataset",
            "description": "Dataset/source"
        },
        {
            "id": "description",
            "name": "Description",
            "description": "Textual description"
        },
        {
            "id": "type",
            "name": "Type",
            "description": "Normalized type"
        },
        {
            "id": "sourceType",
            "name": "Source Type",
            "description": "Source-specific RDF types"
        }
    ]

    prefix_lower = prefix.lower()

    results = [
        p for p in properties
        if prefix_lower in p["name"].lower()
    ]

    return {"result": results}

@app.get("/healthz")
def healthz() -> Dict[str, str]:
    return {"status": "ok"}


async def run_search(
    query: str,
    datasets: Optional[List[str]],
    limit: int,
    typeclass_filters: Optional[List[str]] = None
):
    endpoint = app.state.opensearch_url
    index = app.state.opensearch_index

    url = endpoint.rstrip("/") + "/_msearch"

    payload = build_msearch_query(
        q=query,
        config=app.state.config,
        total_limit=limit,
        index=index,
        typeclass_filters=typeclass_filters,
        requested_datasets=datasets
    )

    headers = {"Content-Type": "application/x-ndjson"}

    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post(url, content=payload, headers=headers)
        r.raise_for_status()
        raw = r.json()

    hits = []
    for resp in raw.get("responses", []):
        hits.extend(resp.get("hits", {}).get("hits", []))

    return [
        {
            "_id": h.get("_id"),
            "_score": h.get("_score", 0.0),
            "_source": h.get("_source", {})
        }
        for h in hits
    ]


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
    requested_datasets = split_comma_separated_values(dataset)
    typeclass = sanitize_text(body.typeclass)
    requested_typeclasses = split_comma_separated_values(typeclass)
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
        typeclass_filters=requested_typeclasses,
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
    parser.add_argument("--min-shared-matches", type=int, default=1, help="Minimum number of shared match URIs required to group entity hits; use 0 to disable shared-match grouping")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reconciliation-base-url", default=None, help="Base URL for reconciliation service. If not provided, it will be inferred from the request.")
    parser.add_argument("--platform-host-name", default=os.getenv("PLATFORM_HOST_NAME"), help="Host name for platform links used in reconciliation manifest view URL")
    args = parser.parse_args()

    if args.max_limit < 1:
        parser.error("--max-limit must be greater than 0")
    if args.min_shared_matches < 0:
        parser.error("--min-shared-matches must be greater than or equal to 0")

    app.state.opensearch_url = args.opensearch_url
    app.state.opensearch_index = args.index
    app.state.opensearch_user = args.user
    app.state.opensearch_password = args.password
    app.state.opensearch_api_key = args.api_key
    app.state.datasets = [dataset.strip() for dataset in args.datasets.split(",") if dataset.strip()] if args.datasets else None
    app.state.max_limit = args.max_limit
    app.state.min_shared_matches = args.min_shared_matches
    app.state.type_classes = asyncio.run(load_type_classes())  # Load type classes at startup
    app.state.reconciliation_base_url = args.reconciliation_base_url
    app.state.platform_host_name = args.platform_host_name

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
