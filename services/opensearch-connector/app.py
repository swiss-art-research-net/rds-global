"""
# OpenSearch Search Proxy

A small FastAPI service that proxies search requests to an OpenSearch index.
The service exposes a `/search` endpoint which accepts a simple query string and translates it into an OpenSearch query.
It is designed to be used as a connector for ResearchSpace Ephedra services that are unable to construct complex OpenSearch queries on their own.

## Usage

Run the service:

    python app.py --opensearch-url http://localhost:9200 --index rds-entities

Optional authentication flags:

    python app.py --opensearch-url http://localhost:9200 --index rds-entities \
        --user admin --password admin

    python app.py --opensearch-url http://localhost:9200 --index rds-entities \
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
from typing import Any, Dict, Optional

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

app = FastAPI()

class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1)

def build_query(q: str) -> Dict[str, Any]:
    return {
        "query": {
            "function_score": {
                "query": {
                    "constant_score": {
                        "filter": {
                            "multi_match": {
                                "query": q,
                                "fields": ["prefLabels^3", "labels"],
                                "operator": "and"
                            }
                        }
                    }
                },
                "field_value_factor": {
                "field": "numMatches",
                "factor": 3,
                "modifier": "sqrt",
                "missing": 0
                },
                "boost_mode": "sum"
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
    if not endpoint or not index:
        raise HTTPException(status_code=500, detail="OpenSearch not configured")

    url = endpoint.rstrip("/") + f"/{index}/_search"
    payload = build_query(body.query)

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
            r = await client.post(url, json=payload, headers=headers, auth=auth)
            if r.status_code >= 400:
                raise HTTPException(status_code=r.status_code, detail=r.text)
            return r.json()
    except httpx.RequestError as e:
        raise HTTPException(status_code=502, detail=f"OpenSearch request failed: {e}") from e

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--opensearch-url", required=True, help="e.g. http://opensearch:9200")
    parser.add_argument("--index", required=True, help="OpenSearch index name")
    parser.add_argument("--user", default=os.getenv("OPENSEARCH_USER"))
    parser.add_argument("--password", default=os.getenv("OPENSEARCH_PASSWORD"))
    parser.add_argument("--api-key", default=os.getenv("OPENSEARCH_API_KEY"))
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    app.state.opensearch_url = args.opensearch_url
    app.state.opensearch_index = args.index
    app.state.opensearch_user = args.user
    app.state.opensearch_password = args.password
    app.state.opensearch_api_key = args.api_key

    import uvicorn
    uvicorn.run(app, host=args.host, port=args.port)

if __name__ == "__main__":
    main()