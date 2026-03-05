import argparse
import random
import time

from SPARQLWrapper import SPARQLWrapper, POST, JSON
from lib.utils import load_config, generate_prefixes_for_SPARQL as generate_prefixes
from tqdm import tqdm

PAGE_SIZE = 1000
PREDICATE = "<http://www.w3.org/2002/07/owl#sameAs>"

WIKIDATA_MATCHES_QUERY_TEMPLATE = """
    PREFIX wd: <http://www.wikidata.org/entity/>
    PREFIX wdt: <http://www.wikidata.org/prop/direct/>
    PREFIX wikibase: <http://wikiba.se/ontology#>
    SELECT DISTINCT ?wdEntity ?otherEntity WHERE {
        VALUES ?wdEntity { $VALUES }
        ?propEntity wikibase:propertyType wikibase:ExternalId ;
                    wikibase:directClaim ?directPredicate .
        ?wdEntity ?directPredicate ?idValue .
        ?propEntity wdt:P1630 ?formatter .
        BIND (REPLACE(?formatter, "\\\\$1", ?idValue) AS ?otherEntity)
    }
"""

def _sleep_backoff(attempt, *, base = 0.6, cap = 30.0):
    # exponential backoff with jitter
    delay = min(cap, base * (2 ** attempt))
    delay = delay * (0.7 + random.random() * 0.6)  # 0.7x .. 1.3x
    time.sleep(delay)

def query_with_retry(
    sparql: SPARQLWrapper,
    query,
    *,
    max_retries = 6,
    label = "SPARQL",
):
    sparql.setQuery(query)
    last_exc = None
    for attempt in range(max_retries + 1):
        try:
            return sparql.query().convert()
        except Exception as e:
            last_exc = e
            if attempt >= max_retries:
                print(f"[{label}] failed after {max_retries} retries: {e}")
                print(f"Query:\n{query}")
                raise
            print(f"[{label}] error (attempt {attempt + 1}/{max_retries + 1}): {e}")
            _sleep_backoff(attempt)
    raise last_exc 

def build_count_query(prefixes, named_graph, rdf_types):
    return (
        prefixes
        + f"\nSELECT (COUNT(?subject) AS ?total) WHERE {{ GRAPH <{named_graph}> "
          f"{{ ?subject a ?type . VALUES ?type {{ {' '.join(rdf_types)} }} "
          f"FILTER(isIri(?subject)) }} }}"
    )

def build_entities_page_query(prefixes, named_graph, rdf_types, offset, limit):
    return prefixes + f"""
        SELECT DISTINCT ?subject WHERE {{
            GRAPH <{named_graph}> {{
                ?subject a ?type .
                VALUES ?type {{ {' '.join(rdf_types)} }}
                FILTER(isIri(?subject))
            }}
        }} ORDER BY DESC(?subject) OFFSET {offset} LIMIT {limit}
    """

def normalize_candidate_ids(entities, namespace):
    candidate_ids = [
        entity[len(namespace):] if entity.startswith(namespace) else entity
        for entity in entities
    ]
    return [cid.rstrip("/") for cid in candidate_ids]

def build_wd_sameas_query(prefixes, wikidata_property, candidate_ids):
    values = " ".join(f"\"{cid}\"" for cid in candidate_ids)
    return prefixes + f"""
        PREFIX owl: <http://www.w3.org/2002/07/owl#>
        PREFIX wdt: <http://www.wikidata.org/prop/direct/>
        SELECT DISTINCT ?wdEntity ?candidateId WHERE {{
            VALUES ?candidateId {{ {values} }}
            ?wdEntity wdt:{wikidata_property} ?candidateId .
        }}
    """

def build_wd_matches_query(unique_wd_entities):
    wikidata_entities_for_values = " ".join(f"<{e}>" for e in unique_wd_entities)
    return WIKIDATA_MATCHES_QUERY_TEMPLATE.replace("$VALUES", wikidata_entities_for_values)


def main(*, endpoint, wikidata_endpoint, output_directory, page_size=PAGE_SIZE, config=None, dataset=None):
    sparqlLocal = SPARQLWrapper(endpoint)
    sparqlLocal.setReturnFormat(JSON)
    sparqlLocal.setMethod(POST)

    sparqlWikidata = SPARQLWrapper(wikidata_endpoint)
    sparqlWikidata.setReturnFormat(JSON)
    sparqlWikidata.setMethod(POST)
    sparqlWikidata.setTimeout(60)

    cfg = load_config(config)
    datasets = cfg.get("datasets", {})

    # if dataset is specified, limit to that dataset
    if dataset:
        if dataset in datasets:
            datasets = {dataset: datasets[dataset]}
        else:
            print(f"Dataset {dataset} not found in config")
            return

    for datasetName in datasets.keys():
        print(f"Processing dataset: {datasetName}")
        datasetConfig = datasets[datasetName]

        rdfTypes = []
        for _, rdfType in datasetConfig.get("types", {}).items():
            rdfTypes.extend(rdfType)

        # Load Configuration
        try:
            wikidataProperty = datasetConfig["wikidata_match_property"]
        except KeyError:
            print(f"No Wikidata match property defined for dataset {datasetName} in config, skipping...")
            continue
        try:
            namespace = datasetConfig["namespace"]
        except KeyError:
            raise KeyError(f"Namespace not defined for dataset {datasetName} in config")
        try:
            namedGraph = datasetConfig["graph"]
        except KeyError:
            raise KeyError(f"Graph not defined for dataset {datasetName} in config")

        prefixes = generate_prefixes(datasetConfig.get("prefixes", {}))

        outputPath = f"{output_directory}/{datasetName}WikidataSameAs.ttl"

        # progress bar total
        countQuery = build_count_query(prefixes, namedGraph, rdfTypes)
        totalEntities = int(
            query_with_retry(sparqlLocal, countQuery, label=f"{datasetName}:local count")[
                "results"
            ]["bindings"][0]["total"]["value"]
        )
        pbar = tqdm(total=totalEntities, desc=f"Processing {datasetName}", unit="ent")

        counter = 0
        wdEquivalentsFound = 0
        hasResults = True

        with open(outputPath, "w") as f:
            while hasResults:
                query = build_entities_page_query(prefixes, namedGraph, rdfTypes, counter, page_size)
                counter += page_size

                results = query_with_retry(sparqlLocal, query, label=f"{datasetName}:local page")

                bindings = results["results"]["bindings"]
                if not bindings:
                    hasResults = False
                    continue

                entities = [r["subject"]["value"] for r in bindings]
                pbar.update(len(entities))

                candidateIds = normalize_candidate_ids(entities, namespace)
                if not candidateIds:
                    pbar.set_postfix({"Links": wdEquivalentsFound})
                    continue

                # sameAs statements from wikidata based on configured external-id property
                sameAsQuery = build_wd_sameas_query(prefixes, wikidataProperty, candidateIds)
                sameAsResults = query_with_retry(
                    sparqlWikidata, sameAsQuery, label=f"{datasetName}:wikidata sameAs"
                )

                newWdEntities = []
                for r in sameAsResults["results"]["bindings"]:
                    localUri = namespace + r["candidateId"]["value"]
                    wdUri = r["wdEntity"]["value"]
                    f.write(f"<{localUri}> {PREDICATE} <{wdUri}> .\n")
                    newWdEntities.append(wdUri)

                wdEquivalentsFound += len(sameAsResults["results"]["bindings"])

                # retrieve formatter-url matches for the currently retrieved wikidata entities
                uniqueWdEntities = set(newWdEntities)
                if uniqueWdEntities:
                    matchesQuery = build_wd_matches_query(unique_wd_entities=uniqueWdEntities)
                    matchesResults = query_with_retry(
                        sparqlWikidata, matchesQuery, label=f"{datasetName}:wikidata matches"
                    )

                    for r in matchesResults["results"]["bindings"]:
                        if "otherEntity" in r and "value" in r["otherEntity"]:
                            wdEntity = r["wdEntity"]["value"]
                            otherEntity = r["otherEntity"]["value"]
                            f.write(f"<{otherEntity}> {PREDICATE} <{wdEntity}> .\n")

                    wdEquivalentsFound += len(matchesResults["results"]["bindings"])

                pbar.set_postfix({"Links": wdEquivalentsFound})

        pbar.close()
        print(f"Found {wdEquivalentsFound} total sameAs links for dataset {datasetName}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch matches for a dataset from Wikidata and store them.")
    parser.add_argument("--endpoint", required=True, help="SPARQL endpoint to use for querying the entities")
    parser.add_argument(
        "--wikidata-endpoint",
        required=False,
        default="https://query.wikidata.org/sparql",
        help="SPARQL endpoint to use for querying Wikidata",
    )
    parser.add_argument(
        "--output-directory",
        required=False,
        default="/data/sameAsStatements/sources",
        help="directory to store output files",
    )
    parser.add_argument("--page-size", required=False, type=int, default=PAGE_SIZE, help="number of results to fetch per query")
    parser.add_argument("--config", required=True, help="Path to YAML configuration")
    parser.add_argument("--dataset", required=False, help="Dataset to generate labels for (all datasets if not specified)")

    args = parser.parse_args()
    main(
        endpoint=args.endpoint,
        wikidata_endpoint=args.wikidata_endpoint,
        output_directory=args.output_directory,
        page_size=args.page_size,
        config=args.config,
        dataset=args.dataset if args.dataset else None,
    )