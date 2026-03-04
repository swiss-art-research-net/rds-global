import argparse

from SPARQLWrapper import SPARQLWrapper, POST, JSON
from lib.utils import load_config, generate_prefixes_for_SPARQL as generate_prefixes
from tqdm import tqdm

PAGE_SIZE = 1000
PREDICATE =  "<http://www.w3.org/2002/07/owl#sameAs>"

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

    file_num = 0

    # if dataset is specified, limit to that dataset
    if dataset:
        if dataset in datasets:
            datasets = {dataset: datasets[dataset]}
        else:
            print(f"Dataset {dataset} not found in config")
            return

    for dataset in datasets.keys():
        print(f"Processing dataset: {dataset}")
        datasetConfig = datasets[dataset]
        rdfTypes = []
        for _, rdfType in datasetConfig.get("types", {}).items():
            rdfTypes.extend(rdfType)

        # Load Configuration
        try:
            wikidataProperty = datasetConfig['wikidata_match_property']
        except KeyError:
            # Gracefully exit if no wikidata match property is defined for the dataset, since this is required to fetch sameAs links from Wikidata
            print(f"No Wikidata match property defined for dataset {dataset} in config, skipping...")
            continue
        try:
            namespace = datasetConfig['namespace']
        except KeyError:
            raise KeyError(f"Namespace not defined for dataset {dataset} in config")
        try:
            namedGraph = datasetConfig['graph']
        except KeyError:
            raise KeyError(f"Graph not defined for dataset {dataset} in config")
        
        counter = 0
        wdEquivalentsFound = 0
        prefixes = generate_prefixes(datasetConfig.get("prefixes", {}))
        hasResults = True

        outputPath = f"{output_directory}/{dataset}WikidataSameAs.ttl"

        # Initialize the progress bar
        countQuery = prefixes + f"SELECT (COUNT(?subject) AS ?total) WHERE {{ GRAPH <{namedGraph}> {{ ?subject a ?type . VALUES ?type {{ {' '.join(rdfTypes)} }} FILTER(isIri(?subject)) }} }}"
        sparqlLocal.setQuery(countQuery)
        totalEntities = int(sparqlLocal.query().convert()["results"]["bindings"][0]["total"]["value"])
        pbar = tqdm(total=totalEntities, desc=f"Processing {dataset}", unit="ent")

        with open(outputPath, "w") as f:
            while hasResults:
                query = prefixes + f"""
                SELECT ?subject WHERE {{
                        GRAPH <{namedGraph}> {{
                            ?subject a ?type .
                            VALUES ?type {{ {' '.join(rdfTypes)} }}
                            FILTER(isIri(?subject))
                        }}
                    }} ORDER BY DESC(?subject) OFFSET {counter} LIMIT {page_size}"""
                counter = counter + page_size
                sparqlLocal.setQuery(query)

                try:
                    results = sparqlLocal.query().convert()
                except Exception as e:
                    print(f"Error querying SPARQL endpoint: {e}")
                    print(f"Query: {query}")
                    return
                
                if len(results["results"]["bindings"]) == 0:
                    hasResults = False
                    continue

                entities = [result["subject"]["value"] for result in results["results"]["bindings"]]
                pbar.update(len(entities))

                # Strip namespace from entities to get candidate IDs for Wikidata query
                candidateIds = [
                    entity[len(namespace):] if entity.startswith(namespace) else entity
                    for entity in entities
                ]
                # Strip trailing slash from candidate IDs if present
                candidateIds = [cid.rstrip('/') for cid in candidateIds]

                # for each page of entities we query wikidata for sameAs statements
                sameAsQuery = prefixes + f"""
                    PREFIX owl: <http://www.w3.org/2002/07/owl#>
                    PREFIX wdt: <http://www.wikidata.org/prop/direct/>
                    SELECT ?wdEntity ?candidateId WHERE {{
                        VALUES ?candidateId {{ {' '.join(f'"{candidateId}"' for candidateId in candidateIds)} }}
                        ?wdEntity wdt:{wikidataProperty} ?candidateId .
                    }}
                """

                sparqlWikidata.setQuery(sameAsQuery)
                try:
                    sameAsResults = sparqlWikidata.query().convert()
                except Exception as e:
                    print(f"Error querying Wikidata SPARQL endpoint: {e}")
                    print(f"Query: {sameAsQuery}")
                    return
                
                newWdEntities = []
                for result in sameAsResults["results"]["bindings"]:
                    localUri = namespace + result["candidateId"]["value"]
                    wdUri = result["wdEntity"]["value"]
                    f.write(f"<{localUri}> {PREDICATE} <{wdUri}> .\n")
                    newWdEntities.append(wdUri)

                wdEquivalentsFound = wdEquivalentsFound + len(sameAsResults["results"]["bindings"])

                # Retrieve matches from wikidata for the currently retrieved wikidata entities
                if newWdEntities:
                    wikidataEntitiesForValues = [f"<{entity}>" for entity in newWdEntities]
                    matchesQuery = WIKIDATA_MATCHES_QUERY_TEMPLATE.replace("$VALUES", " ".join(wikidataEntitiesForValues))
                    sparqlWikidata.setQuery(matchesQuery)

                    try:
                        matchesResults = sparqlWikidata.query().convert()
                    except Exception as e:
                        print(f"Error querying Wikidata SPARQL endpoint for matches: {e}")
                        print(f"Query: {matchesQuery}")
                        raise e
                    
                    for result in matchesResults["results"]["bindings"]:
                        if "otherEntity" in result and "value" in result["otherEntity"]:
                            wdEntity = result["wdEntity"]["value"]
                            otherEntity = result["otherEntity"]["value"]
                            f.write(f"<{otherEntity}> {PREDICATE} <{wdEntity}> .\n")
                    wdEquivalentsFound = wdEquivalentsFound + len(matchesResults["results"]["bindings"])
                
                pbar.set_postfix({"Links": wdEquivalentsFound})
        pbar.close()
        print(f"Found {wdEquivalentsFound} total sameAs links for dataset {dataset}")

            
        

if __name__ == "__main__":    
    parser = argparse.ArgumentParser(description = 'Fetch matches for a dataset from Wikidata and store them.')
    parser.add_argument('--endpoint',required=True, help='SPARQL endpoint to use for querying the entities')
    parser.add_argument('--wikidata-endpoint', required=False, default='https://query.wikidata.org/sparql', help='SPARQL endpoint to use for querying Wikidata')
    parser.add_argument('--output-directory', required=False, default='/data/sameAsStatements/sources', help='directory to store output files')
    parser.add_argument('--page-size', required=False, type=int, default=PAGE_SIZE, help='number of results to fetch per query')
    parser.add_argument("--config", required=True, help="Path to YAML configuration")
    parser.add_argument("--dataset", required=False, help="Dataset to generate labels for (all datasets if not specified)")
    
    args = parser.parse_args()
    endpoint = args.endpoint
    output_directory = args.output_directory
    config = args.config
    dataset = args.dataset if args.dataset else None
    wikidata_endpoint = args.wikidata_endpoint
 
    page_size = args.page_size
    main(endpoint=endpoint, wikidata_endpoint=wikidata_endpoint, output_directory=output_directory, page_size=page_size, config=config, dataset=dataset)