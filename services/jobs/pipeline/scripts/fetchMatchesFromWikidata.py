import argparse
import csv
import random
import time

from SPARQLWrapper import SPARQLWrapper, POST, JSON
from lib.utils import load_config, generate_prefixes_for_SPARQL as generate_prefixes
from tqdm import tqdm

PAGE_SIZE = 1000
PREDICATE_SAMEAS = "<http://www.w3.org/2002/07/owl#sameAs>"
PREDICATE_DESCRIPTION = "<http://www.w3.org/2000/01/rdf-schema#comment>"
DEFAULT_TYPES_QUERY = "?subject a ?value ."

WIKIDATA_MATCHES_QUERY_TEMPLATE = """
    PREFIX wd: <http://www.wikidata.org/entity/>
    PREFIX wdt: <http://www.wikidata.org/prop/direct/>
    PREFIX wikibase: <http://wikiba.se/ontology#>
    SELECT DISTINCT ?wdEntity ?otherEntity ?propEntityLabel WHERE {
        VALUES ?wdEntity { $VALUES }
        VALUES (?directPredicate ?formatter ?propEntityLabel) { $PREDICATES_FORMATTERS_AND_LABELS }
        ?wdEntity ?directPredicate ?idValue .
        BIND (REPLACE(?formatter, "\\\\$1", ?idValue) AS ?otherEntity)
    }
"""

_TURTLE_IRIREF_FORBIDDEN = set(['<', '>', '"', '{', '}', '|', '\\', '^', '`'])

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

def build_count_query(prefixes, named_graph, rdf_types, types_query=DEFAULT_TYPES_QUERY):
    types_query = types_query.replace("?value", "?type")
    return (
        prefixes
        + f"\nSELECT (COUNT(DISTINCT ?subject) AS ?total) WHERE {{ GRAPH <{named_graph}> "
          f"{{ {types_query} VALUES ?type {{ {' '.join(rdf_types)} }} "
          f"FILTER(isIri(?subject)) }} }}"
    )

def build_entities_page_query(prefixes, named_graph, rdf_types, offset, limit, types_query=DEFAULT_TYPES_QUERY):
    types_query = types_query.replace("?value", "?type")
    return prefixes + f"""
        SELECT DISTINCT ?subject WHERE {{
            GRAPH <{named_graph}> {{
                {types_query}
                VALUES ?type {{ {' '.join(rdf_types)} }}
                FILTER(isIri(?subject))
            }}
        }} ORDER BY DESC(?subject) OFFSET {offset} LIMIT {limit}
    """

def is_valid_turtle_iri(iri):
    if not iri:
        return False
    for ch in iri:
        o = ord(ch)
        if o <= 0x20 or o == 0x7F:
            return False
        if ch in _TURTLE_IRIREF_FORBIDDEN:
            return False
    return True

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

def build_wd_matches_query(unique_wd_entities, wikidata_external_id_properties):
    wikidata_entities_for_values = " ".join(f"<{e}>" for e in unique_wd_entities)
    predicates_and_formatter_values = []
    for prop in wikidata_external_id_properties:
        directPredicate = prop['directPredicate']
        formatter = prop['formatter']
        propEntityLabel = prop['propEntityLabel']
        if not formatter:
            continue
        predicates_and_formatter_values.append(f"( <{directPredicate}> \"{formatter}\" \"{propEntityLabel}\" )")
    return WIKIDATA_MATCHES_QUERY_TEMPLATE.replace("$VALUES", wikidata_entities_for_values).replace("$PREDICATES_FORMATTERS_AND_LABELS", " ".join(predicates_and_formatter_values))


def main(*, endpoint, wikidata_endpoint, wikidata_properties_csv, output_directory, page_size=PAGE_SIZE, config=None, dataset=None):
    sparqlLocal = SPARQLWrapper(endpoint)
    sparqlLocal.setReturnFormat(JSON)
    sparqlLocal.setMethod(POST)

    sparqlWikidata = SPARQLWrapper(wikidata_endpoint)
    sparqlWikidata.setReturnFormat(JSON)
    sparqlWikidata.setMethod(POST)
    sparqlWikidata.setTimeout(60)

    cfg = load_config(config)
    datasets = cfg.get("datasets", {})

    wikidata_external_id_properties = []
    try:
        with open(wikidata_properties_csv, "r", newline="") as f:
            reader = csv.DictReader(f, delimiter=';')
            for row in reader:
                if row['use']:
                    wikidata_external_id_properties.append(row)
    except Exception as e:
        print(f"Error reading Wikidata properties CSV: {e}")
        return

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
        typesQuery = datasetConfig.get("queries", {}).get("types", DEFAULT_TYPES_QUERY)
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
        countQuery = build_count_query(prefixes, namedGraph, rdfTypes, types_query=typesQuery)
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
                query = build_entities_page_query(prefixes, namedGraph, rdfTypes, counter, page_size, types_query=typesQuery)
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
                    f.write(f"<{localUri}> {PREDICATE_SAMEAS} <{wdUri}> .\n")
                    newWdEntities.append(wdUri)

                wdEquivalentsFound += len(sameAsResults["results"]["bindings"])

                # retrieve formatter-url matches for the currently retrieved wikidata entities
                uniqueWdEntities = set(newWdEntities)
                if uniqueWdEntities:
                    matchesQuery = build_wd_matches_query(unique_wd_entities=uniqueWdEntities, wikidata_external_id_properties=wikidata_external_id_properties)
                    matchesResults = query_with_retry(
                        sparqlWikidata, matchesQuery, label=f"{datasetName}:wikidata matches"
                    )

                    match_bindings = matchesResults["results"]["bindings"]
                    written_matches = 0
                    for r in match_bindings:
                        if "otherEntity" in r and "value" in r["otherEntity"]:
                            wdEntity = r["wdEntity"]["value"]
                            otherEntity = r["otherEntity"]["value"]
                            propEntityLabel = r["propEntityLabel"]["value"]
                            if is_valid_turtle_iri(otherEntity):
                                f.write(f"<{otherEntity}> {PREDICATE_SAMEAS} <{wdEntity}> .\n")
                                f.write(f"<{otherEntity}> {PREDICATE_DESCRIPTION} \"{propEntityLabel}\" .\n")
                                written_matches += 1

                    wdEquivalentsFound += written_matches

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
        "--wikidata-properties-csv",
        required=True,
        help="Path to CSV file containing Wikidata properties to use for matching"
    )
    parser.add_argument(
        "--output-directory",
        required=False,
        default="/data/sameAsStatements/sources",
        help="directory to store output files",
    )
    parser.add_argument("--page-size", required=False, type=int, default=PAGE_SIZE, help="number of results to fetch per query")
    parser.add_argument("--config", required=True, help="Path to YAML configuration")
    parser.add_argument("--dataset", required=False, help="Dataset to fetch Wikidata matches for (all datasets if not specified)")

    args = parser.parse_args()
    main(
        endpoint=args.endpoint,
        wikidata_endpoint=args.wikidata_endpoint,
        wikidata_properties_csv=args.wikidata_properties_csv,
        output_directory=args.output_directory,
        page_size=args.page_size,
        config=args.config,
        dataset=args.dataset if args.dataset else None,
    )