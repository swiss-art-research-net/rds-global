"""
# OpenSearch Search Proxy

A small FastAPI service that proxies search requests to an OpenSearch index.
The service exposes a `/search` endpoint which accepts a simple query string and translates it into an OpenSearch query.
It is designed to be used as a connector for ResearchSpace Ephedra services that are unable to construct complex OpenSearch queries on their own.

## Usage

Run the service:

    python app.py --opensearch-url http://localhost:9200 --index rds-entities --config config.yaml

Optional authentication flags:

    python app.py --opensearch-url http://localhost:9200 --index rds-entities --config config.yaml \
        --user admin --password admin

    python app.py --opensearch-url http://localhost:9200 --index rds-entities --config config.yaml \
        --api-key "<your_api_key>"

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
from typing import Any, Dict, Optional

import httpx
import yaml
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

app = FastAPI()

DEBUG= True

class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1)

def build_msearch_query(q: str, config: Dict[str, Any], limit_per_dataset: int = 10, index: str = "rds-entities") -> str:
    """
    Constructs an ndjson string for the OpenSearch _msearch endpoint.
    """
    msearch_payload = ""
    dataset_names = config.get('datasets', {}).keys()
    
    for ds_name in dataset_names:
        header = {"index": index}
        
        body = {
            "size": limit_per_dataset,
            "query": {
                "function_score": {
                    "query": {
                        "bool": {
                            "must": [
                                {"term": {"dataset": ds_name}}, 
                                {
                                    "multi_match": {
                                        "query": q,
                                        "fields": ["prefLabels^3", "labels"],
                                        "operator": "and",
                                        "fuzziness": "AUTO"
                                    }
                                }
                            ],
                            "should": [
                                {"match_phrase": {"prefLabels": {"query": q, "boost": 10}}}
                            ]
                        }
                    },
                    "field_value_factor": {
                        "field": "numMatches",
                        "factor": 30,
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


def build_query(q: str) -> Dict[str, Any]:
    return {
        "size": 100,
        "query": {
            "function_score": {
                "query": {
                    "bool": {
                        "must": [
                            {
                                "multi_match": {
                                    "query": q,
                                    "fields": ["prefLabels^3", "labels"],
                                    "operator": "and",
                                    "fuzziness": "AUTO"
                                }
                            }
                        ],
                        "should": [
                            {
                                "match_phrase": {
                                    "prefLabels": {
                                        "query": q,
                                        "boost": 10
                                    }
                                }
                            }
                        ]
                    }
                },
                "functions": [
                    {
                        "field_value_factor": {
                            "field": "numMatches",
                            "factor": 30,
                            "modifier": "sqrt",
                            "missing": 0
                        }
                    }
                ],
                "boost_mode": "sum"
            }
        },
        "collapse": {
            "field": "dataset", 
            "inner_hits": {
                "name": "top_results_per_dataset",
                "size": 10,
                "sort": [{"_score": "desc"}]
            }
        }
    }
@app.get("/healthz")
def healthz() -> Dict[str, str]:
    return {"status": "ok"}

@app.post("/search")
async def search(body: SearchRequest) -> Any:
    endpoint: Optional[str] = getattr(app.state, "opensearch_url", None)
    index: Optional[str] = getattr(app.state, "opensearch_index", None)

    if not endpoint:
        raise HTTPException(status_code=500, detail="OpenSearch not configured")

    # Point to the global _msearch endpoint
    url = endpoint.rstrip("/") + "/_msearch"
    
    try:
        clean_query = body.query.encode('latin-1').decode('utf-8')
    except (UnicodeEncodeError, UnicodeDecodeError):
        clean_query = body.query
    
    # Pass config as the second argument
    payload = build_msearch_query(clean_query, app.state.config, limit_per_dataset=10, index=index)
    
    if DEBUG:
        print("Constructed OpenSearch query (NDJSON payload)")
        print(payload)

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
                if DEBUG: print(f"OpenSearch error response: {r.status_code} - {r.text}")
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
            return {
                "took": raw_response.get("took"),
                "hits": {
                    "total": {"value": total_value, "relation": "eq"},
                    "hits": final_hits
                }
            }

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
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    app.state.opensearch_url = args.opensearch_url
    app.state.opensearch_index = args.index
    app.state.opensearch_user = args.user
    app.state.opensearch_password = args.password
    app.state.opensearch_api_key = args.api_key

    # Load additional configuration from YAML file
    with open(args.config, "r") as f:
        config = yaml.safe_load(f)
    app.state.config = config

    import uvicorn
    uvicorn.run(app, host=args.host, port=args.port)

if __name__ == "__main__":
    main()