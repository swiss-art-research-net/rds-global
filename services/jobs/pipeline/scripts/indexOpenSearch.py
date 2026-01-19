import argparse
import gzip
import os
import re
import time
from typing import Dict, Any, Iterable, Optional, Tuple, List

from opensearchpy import OpenSearch, helpers
from tqdm import tqdm

DEFAULT_TEXT_PREDICATES = {
    "http://www.w3.org/2000/01/rdf-schema#label",
    "http://www.w3.org/2004/02/skos/core#prefLabel",
    "http://www.w3.org/2004/02/skos/core#altLabel",
    "http://schema.org/name",
    "http://purl.org/dc/terms/title",
    "http://www.w3.org/2008/05/skos-xl#literalForm"
}

RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
VOID_IN_DATASET = "http://rdfs.org/ns/void#inDataset"

INDEX_MAPPING = {
    "settings": {
        "analysis": {
            "normalizer": {
                "lowercase_norm": {"type": "custom", "filter": ["lowercase", "asciifolding"]}
            }
        }
    },
    "mappings": {
        "properties": {
            "id": {"type": "keyword", "normalizer": "lowercase_norm"},
            "best_label": {
                "type": "text",
                "fields": {
                    "keyword": {"type": "keyword", "normalizer": "lowercase_norm"}
                }  
            },
            "all_text": {"type": "text"},
            "langs": {"type": "keyword"},
            "sources": {"type": "keyword"},
            "types": {"type": "keyword"}
        }
    }
}

UPDATE_SCRIPT = """
// best label
if (ctx._source.best_label == null || ctx._source.best_label.length() == 0) {
  ctx._source.best_label = params.best_label;
}

// text concat
if (params.text != null && params.text.length() > 0) {
  if (ctx._source.all_text == null) { ctx._source.all_text = params.text; }
  else { ctx._source.all_text += ' ' + params.text; }
}

// langs
if (ctx._source.langs == null) { ctx._source.langs = []; }
if (params.lang != null && params.lang.length() > 0 && !ctx._source.langs.contains(params.lang)) {
  ctx._source.langs.add(params.lang);
}

// sources
if (ctx._source.sources == null) { ctx._source.sources = []; }
if (params.source != null && params.source.length() > 0 && !ctx._source.sources.contains(params.source)) {
  ctx._source.sources.add(params.source);
}
if (params.dataset != null && params.dataset.length() > 0 && !ctx._source.sources.contains(params.dataset)) {
  ctx._source.sources.add(params.dataset);
}

// types
if (ctx._source.types == null) { ctx._source.types = []; }
if (params.type_iri != null && params.type_iri.length() > 0 && !ctx._source.types.contains(params.type_iri)) {
  ctx._source.types.add(params.type_iri);
}
"""

NQ_RE = re.compile(
    r'^\s*<([^>]*)>\s+<([^>]*)>\s+'
    r'(?:'
    r'"((?:[^"\\]|\\.)*)"'          # literal content (with escapes)
    r'(?:@([a-zA-Z]+(?:-[a-zA-Z0-9]+)*))?'  # optional @lang
    r'(?:\^\^<([^>]*)>)?'           # optional datatype
    r'|'
    r'<([^>]*)>'                    # or object IRI
    r')\s+<([^>]*)>\s*\.\s*$'        # graph IRI
)

def unescape_literal(s: str) -> str:
    # Basic N-Triples/N-Quads string unescaping
    return bytes(s, "utf-8").decode("unicode_escape")

def open_maybe_gz(path: str):
    if path.endswith(".gz"):
        return gzip.open(path, "rt", encoding="utf-8", errors="replace")
    return open(path, "rt", encoding="utf-8", errors="replace")

def make_client(host: str, port: int, user: str, password: str, use_ssl: bool) -> OpenSearch:
    return OpenSearch(
        hosts=[{"host": host, "port": port}],
        http_auth=(user, password),
        use_ssl=use_ssl,
        verify_certs=False,
        ssl_show_warn=False,
        timeout=60,
        max_retries=5,
        retry_on_timeout=True,
    )

def ensure_index(client: OpenSearch, index: str, create: bool) -> None:
    if client.indices.exists(index=index):
        return
    if not create:
        raise SystemExit(f"Index '{index}' missing. Use --create-index.")
    client.indices.create(index=index, body=INDEX_MAPPING)

def make_update_action(
  index: str,
  subj: str,
  text: str = "",
  best_label: str = "",
  lang: str = "",
  source: str = "",
  dataset: str = "",
  type_iri: str = "",
) -> Dict[str, Any]:
  params = {
      "text": text,
      "best_label": best_label or text,
      "lang": lang,
      "source": source,
      "dataset": dataset,
      "type_iri": type_iri,
  }
  upsert = {
      "id": subj,
      "best_label": best_label or text,
      "all_text": text if text else "",
      "langs": [lang] if lang else [],
      "sources": [s for s in [source, dataset] if s],
      "types": [type_iri] if type_iri else [],
  }
  return {
      "_op_type": "update",
      "_index": index,
      "_id": subj,
      "script": {"source": UPDATE_SCRIPT, "lang": "painless", "params": params},
      "upsert": upsert,
  }

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--nq", required=True, help="Path to .nq or .nq.gz")
    ap.add_argument("--index", default="rdf_entities")
    ap.add_argument("--create-index", action="store_true")
    ap.add_argument("--bulk-size", type=int, default=2000)
    ap.add_argument("--host", default=os.getenv("OPENSEARCH_HOST", "localhost"))
    ap.add_argument("--port", type=int, default=int(os.getenv("OPENSEARCH_PORT", "9200")))
    ap.add_argument("--user", default=os.getenv("OPENSEARCH_USER", "admin"))
    ap.add_argument("--password", default=os.getenv("OPENSEARCH_PASSWORD", ""))
    ap.add_argument("--use-ssl", action="store_true", default=False)
    ap.add_argument("--no-ssl", action="store_false", dest="use_ssl")
    ap.add_argument("--pred", action="append", default=[], help="Extra predicate IRI to index (repeatable)")
    args = ap.parse_args()

    text_preds = set(DEFAULT_TEXT_PREDICATES)
    text_preds.update(args.pred)

    client = make_client(args.host, args.port, args.user, args.password, args.use_ssl)
    ensure_index(client, args.index, args.create_index)

    actions: List[Dict[str, Any]] = []
    t0 = time.time()

    with open_maybe_gz(args.nq) as f:
        for line in tqdm(f, unit=" triples", smoothing=10):

            m = NQ_RE.match(line)
            if not m:
                continue

            subj, pred, lit_raw, lang, dtype, obj_iri, graph = m.groups()
            source = graph  # named graph IRI as source facet

            # dataset facet (optional, via void:inDataset)
            dataset = ""
            if pred == VOID_IN_DATASET and obj_iri:
                dataset = obj_iri

            # rdf:type facet
            if pred == RDF_TYPE and obj_iri:
                actions.append(make_update_action(args.index, subj, source=source, type_iri=obj_iri))
            # text predicates
            elif pred in text_preds and lit_raw is not None:
                text = unescape_literal(lit_raw)
                actions.append(make_update_action(args.index, subj, text=text, best_label=text, lang=lang or "", source=source, dataset=dataset))

            if len(actions) >= args.bulk_size:
                helpers.bulk(client, actions, raise_on_error=False, request_timeout=120)
                actions.clear()

    if actions:
        helpers.bulk(client, actions, raise_on_error=False, request_timeout=120)

    client.indices.refresh(index=args.index)
    dt = time.time() - t0
    print(f"Done. elapsed={dt:.1f}s")

if __name__ == "__main__":
    main()